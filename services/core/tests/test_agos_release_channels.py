"""Release channels and the signed-release check in deploy/agos (ADR 0028), on the
fake machine of test_agos_cli.py: real git tags, a release folder served as files,
and a `cosign` shim (the real signature check runs in deploy/test-upgrade-vm.sh and
docs/releases.md's proof; GitHub CI has no cosign)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from test_agos_cli import AGOS, Machine, _exe, _git, machine

__all__ = ["machine"]  # the fixture, used by name below

VERIFY = AGOS.parent / "release-verify.sh"
COSIGN = """#!/usr/bin/env bash
echo "cosign $*" >> "$FAKE/calls"
[[ -f "$FAKE/bad-signature" ]] && { echo "invalid signature" >&2; exit 1; }
exit 0
"""


def _channel(m: Machine, name: str) -> None:
    conf = Path(m.env["AGOS_CONF"])
    conf.write_text(conf.read_text().replace("AGOS_CHANNEL=main", f"AGOS_CHANNEL={name}"))


def _tag(m: Machine, tag: str, message: str) -> str:
    """One more commit on main, tagged and pushed."""
    src = m.root / "src"
    sha = m.release(message)
    _git(src, "tag", "-a", tag, "-m", tag)
    _git(src, "push", "-q", "origin", tag)
    return sha


def _publish_assets(m: Machine, tag: str, sha: str, commit: str | None = None) -> None:
    """What the release workflow puts beside a tag: release.json, SHA256SUMS, its bundle."""
    folder = m.root / "releases" / tag
    folder.mkdir(parents=True)
    manifest = json.dumps({"tag": tag, "version": tag[1:], "commit": commit or sha})
    (folder / "release.json").write_text(manifest)
    digest = hashlib.sha256(manifest.encode()).hexdigest()
    (folder / "SHA256SUMS").write_text(f"{digest}  release.json\n")
    (folder / "SHA256SUMS.sigstore.json").write_text("{}")


@pytest.fixture
def released(machine: Machine) -> Machine:
    """The install runs a release that has the checker; the cosign shim; the releases folder."""
    src = machine.root / "src"
    shutil.copy(VERIFY, src / "deploy" / "release-verify.sh")
    machine.release("The release checker")
    _git(machine.app, "pull", "-q", "--ff-only", "origin", "main")
    _exe(Path(machine.env["FAKE"]) / "bin" / "cosign", COSIGN)
    # file:// URLs: the real curl (the fake machine's curl shim answers only the core).
    real_curl = shutil.which("curl", path="/usr/bin:/bin") or "/usr/bin/curl"
    _exe(
        Path(machine.env["FAKE"]) / "bin" / "curl",
        "#!/usr/bin/env bash\n"
        f'for a in "$@"; do [[ "$a" == file://* ]] && exec {real_curl} "$@"; done\n'
        + (Path(machine.env["FAKE"]) / "bin" / "curl").read_text().split("\n", 1)[1],
    )
    machine.env["AGOS_RELEASES_URL"] = f"file://{machine.root / 'releases'}"
    return machine


def _head(m: Machine) -> str:
    return _git(m.app, "rev-parse", "HEAD")


def test_stable_takes_the_newest_release_tag_beta_also_betas_main_the_branch(
    released: Machine,
) -> None:
    m = released
    _tag(m, "v0.1.1", "Hotfix")
    beta = _tag(m, "v0.2.0-beta.1", "New board, beta")
    tip = m.release("Work in progress on main")
    _channel(m, "stable")
    out = m.agos("update", "--check").stdout
    assert "stable channel: v0.1.1" in out and "Work in progress" not in out
    assert "New board, beta" not in out
    out = m.agos("update", "--check", "--channel", "beta").stdout
    assert "beta channel: v0.2.0-beta.1" in out and beta[:12] in out
    out = m.agos("update", "--check", "--channel", "main").stdout
    assert tip[:12] in out and "Work in progress on main" in out
    # read-only: nothing moved
    assert not m.snapshots()


def test_a_beta_never_outranks_its_own_release(released: Machine) -> None:
    m = released
    _tag(m, "v0.2.0-beta.1", "Beta 1")
    final = _tag(m, "v0.2.0", "The release")
    _channel(m, "beta")
    out = m.agos("update", "--check").stdout
    assert "beta channel: v0.2.0 " in out and final[:12] in out


def test_an_update_only_moves_forward(released: Machine) -> None:
    """An install on newer code than the newest release (e.g. it followed main) stays."""
    m = released
    _tag(m, "v0.1.1", "Hotfix")
    m.release("Newer work on main")
    m.agos("update", "--yes")  # channel main: the tip
    tip = _head(m)
    _channel(m, "stable")
    out = m.agos("update", "--yes").stdout
    assert "up to date" in out and "newer than v0.1.1" in out
    assert _head(m) == tip


def test_no_release_yet_is_up_to_date(released: Machine) -> None:
    _channel(released, "stable")
    out = released.agos("update", "--check").stdout
    assert "up to date" in out and "no stable release is published yet" in out


def test_an_install_without_a_channel_follows_stable(released: Machine) -> None:
    m = released
    conf = Path(m.env["AGOS_CONF"])
    conf.write_text(conf.read_text().replace("AGOS_CHANNEL=main\n", ""))
    m.release("Untagged work on main")
    out = m.agos("update", "--check").stdout
    assert "up to date" in out and "stable channel" in out


def test_a_verified_release_updates(released: Machine) -> None:
    m = released
    sha = _tag(m, "v0.1.1", "Hotfix")
    _publish_assets(m, "v0.1.1", sha)
    _channel(m, "stable")
    out = m.agos("update", "--yes").stdout
    assert "release v0.1.1 verified" in out
    assert _head(m) == sha
    calls = (Path(m.env["FAKE"]) / "calls").read_text()
    assert "cosign verify-blob" in calls and "--certificate-oidc-issuer" in calls
    assert "release\\.yml@refs/tags/v" in calls  # the official workflow's identity


@pytest.mark.parametrize(
    "broken",
    ["no-assets", "bad-signature", "other-commit", "other-tag", "wrong-checksum"],
)
def test_an_unverified_release_changes_nothing(released: Machine, broken: str) -> None:
    m = released
    before = _head(m)
    sha = _tag(m, "v0.1.1", "Hotfix")
    if broken != "no-assets":
        _publish_assets(m, "v0.1.1", sha, commit="f" * 40 if broken == "other-commit" else None)
    folder = m.root / "releases" / "v0.1.1"
    if broken == "bad-signature":
        (Path(m.env["FAKE"]) / "bad-signature").write_text("")
    if broken == "other-tag":
        (folder / "release.json").write_text(json.dumps({"tag": "v9.9.9", "commit": sha}))
        digest = hashlib.sha256((folder / "release.json").read_bytes()).hexdigest()
        (folder / "SHA256SUMS").write_text(f"{digest}  release.json\n")
    if broken == "wrong-checksum":
        (folder / "SHA256SUMS").write_text(f"{'0' * 64}  release.json\n")
    _channel(m, "stable")
    done = m.agos("update", "--yes", check=False)
    assert done.returncode != 0
    assert "is not verified" in done.stderr and "Nothing was changed" in done.stderr
    assert _head(m) == before
    assert not m.snapshots()  # stopped before the backup, the snapshot and the stop
    state = json.loads((m.data / "system" / "agos-update.json").read_text())
    assert state["phase"] == "failed" and "not verified" in state["error"]
    calls = (Path(m.env["FAKE"]) / "calls").read_text()
    assert "systemctl stop" not in calls


def test_verify_warn_goes_on_and_says_so(released: Machine) -> None:
    m = released
    sha = _tag(m, "v0.1.1", "Hotfix")
    _channel(m, "stable")
    done = m.agos("update", "--yes", AGOS_VERIFY="warn")
    assert "is NOT verified" in done.stderr
    assert _head(m) == sha


def test_agos_channel_shows_and_sets_the_channel(released: Machine) -> None:
    m = released
    _tag(m, "v0.1.1", "Hotfix")
    _channel(m, "stable")
    assert "Release channel: stable (newest: v0.1.1)" in m.agos("channel").stdout
    m.agos("channel", "beta")
    assert "AGOS_CHANNEL=beta" in Path(m.env["AGOS_CONF"]).read_text()
    assert m.agos("channel", "nightly", check=False).returncode != 0
    assert "AGOS_CHANNEL=beta" in Path(m.env["AGOS_CONF"]).read_text()
