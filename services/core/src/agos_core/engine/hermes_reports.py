"""Hermes's own reports, read through its CLI in a profile's home: `hermes status
--full`, `hermes doctor` (no --fix) and `hermes logs errors` (HermesEngine.hermes_check).
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

REPORTS: dict[str, list[str]] = {
    "status": ["status", "--full"],
    "doctor": ["doctor"],
    # Its errors.log, ERROR and up (Settings → Errors, actions/hermes_errors.py).
    "errors": ["logs", "errors", "-n", "500", "--level", "ERROR"],
}


def run(
    engine: HermesEngine, workspace_id: str, command: str, *, timeout: float = 180
) -> tuple[str, int]:
    """One report, with the managed scope as every AGOS run has it: (its text, its
    exit code). Doctor's exit code is Hermes's own verdict: 1 when it found issues
    (H: hermes_cli/doctor.py run_doctor `int(bool(issues or manual_issues))`); its
    report is still the answer."""
    from agos_core.engine.hermes import EngineError, child_env

    argv = REPORTS.get(command)
    if argv is None:
        raise EngineError(f"no Hermes report named {command}")
    env = child_env({**engine.hermes_env(workspace_id), "NO_COLOR": "1"})
    off_loop(f"hermes {command}")
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own CLI, fixed argv
            [engine.settings.hermes_bin, *argv],
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=env,
            check=False,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EngineError(f"Hermes didn't answer: {error}") from error
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", done.stdout or "").strip()
    if not text:
        tail = (done.stderr or "").strip().splitlines()[-1:] or ["no answer"]
        raise EngineError(f"Hermes didn't answer: {tail[0][:300]}")
    return text, done.returncode
