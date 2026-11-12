"""The nightly's self-hosted runner (deploy/register-ci-runner.sh) and its workflow.

- `--dry-run` says every step and runs none (no sudo, no download, no GitHub call);
- the runner never runs as the live AGOS's account, root or the caller's own account;
- its systemd user unit is a low-priority guest (nice, idle IO, memory caps, OOM first)
  and cleans before and after; the clean-up hook ends the rigs' processes and removes
  only the rigs and the job's temp files;
- the nightly workflow runs on schedule / workflow_dispatch only (never pull_request),
  one job at a time, and no other workflow reaches a self-hosted runner.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy" / "register-ci-runner.sh"
WORKFLOWS = REPO / ".github" / "workflows"
BASH = shutil.which("bash") or "/bin/bash"


def _shims(tmp: Path) -> tuple[Path, Path]:
    """PATH shims for every command that changes the machine: each records its call."""
    bin_dir, calls = tmp / "bin", tmp / "calls.log"
    bin_dir.mkdir()
    for name in ("sudo", "useradd", "userdel", "loginctl", "curl", "systemctl", "gh", "tar"):
        shim = bin_dir / name
        shim.write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\nexit 1\n')
        shim.chmod(0o755)
    return bin_dir, calls


def _as_the_runner(tmp: Path) -> None:
    """Make the script see the nightly's own caller: the runner account `server-ci`
    (the default --account), which runs this suite on the self-hosted runner."""
    bin_dir = tmp / "bin"
    if not bin_dir.exists():
        _shims(tmp)
    shim = bin_dir / "id"
    shim.write_text(
        '#!/bin/sh\n[ "$1" = "-un" ] && { echo server-ci; exit 0; }\nexec /usr/bin/id "$@"\n'
    )
    shim.chmod(0o755)


def _run(args: list[str], tmp: Path, **env: str) -> subprocess.CompletedProcess[str]:
    bin_dir, _ = _shims(tmp) if not (tmp / "bin").exists() else (tmp / "bin", None)
    return subprocess.run(  # noqa: S603 - our own script
        [BASH, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp), **env},
    )


def test_a_dry_run_says_every_step_and_runs_none(tmp_path: Path) -> None:
    _, calls = _shims(tmp_path)
    done = _run(["--dry-run", "--repo", "owner/agos", "--account", "server-ci-test"], tmp_path)
    assert done.returncode == 0, done.stderr
    assert not calls.exists(), calls.read_text()  # nothing that changes the machine ran
    out = done.stdout
    for step in (
        "sudo useradd --create-home",
        "sudo loginctl enable-linger server-ci-test",
        "deploy/hermes.pin",
        "sha256sum -c",
        "--labels hermes",
        "https://github.com/owner/agos",
        "ACTIONS_RUNNER_INPUT_TOKEN, never on argv",
        "systemctl --user daemon-reload && systemctl --user enable --now server-ci-runner.service",
    ):
        assert step in out, step


def test_the_registration_token_never_shows(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("AAAA-SECRET-REGISTRATION-TOKEN\n")
    token.chmod(0o600)
    done = _run(
        [
            "--dry-run",
            "--repo",
            "owner/agos",
            "--account",
            "server-ci-test",
            "--token-file",
            str(token),
        ],
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "SECRET" not in done.stdout + done.stderr


@pytest.mark.parametrize("account", ["agos", "root"])
def test_never_the_live_account_or_root(tmp_path: Path, account: str) -> None:
    done = _run(["--dry-run", "--repo", "o/r", "--account", account], tmp_path)
    assert done.returncode == 1
    assert "may not run as" in done.stderr


def test_never_the_callers_own_account(tmp_path: Path) -> None:
    me = subprocess.run(["id", "-un"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S607
    done = _run(["--dry-run", "--repo", "o/r", "--account", me], tmp_path)
    assert done.returncode == 1
    assert "its own account" in done.stderr


def test_the_unit_is_a_low_priority_guest_that_cleans_up(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    done = _run(["--render", str(out), "--account", "server-ci-test"], tmp_path)
    assert done.returncode == 0, done.stderr
    unit = (out / "server-ci-runner.service").read_text()
    for line in (
        "ExecStart=/home/server-ci-test/actions-runner/run.sh",
        "ExecStartPre=/usr/bin/bash /home/server-ci-test/actions-runner/hooks/clean.sh",
        "ExecStopPost=/usr/bin/bash /home/server-ci-test/actions-runner/hooks/clean.sh",
        "Nice=19",
        "IOSchedulingClass=idle",
        "OOMScoreAdjust=800",
        "MemoryMax=9G",
        "NoNewPrivileges=yes",
        "Environment=TMPDIR=/home/server-ci-test/.hermes/cache/scratch/agos-nightly-tmp",
        "WantedBy=default.target",
    ):
        assert line in unit.splitlines(), line
    env = (out / ".env").read_text().splitlines()
    assert (
        "ACTIONS_RUNNER_HOOK_JOB_STARTED=/home/server-ci-test/actions-runner/hooks/clean.sh" in env
    )
    assert (
        "ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/home/server-ci-test/actions-runner/hooks/clean.sh"
        in env
    )


@pytest.mark.parametrize("caller", ["owner", "runner"])
def test_the_clean_hook_ends_the_rigs_and_removes_only_them(tmp_path: Path, caller: str) -> None:
    if caller == "runner":
        _as_the_runner(tmp_path)
    out = tmp_path / "rendered"
    # A test account: the default (server-ci) is the caller itself on the runner.
    assert _run(["--render", str(out), "--account", "server-ci-test"], tmp_path).returncode == 0
    home = tmp_path / "ci-home"
    rig = home / "agos-nightly-e2e"
    (rig / "roots" / "agos-x").mkdir(parents=True)
    evals = home / ".hermes" / "cache" / "scratch" / "agos-nightly-evals"
    (evals / "logs").mkdir(parents=True)
    tmp = home / ".hermes" / "cache" / "scratch" / "agos-nightly-tmp"
    (tmp / "pytest-of-ci").mkdir(parents=True)
    (tmp / "loose.txt").write_text("x")
    kept = home / "agos-src-copy"
    kept.mkdir()
    (home / ".hermes" / "config.yaml").write_text("model: {}\n")
    # A gateway of the rig, still running after a killed job.
    gateway = subprocess.Popen(
        ["/bin/sleep", "300"],
        env={"HERMES_HOME": str(rig / "roots" / "agos-x"), "PATH": "/usr/bin:/bin"},
        start_new_session=True,
    )
    try:
        done = subprocess.run(  # noqa: S603
            [BASH, str(out / "hooks" / "clean.sh")],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home), "CLEAN_GRACE_S": "0.2"},
        )
        assert done.returncode == 0, done.stderr
        deadline = time.monotonic() + 10
        while gateway.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert gateway.poll() is not None, "the rig's gateway still runs"
    finally:
        if gateway.poll() is None:
            gateway.kill()
        gateway.wait()
    assert not rig.exists() and not evals.exists()
    assert tmp.is_dir() and list(tmp.iterdir()) == []
    assert kept.is_dir() and (home / ".hermes" / "config.yaml").is_file()


@pytest.mark.parametrize("caller", ["owner", "runner"])
def test_the_clean_hook_refuses_an_odd_home(tmp_path: Path, caller: str) -> None:
    if caller == "runner":
        _as_the_runner(tmp_path)
    out = tmp_path / "rendered"
    # A test account: the default (server-ci) is the caller itself on the runner.
    assert _run(["--render", str(out), "--account", "server-ci-test"], tmp_path).returncode == 0
    done = subprocess.run(  # noqa: S603
        [BASH, str(out / "hooks" / "clean.sh")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": "/", "CI_RUNNER_HOME": "/"},
    )
    assert done.returncode == 1 and "odd home" in done.stderr


def _workflow(name: str) -> dict[Any, Any]:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text())
    assert isinstance(loaded, dict)
    return loaded


def _triggers(flow: dict[Any, Any]) -> dict[str, Any]:
    on = flow.get("on", flow.get(True))  # YAML 1.1 reads a bare `on` as true
    return dict(on) if isinstance(on, dict) else {str(on): None}


def test_the_nightly_never_runs_on_a_pull_request() -> None:
    flow = _workflow("nightly-hermes.yml")
    assert set(_triggers(flow)) == {"schedule", "workflow_dispatch"}
    assert flow["concurrency"]["cancel-in-progress"] is False
    for job in flow["jobs"].values():
        assert job["runs-on"] == ["self-hosted", "linux", "hermes"]
        assert "HERMES_RUNNER" in str(job.get("if", ""))


def test_no_other_workflow_reaches_a_self_hosted_runner() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "nightly-hermes.yml":
            continue
        for name, job in _workflow(path.name)["jobs"].items():
            assert "self-hosted" not in str(job.get("runs-on")), f"{path.name}: {name}"


def _tools_step(job: dict[str, Any]) -> str:
    return str(next(st["run"] for st in job["steps"] if st.get("name") == "Temp dirs and tools"))


def test_each_nightly_job_finds_the_runner_accounts_tools_or_stops() -> None:
    # The first nightly died at `uv sync` with "uv: command not found": uv and Hermes
    # live in the runner account's ~/.local/bin, which the runner service's PATH lacks,
    # and the old check (`command -v uv && ...` followed by `free -m`) passed anyway.
    for name, job in _workflow("nightly-hermes.yml")["jobs"].items():
        run = _tools_step(job)
        assert '"$HOME/.local/bin" >> "$GITHUB_PATH"' in run, name
        assert "exit 1" in run, name
        assert "command -v uv &&" not in run, name
        done = subprocess.run(  # noqa: S603
            ["/bin/bash", "-e", "-c", run],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/nonexistent",
                "HOME": "/nonexistent",
                "GITHUB_ENV": os.devnull,
                "GITHUB_PATH": os.devnull,
            },
        )
        assert done.returncode != 0, f"{name}: a missing tool must fail the step"
        assert "not found" in done.stdout + done.stderr, name


def test_the_nightly_checks_out_the_git_history_its_migration_rehearsal_reads() -> None:
    # The second nightly's "Migrations on old databases" said "0/0 rehearsals passed"
    # and failed: actions/checkout fetches one commit by default, and the rehearsal
    # rebuilds old versions from db/migrations.py's git history.
    job = _workflow("nightly-hermes.yml")["jobs"]["hermes"]
    assert any("migration_rehearsal.py --git" in str(st.get("run", "")) for st in job["steps"])
    checkout = next(
        st for st in job["steps"] if str(st.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout.get("with", {}).get("fetch-depth") == 0


def test_every_dispatch_stage_a_job_checks_is_offered() -> None:
    flow = _workflow("nightly-hermes.yml")
    offered = set(_triggers(flow)["workflow_dispatch"]["inputs"]["stage"]["options"])
    text = (WORKFLOWS / "nightly-hermes.yml").read_text()
    asked = set(re.findall(r"(?:inputs\.stage|env\.STAGE) == '([a-z-]+)'", text))
    assert asked <= offered, asked - offered


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck here")
def test_shellcheck_is_clean() -> None:
    done = subprocess.run(  # noqa: S603
        [str(shutil.which("shellcheck")), "-S", "style", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ},
    )
    assert done.returncode == 0, done.stdout
