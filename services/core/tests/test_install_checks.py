"""The installer's machine check (the measured minimum, docs/INSTALL.md "Hardware")
and which release it installs (the newest stable tag by default, ADR 0028)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[3] / "deploy" / "install-server.sh"

pytestmark = pytest.mark.skipif(
    not (Path("/run/systemd/system").is_dir() and Path("/etc/os-release").is_file()),
    reason="the machine check reads systemd and /etc/os-release",
)


def _run(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SERVER), *args],  # noqa: S607
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "AGOS_SKIP_DISK_CHECK": "1", **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _meminfo(tmp_path: Path, mb: int) -> str:
    path = tmp_path / f"meminfo-{mb}"
    path.write_text(f"MemTotal:       {mb * 1024} kB\nMemFree:        1000 kB\n")
    return str(path)


def _supported_os() -> bool:
    text = Path("/etc/os-release").read_text()
    return "ID=ubuntu" in text and any(
        f'VERSION_ID="{v}"' in text for v in ("22.04", "24.04", "26.04")
    )


@pytest.mark.skipif(not _supported_os(), reason="the check stops first on an untested OS")
@pytest.mark.parametrize(
    ("mb", "cpus", "rc", "said"),
    [
        (2900, "4", 1, "AGOS needs at least 4 GB of memory and 2 CPUs"),
        (16000, "1", 1, "AGOS needs at least 4 GB of memory and 2 CPUs"),
        (3800, "2", 0, "WARNING: 4 GB of memory: enough for 1-2 workspaces"),
        (16000, "4", 0, "[ok] 16 GB memory, 4 CPUs"),
    ],
)
def test_the_machine_check_refuses_below_the_minimum_and_warns_near_it(
    tmp_path: Path, mb: int, cpus: str, rc: int, said: str
) -> None:
    done = _run(tmp_path, "--check-machine", AGOS_MEMINFO=_meminfo(tmp_path, mb), AGOS_NPROC=cpus)
    assert done.returncode == rc, done.stdout + done.stderr
    assert said in done.stdout + done.stderr
    if rc:
        assert "Nothing was installed" in done.stderr
        assert "This machine can run AGOS" not in done.stdout
    else:
        assert "This machine can run AGOS" in done.stdout


@pytest.mark.skipif(not _supported_os(), reason="the check stops first on an untested OS")
def test_the_minimum_can_be_skipped_on_purpose(tmp_path: Path) -> None:
    done = _run(
        tmp_path,
        "--check-machine",
        AGOS_MEMINFO=_meminfo(tmp_path, 2000),
        AGOS_NPROC="1",
        AGOS_SKIP_HARDWARE_CHECK="1",
    )
    assert done.returncode == 0
    assert "installing anyway (AGOS_SKIP_HARDWARE_CHECK=1)" in done.stdout


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)  # noqa: S603,S607


@pytest.fixture
def published(tmp_path: Path) -> Path:
    """A published repository with releases, a beta and newer work on main."""
    src, bare = tmp_path / "src", tmp_path / "agos.git"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    for n, tag in enumerate(["v0.9.0", "v0.10.0", "v0.11.0-beta.1", None, "v0.2.0"]):
        (src / "f").write_text(str(n))
        _git(src, "add", "f")
        _git(
            src, "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", str(n)
        )
        if tag:
            _git(src, "tag", tag)
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)  # noqa: S603,S607
    return bare


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
@pytest.mark.parametrize(
    ("env", "picked"),
    [
        ({}, "v0.10.0 stable"),  # SemVer order: 0.10 > 0.9 > 0.2
        ({"AGOS_CHANNEL": "beta"}, "v0.11.0-beta.1 beta"),
        ({"AGOS_CHANNEL": "main"}, "main main"),
        ({"AGOS_REF": "v0.9.0"}, "v0.9.0 stable"),  # a release by hand stays on stable
        ({"AGOS_REF": "dev"}, "dev main"),  # a branch by hand follows it
    ],
)
def test_the_installer_takes_the_newest_release_of_its_channel(
    tmp_path: Path, published: Path, env: dict[str, str], picked: str
) -> None:
    done = _run(tmp_path, "--which-release", AGOS_REPO_URL=str(published), **env)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == picked


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_no_release_yet_installs_main_but_keeps_the_stable_channel(tmp_path: Path) -> None:
    bare = tmp_path / "empty.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603,S607
    done = _run(tmp_path, "--which-release", AGOS_REPO_URL=str(bare))
    assert "no stable release is published yet" in done.stdout
    assert done.stdout.strip().splitlines()[-1] == "main stable"
