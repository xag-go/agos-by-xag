"""deploy/cage-setup.sh: the installer's cage step on a fake machine (audit F9).

`install` adds bubblewrap with whichever package manager the system has, turns user
namespaces on where the kernel ships them off, and runs the AppArmor step
(bwrap-apparmor.sh). `self-test` runs bwrap as the AGOS user; when it can't, it
stops with the plain code `cage_refused` and the exact fix for that machine (exit
3), and the installer refuses to finish. A machine where bwrap works passes
untouched.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
SCRIPT = DEPLOY / "cage-setup.sh"
PROFILE = "bwrap-userns-restrict"
LOG = 'echo "$(basename "$0") $*" >> "$FAKE/calls"\n'
# bwrap works once $FAKE/bwrap-ok exists; it is "installed" once $FAKE/bin/bwrap is.
BWRAP = (
    "#!/usr/bin/env bash\n" + LOG + '[[ -f "$FAKE/bwrap-ok" ]] && exit 0\n'
    'echo "bwrap: setting up uid map: Permission denied" >&2; exit 1\n'
)
SHIMS = {
    "runuser": "#!/usr/bin/env bash\n"
    + LOG
    + 'while [[ "$1" != -- ]]; do shift; done; shift\n"$@"\n',
    "apparmor_parser": "#!/usr/bin/env bash\n" + LOG + 'touch "$FAKE/bwrap-ok"\n',
    "id": '#!/usr/bin/env bash\n[[ "$1" == -un ]] && { echo root; exit 0; }\n/usr/bin/id "$@"\n',
}
MANAGER = "#!/usr/bin/env bash\n" + LOG + 'cp "$FAKE/bwrap.real" "$FAKE/bin/bwrap"\n'


def _machine(
    tmp_path: Path, *, manager: str | None = "apt-get", bwrap: bool = False
) -> dict[str, str]:
    fake = tmp_path / "fake"
    (fake / "bin").mkdir(parents=True)
    (fake / "calls").write_text("")
    (fake / "bwrap.real").write_text(BWRAP)
    (fake / "bwrap.real").chmod(stat.S_IRWXU)
    shims = dict(SHIMS)
    if manager:
        shims[manager] = MANAGER
    for name, body in shims.items():
        (fake / "bin" / name).write_text(body)
        (fake / "bin" / name).chmod(stat.S_IRWXU)
    if bwrap:
        (fake / "bin" / "bwrap").write_text(BWRAP)
        (fake / "bin" / "bwrap").chmod(stat.S_IRWXU)
    proc = tmp_path / "proc"
    for knob, value in (
        ("kernel/apparmor_restrict_unprivileged_userns", "0"),
        ("user/max_user_namespaces", "63000"),
    ):
        (proc / knob).parent.mkdir(parents=True, exist_ok=True)
        (proc / knob).write_text(value + "\n")
    (tmp_path / "apparmor" / "disable").mkdir(parents=True)
    # Only the fake bin and the shell's own tools: no real bwrap or apt-get here.
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in ("bash", "cat", "head", "basename", "mkdir", "dirname", "sed", "cp", "touch",
                 "install", "printf"):  # fmt: skip
        real = next(Path(d) / tool for d in ("/usr/bin", "/bin") if (Path(d) / tool).exists())
        (tools / tool).symlink_to(real)
    return {
        "PATH": f"{fake / 'bin'}:{tools}",
        "FAKE": str(fake),
        "AGOS_PROC_SYS": str(proc),
        "AGOS_SYSCTL_DIR": str(tmp_path / "sysctl.d"),
        "AGOS_APPARMOR_DIR": str(tmp_path / "apparmor"),
        "AGOS_APPARMOR_EXTRA": str(tmp_path / "extra"),
    }


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def _calls(env: dict[str, str]) -> str:
    return (Path(env["FAKE"]) / "calls").read_text()


@pytest.mark.parametrize(
    ("manager", "said"),
    [
        ("apt-get", "apt-get install -y -q bubblewrap"),
        ("dnf", "dnf install -y bubblewrap"),
        ("zypper", "zypper --non-interactive install bubblewrap"),
        ("pacman", "pacman -S --noconfirm --needed bubblewrap"),
        ("apk", "apk add bubblewrap"),
    ],
)
def test_install_adds_bubblewrap_with_the_systems_own_package_manager(
    tmp_path: Path, manager: str, said: str
) -> None:
    env = _machine(tmp_path, manager=manager)
    done = _run(env, "install")
    assert done.returncode == 0, done.stderr
    assert said in _calls(env)
    assert (Path(env["FAKE"]) / "bin" / "bwrap").is_file()


def test_install_leaves_an_installed_bwrap_alone(tmp_path: Path) -> None:
    env = _machine(tmp_path, bwrap=True)
    assert _run(env, "install").returncode == 0
    assert "apt-get" not in _calls(env)


@pytest.mark.parametrize(
    ("knob", "key", "want"),
    [
        ("kernel/unprivileged_userns_clone", "kernel.unprivileged_userns_clone", "1"),
        ("user/max_user_namespaces", "user.max_user_namespaces", "15000"),
    ],
)
def test_install_turns_user_namespaces_on_where_the_kernel_has_them_off(
    tmp_path: Path, knob: str, key: str, want: str
) -> None:
    env = _machine(tmp_path, bwrap=True)
    (Path(env["AGOS_PROC_SYS"]) / knob).write_text("0\n")
    assert _run(env, "install").returncode == 0
    assert (Path(env["AGOS_PROC_SYS"]) / knob).read_text().strip() == want
    kept = (Path(env["AGOS_SYSCTL_DIR"]) / "60-agos-userns.conf").read_text()
    assert f"{key} = {want}" in kept  # kept across reboots


def test_install_loads_the_apparmor_profile_where_ubuntu_restricts_userns(tmp_path: Path) -> None:
    env = _machine(tmp_path, bwrap=True)
    (Path(env["AGOS_PROC_SYS"]) / "kernel/apparmor_restrict_unprivileged_userns").write_text("1\n")
    assert _run(env, "install").returncode == 0
    profile = Path(env["AGOS_APPARMOR_DIR"]) / PROFILE
    assert profile.read_text() == (DEPLOY / "apparmor" / PROFILE).read_text()
    assert f"apparmor_parser -r -W {profile}" in _calls(env)
    # ...after which the cage works: the self-test passes as the AGOS user.
    done = _run(env, "self-test", "agos")
    assert done.returncode == 0, done.stderr
    assert "runuser -u agos -- bwrap --dev-bind / /" in _calls(env)


def test_self_test_passes_where_bwrap_works(tmp_path: Path) -> None:
    env = _machine(tmp_path, bwrap=True)
    (Path(env["FAKE"]) / "bwrap-ok").touch()
    done = _run(env, "self-test", "agos")
    assert done.returncode == 0, done.stderr
    assert "the cage works here" in done.stdout


def _refused(done: subprocess.CompletedProcess[str]) -> str:
    assert done.returncode == 3, done.stdout + done.stderr
    assert "ERROR cage_refused:" in done.stderr
    assert "What to do: " in done.stderr
    assert "docs/troubleshooting.md" in done.stderr
    return done.stderr


def test_self_test_refuses_without_bwrap_and_names_the_install_command(tmp_path: Path) -> None:
    env = _machine(tmp_path, manager="dnf")
    said = _refused(_run(env, "self-test", "agos"))
    assert "not installed" in said and "What to do: sudo dnf install -y bubblewrap" in said


def test_self_test_refuses_where_apparmor_blocks_bwrap_with_the_exact_fix(
    tmp_path: Path,
) -> None:
    env = _machine(tmp_path, bwrap=True)
    (Path(env["AGOS_PROC_SYS"]) / "kernel/apparmor_restrict_unprivileged_userns").write_text("1\n")
    said = _refused(_run(env, "self-test", "agos"))
    assert "AppArmor" in said and "bwrap-apparmor.sh" in said
    assert "uid map: Permission denied" in said  # bwrap's own words
    # A profile the admin disabled: the fix names that file.
    profile = Path(env["AGOS_APPARMOR_DIR"]) / PROFILE
    profile.write_text("# Ubuntu's\n")
    (Path(env["AGOS_APPARMOR_DIR"]) / "disable" / PROFILE).symlink_to(profile)
    said = _refused(_run(env, "self-test", "agos"))
    assert f"sudo rm {Path(env['AGOS_APPARMOR_DIR']) / 'disable' / PROFILE}" in said


def test_self_test_refuses_where_the_kernel_has_user_namespaces_off(tmp_path: Path) -> None:
    env = _machine(tmp_path, bwrap=True)
    (Path(env["AGOS_PROC_SYS"]) / "kernel/unprivileged_userns_clone").write_text("0\n")
    said = _refused(_run(env, "self-test", "agos"))
    assert "kernel.unprivileged_userns_clone = 1" in said and "sysctl --system" in said


def test_self_test_refuses_inside_a_box_without_user_namespaces(tmp_path: Path) -> None:
    env = _machine(tmp_path, bwrap=True)
    said = _refused(_run(env, "self-test", "agos"))
    assert "--no-cage" in said and "virtual machine" in said


# ---- the installer uses it and refuses to finish without a cage -------------------
INSTALLER = (DEPLOY / "install-server.sh").read_text()


def test_the_installer_sets_the_cage_up_and_stops_when_its_self_test_fails() -> None:
    assert 'bash "$HERE/cage-setup.sh" install' in INSTALLER
    assert 'bash "$HERE/bwrap-apparmor.sh"' not in INSTALLER  # through cage-setup only
    test_at = INSTALLER.index('if ! run bash "$HERE/cage-setup.sh" self-test "$AGOS_USER"')
    # The self-test runs as soon as the AGOS user exists, before anything heavy
    # (Hermes, the build), and its refusal ends the install with its own code.
    assert (
        INSTALLER.index("useradd --create-home") < test_at < INSTALLER.index("Hermes Agent (pinned")
    )
    assert "exit 3" in INSTALLER[test_at : test_at + 400]


def test_the_cage_can_be_turned_off_only_on_purpose_and_the_core_is_told() -> None:
    assert "--no-cage) CAGE=off" in INSTALLER
    assert 'CAGE="${AGOS_SANDBOXD:-}"' in INSTALLER
    assert "Environment=AGOS_SANDBOXD=off" in INSTALLER
    assert "AGOS_SANDBOXD=$CAGE" in INSTALLER  # kept in agos.conf for the next run
    # Nothing writes AGOS_SANDBOXD=auto or on any more: the default is required.
    assert "AGOS_SANDBOXD=auto" not in INSTALLER and "AGOS_SANDBOXD=on" not in INSTALLER


def test_the_mac_and_windows_wrappers_pass_the_choice_through() -> None:
    root = DEPLOY.parent
    assert "AGOS_SANDBOXD" in (root / "install.sh").read_text()
    assert "'AGOS_SANDBOXD'" in (root / "install.ps1").read_text()
