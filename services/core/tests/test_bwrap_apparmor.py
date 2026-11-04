"""deploy/bwrap-apparmor.sh: the installer's AppArmor step for bwrap (the gateways'
cage) on a fake machine (review L5). It prefers the system's own extra-profiles copy,
leaves a profile the admin disabled alone, and never stops by itself when the parser
can't read the profile (an older AppArmor): the installer's cage self-test after it
(deploy/cage-setup.sh, tests/test_cage_setup.py) refuses with cage_refused then."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
NAME = "bwrap-userns-restrict"
SHIMS = {
    # bwrap runs once $FAKE/bwrap-ok exists (the profile "loaded").
    "runuser": '#!/usr/bin/env bash\necho "runuser $*" >> "$FAKE/calls"\n[[ -f "$FAKE/bwrap-ok" ]]\n',
    "apparmor_parser": (
        '#!/usr/bin/env bash\necho "apparmor_parser $*" >> "$FAKE/calls"\n'
        '[[ -f "$FAKE/parser-fails" ]] && { echo "parser: unknown abi" >&2; exit 1; }\n'
        'touch "$FAKE/bwrap-ok"\n'
    ),
}


def _machine(tmp_path: Path, *, restricted: bool = True) -> dict[str, str]:
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "calls").write_text("")
    for name, body in SHIMS.items():
        (fake / name).write_text(body)
        (fake / name).chmod(stat.S_IRWXU)
    (tmp_path / "etc" / "disable").mkdir(parents=True)
    (tmp_path / "extra").mkdir()
    (tmp_path / "restrict").write_text("1\n" if restricted else "0\n")
    return {
        "PATH": f"{fake}:/usr/bin:/bin",
        "FAKE": str(fake),
        "AGOS_APPARMOR_DIR": str(tmp_path / "etc"),
        "AGOS_APPARMOR_EXTRA": str(tmp_path / "extra"),
        "AGOS_USERNS_RESTRICT": str(tmp_path / "restrict"),
    }


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(DEPLOY / "bwrap-apparmor.sh")],  # noqa: S607
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_the_systems_own_extra_profiles_copy_is_preferred(tmp_path: Path) -> None:
    env = _machine(tmp_path)
    (tmp_path / "extra" / NAME).write_text("# the system's own copy\n")
    done = _run(env)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "etc" / NAME).read_text() == "# the system's own copy\n"
    assert (
        f"apparmor_parser -r -W {tmp_path / 'etc' / NAME}"
        in (tmp_path / "fake" / "calls").read_text()
    )


def test_agos_own_copy_where_the_system_ships_none(tmp_path: Path) -> None:
    env = _machine(tmp_path)
    assert _run(env).returncode == 0
    assert (tmp_path / "etc" / NAME).read_text() == (DEPLOY / "apparmor" / NAME).read_text()


def test_a_profile_the_admin_disabled_is_never_loaded(tmp_path: Path) -> None:
    env = _machine(tmp_path)
    (tmp_path / "etc" / NAME).write_text("# Ubuntu's\n")
    (tmp_path / "etc" / "disable" / NAME).symlink_to(tmp_path / "etc" / NAME)
    done = _run(env)
    assert done.returncode == 0
    assert "apparmor_parser" not in (tmp_path / "fake" / "calls").read_text()
    assert "disabled" in done.stderr + done.stdout


def test_a_parser_that_cannot_read_the_profile_warns_and_leaves_it_to_the_self_test(
    tmp_path: Path,
) -> None:
    env = _machine(tmp_path)
    (tmp_path / "fake" / "parser-fails").touch()
    done = _run(env)
    assert done.returncode == 0
    assert "the cage self-test will say what to do (code cage_refused)" in done.stderr


def test_nothing_happens_where_bwrap_already_runs_or_userns_is_free(tmp_path: Path) -> None:
    env = _machine(tmp_path, restricted=False)
    assert _run(env).returncode == 0
    assert not (tmp_path / "etc" / NAME).exists()
    (tmp_path / "restrict").write_text("1\n")
    (tmp_path / "fake" / "bwrap-ok").touch()
    assert _run(env).returncode == 0
    assert not (tmp_path / "etc" / NAME).exists()


def test_the_installer_runs_this_step_and_no_inline_copy() -> None:
    """Through deploy/cage-setup.sh install, the installer's one cage step."""
    assert 'bash "$HERE/bwrap-apparmor.sh"' in (DEPLOY / "cage-setup.sh").read_text()
    assert "apparmor_parser -r" not in (DEPLOY / "install-server.sh").read_text()
