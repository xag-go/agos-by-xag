"""scripts/release.py: cutting a release (docs/releases.md, ADR 0028). The version
grammar, the CHANGELOG move from [Unreleased] to the release's section, the README
badge, the local commit + annotated tag (never pushed), and the release workflow's gate
(`check`: the tag, VERSION and CHANGELOG agree)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agos_release", REPO / "scripts/release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


release = _load()

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- A new thing.

## [0.1.0] - 2026-11-02

### Added

- The first release.

[0.1.0]: https://github.com/xag-go/agos-by-xag/releases/tag/v0.1.0
"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "agos"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "tag.gpgsign", "false")
    (root / "CHANGELOG.md").write_text(CHANGELOG)
    (root / "README.md").write_text(
        "![version](<https://img.shields.io/badge/version-v0.1.0_(beta)-blue>)\n"
    )
    (root / "VERSION").write_text("0.1.0\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "start")
    return root


@pytest.mark.parametrize("good", ["0.1.0", "1.2.3", "0.2.0-beta.1", "1.0.0-rc.2"])
def test_release_versions_are_semver(good: str) -> None:
    release.parse(good)


@pytest.mark.parametrize("bad", ["v0.1.0", "0.1", "0.1.0-alpha.1", "0.1.0-beta", "01.2.3x"])
def test_anything_else_is_refused_with_a_reason(bad: str) -> None:
    with pytest.raises(release.ReleaseError, match="not a release version"):
        release.parse(bad)


def test_unreleased_becomes_the_release_section_under_a_new_empty_unreleased() -> None:
    out = release.bump_changelog(CHANGELOG, "0.2.0", "2026-12-01")
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-12-01\n\n### Added\n\n- A new thing." in out
    assert release.section(out, "0.2.0") == "### Added\n\n- A new thing."
    assert release.section(out, "Unreleased") == ""
    assert release.section(out, "0.1.0") == "### Added\n\n- The first release."
    assert out.endswith("[0.2.0]: https://github.com/xag-go/agos-by-xag/releases/tag/v0.2.0\n")


def test_an_empty_unreleased_or_a_second_release_of_a_version_is_refused() -> None:
    empty = CHANGELOG.replace("### Added\n\n- A new thing.\n\n", "", 1)
    with pytest.raises(release.ReleaseError, match="empty"):
        release.bump_changelog(empty, "0.2.0", "2026-12-01")
    with pytest.raises(release.ReleaseError, match="already has"):
        release.bump_changelog(CHANGELOG, "0.1.0", "2026-12-01")


def test_the_badge_shows_the_version_and_beta_while_0_x() -> None:
    readme = "![version](<https://img.shields.io/badge/version-v0.1.0_(beta)-blue>)"
    assert "version-v0.2.0_(beta)-blue" in release.bump_badge(readme, "0.2.0")
    assert "version-v1.0.0--rc.1_(beta)-blue" in release.bump_badge(readme, "1.0.0-rc.1")
    assert "version-v1.0.0-blue" in release.bump_badge(readme, "1.0.0")


def test_prepare_makes_one_commit_and_an_annotated_tag_and_pushes_nothing(repo: Path) -> None:
    tag = release.prepare("0.2.0", today="2026-12-01", root=repo)
    assert tag == "v0.2.0"
    assert (repo / "VERSION").read_text() == "0.2.0\n"
    assert _git(repo, "log", "-1", "--format=%s") == "Release 0.2.0"
    assert _git(repo, "cat-file", "-t", "v0.2.0") == "tag"  # annotated
    assert _git(repo, "rev-parse", "v0.2.0^{commit}") == _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "remote") == ""
    release.check("v0.2.0", root=repo)  # the workflow's gate passes on what prepare made


def test_prepare_refuses_a_dirty_tree_or_an_existing_tag(repo: Path) -> None:
    (repo / "VERSION").write_text("dirty\n")
    with pytest.raises(release.ReleaseError, match="working tree has changes"):
        release.prepare("0.2.0", root=repo)
    _git(repo, "checkout", "-q", "VERSION")
    _git(repo, "tag", "-a", "v0.2.0", "-m", "x")
    with pytest.raises(release.ReleaseError, match="exists already"):
        release.prepare("0.2.0", root=repo)


def test_check_refuses_a_tag_that_does_not_match_version_or_changelog(repo: Path) -> None:
    with pytest.raises(release.ReleaseError, match=r"VERSION says 0\.1\.0"):
        release.check("v0.2.0", root=repo)
    (repo / "VERSION").write_text("0.3.0\n")
    with pytest.raises(release.ReleaseError, match=r"no \(or an empty\) \[0.3.0\]"):
        release.check("v0.3.0", root=repo)
    with pytest.raises(release.ReleaseError, match="not a release tag"):
        release.check("0.3.0", root=repo)


def test_manifest_names_the_tagged_commit_and_its_tree(repo: Path) -> None:
    release.prepare("0.2.0", today="2026-12-01", root=repo)
    found = release.manifest("v0.2.0", root=repo)
    assert found == {
        "tag": "v0.2.0",
        "version": "0.2.0",
        "commit": _git(repo, "rev-parse", "HEAD"),
        "tree": _git(repo, "rev-parse", "HEAD^{tree}"),
    }
    json.dumps(found)  # release.json


def test_every_release_tag_of_this_repository_has_its_changelog_section() -> None:
    """A release's notes are its CHANGELOG section. The first public release is
    v0.1.0; the pre-public development tags v0.1.1 and v0.1.2 (local, never
    published) have no section of their own: their notes are part of v0.1.0's."""
    tags = subprocess.run(
        ["git", "tag", "-l", "v[0-9]*"],  # noqa: S607
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    text = (REPO / "CHANGELOG.md").read_text()
    pre_public = {"v0.1.1", "v0.1.2"}
    assert not release.section(text, "0.1.1") and not release.section(text, "0.1.2")
    for version in ["0.1.0"] + [t[1:] for t in tags if t not in pre_public]:
        assert release.section(text, version), f"CHANGELOG.md has no [{version}] section"


def test_the_release_workflow_publishes_what_the_installer_checks() -> None:
    """deploy/release-verify.sh downloads release.json, SHA256SUMS and its Sigstore
    bundle, and trusts only release.yml's identity: the workflow makes exactly those,
    signs with the same cosign, and gates on scripts/release.py check."""
    workflow = (REPO / ".github/workflows/release.yml").read_text()
    verify = (REPO / "deploy/release-verify.sh").read_text()
    for name in ("release.json", "SHA256SUMS", "SHA256SUMS.sigstore.json"):
        assert name in workflow and name in verify
    assert r"release\.yml@refs/tags/v" in verify
    cosign = verify.split("COSIGN_VERSION=", 1)[1].split()[0]
    assert f"cosign-release: {cosign}" in workflow
    assert 'scripts/release.py check "$TAG"' in workflow
    assert "attest-build-provenance" in workflow and "id-token: write" in workflow
    assert "pull_request" not in workflow
