"""A Hermes command or runtime script is never cut off after a few seconds: each one
starts a fresh Hermes runtime, which takes far longer on a busy machine (checks
timed out at 30 s while the same call took 14 s alone). Every subprocess AGOS runs
for Hermes gets at least HERMES_MIN_WAIT_S (owner rule: no short time limits)."""

import contextlib
import subprocess
from pathlib import Path
from typing import Any

from agos_core.engine import cron as cron_module
from agos_core.engine import hermes as engine_module
from agos_core.engine.waits import HERMES_MIN_WAIT_S


def _capture(monkeypatch: Any) -> list[float]:
    seen: list[float] = []

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(float(kwargs["timeout"]))
        return subprocess.CompletedProcess(args[0], 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_the_runner_never_waits_less_than_the_floor(monkeypatch: Any) -> None:
    seen = _capture(monkeypatch)
    engine_module.SubprocessRunner().run(["/bin/true"], timeout=20)
    assert seen == [HERMES_MIN_WAIT_S]
    engine_module.SubprocessRunner().run(["/bin/true"], timeout=900)
    assert seen[-1] == 900


def test_a_cron_check_never_waits_less_than_the_floor(monkeypatch: Any, tmp_path: Path) -> None:
    seen = _capture(monkeypatch)
    bridge = cron_module.CronBridge.__new__(cron_module.CronBridge)
    bridge.python = "/usr/bin/python3"
    bridge.engine = type(
        "E", (), {"host_home": tmp_path, "runtime_env": staticmethod(lambda: {})}
    )()
    with contextlib.suppress(Exception):  # only the wait matters here
        bridge._call(tmp_path, {"op": "check", "schedule": "0 9 * * *"}, timeout=30)
    assert seen and min(seen) >= HERMES_MIN_WAIT_S
