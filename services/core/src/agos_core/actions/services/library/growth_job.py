"""Skills that grow, the weekly job: its script and its Hermes cron job, switched on or off per workspace.
Must not: decide on a candidate.

Split out of agos_core.actions.skill_growth (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.library.growth_evidence import (
    JOB_DAY,
    JOB_NAME,
    JOB_TIME,
    OFF_REASON,
    PROMPT,
    SCRIPT,
)
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction

__all__ = [
    "ensure_job",
    "job",
    "script_text",
    "set_job",
]

log = logging.getLogger("agos.skill_growth")  # the old module's logger (one name)

# ---- the weekly job (the Co-Founder's own Hermes cron) ------------------------------------------


def script_text() -> str:
    """The monitor script Hermes runs before each tick: it asks AGOS (the workspace's
    own bridge, key from agos-bridge.json in the profile home) for the evidence."""
    return '''"""AGOS skill review: the week's evidence the engine's monitor compares (written by AGOS)."""
import json
import os
import sys
import urllib.request
from pathlib import Path

home = Path(os.environ.get("HERMES_HOME") or ".")
bridge = json.loads((home / "agos-bridge.json").read_text())
core = str(bridge["core"]).rstrip("/")
if not core.startswith(("http://127.0.0.1", "http://localhost")):
    sys.exit("AGOS's core is not on this machine")
request = urllib.request.Request(
    core + "/hermes-bridge/" + str(bridge["workspace"]) + "/skill-review",
    data=json.dumps({"action": "evidence"}).encode(),
    headers={"content-type": "application/json", "authorization": "Bearer " + str(bridge["key"])},
    method="POST",
)
with urllib.request.urlopen(request, timeout=120) as reply:
    answer = json.loads(reply.read() or b"{}")
if not isinstance(answer, dict) or answer.get("error"):
    sys.exit(str(answer.get("error") if isinstance(answer, dict) else "no answer"))
sys.stdout.write(str(answer.get("evidence") or ""))
'''


def _write_script(home: Path) -> None:
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / SCRIPT
    wanted = script_text()
    with contextlib.suppress(OSError):
        if script.read_text() == wanted:
            return
    script.write_text(wanted)
    script.chmod(0o600)


def _jobs(core: Core, workspace_id: str) -> tuple[Path, list[dict[str, Any]]]:
    from agos_core.actions import automations, heartbeat

    home, jobs = heartbeat._home_and_jobs(core, workspace_id, automations.COFOUNDER)
    return Path(home), jobs


def _spec(core: Core, workspace_id: str, time: str, day: int) -> Any:
    from agos_core.actions import automations, rhythm
    from agos_core.actions.engine import _default_model
    from agos_core.engine.cron import FAILURES_TO, JobSpec

    provider, model, effort = _default_model(core, workspace_id) or ("", "", "")
    return JobSpec(
        name=JOB_NAME,
        prompt=PROMPT,
        schedule=rhythm.schedule_of(time, day),
        model=model,
        provider=provider,
        reasoning_effort=effort if effort and effort not in ("standard", "default") else None,
        enabled=True,
        failure_deliver=FAILURES_TO,
        skills=tuple(automations.pinned_skills(core, workspace_id, "")),
        monitor_script=SCRIPT,
    )


def job(core: Core, workspace_id: str) -> dict[str, Any]:
    """The job as the settings show it (the root's cron, read only)."""
    from agos_core.actions import rhythm
    from agos_core.engine.cron import CronError

    shown: dict[str, Any] = {"name": JOB_NAME, "on": False, "time": JOB_TIME, "day": JOB_DAY}
    if core.engine is None:
        return shown
    try:
        _home, jobs = _jobs(core, workspace_id)
    except (CronError, OSError, ValueError, ActionError) as error:
        return {**shown, "problem": str(error)[:300]}
    found = next((j for j in jobs if j.get("name") == JOB_NAME), None)
    if found is None:
        return shown
    when = rhythm._when(str(found.get("schedule") or "")) or (JOB_TIME, JOB_DAY)
    enabled = bool(found.get("enabled"))
    reason = found.get("paused_reason")
    return {
        "name": JOB_NAME,
        "on": enabled,
        "time": when[0],
        "day": when[1] if when[1] is not None else JOB_DAY,
        "nextAt": found.get("next_run_at") if enabled else None,
        "lastAt": found.get("last_run_at"),
        "lastStatus": found.get("last_status"),
        "changedAt": found.get("monitor_changed_at"),
        "problem": f"Paused by the engine: {reason}"[:300]
        if not enabled and reason and reason != OFF_REASON
        else None,
    }


def set_job(core: Core, workspace_id: str, *, on: bool, time: str, day: int) -> dict[str, Any]:
    """On makes (or re-times and resumes) the job in the Co-Founder's cron with its
    monitor script; off pauses it (its time stays)."""
    from agos_core.actions import automations, rhythm
    from agos_core.actions.workspaces import require_workspace
    from agos_core.engine.cron import CronError
    from agos_core.engine.hermes import EngineError

    require_workspace(core, workspace_id)
    if not rhythm._TIME.match(time):
        raise ActionError("A time is HH:MM, 00:00 to 23:59.")
    if not 0 <= day <= 6:
        raise ActionError("The skill review's day: 0 (Sunday) to 6 (Saturday).")
    bridge = automations.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so the Co-Founder's jobs can't change now.", 409)
    home, jobs = _jobs(core, workspace_id)
    found = next((j for j in jobs if j.get("name") == JOB_NAME), None)
    try:
        _write_script(home)
        spec = _spec(core, workspace_id, time, day)
        if found is None:
            job_id = str(bridge.create(home, spec)["id"])
        else:
            job_id = str(found["id"])
            bridge.update(home, job_id, spec)
        if not on:
            bridge.pause(home, job_id, OFF_REASON)
        elif found is not None and not found.get("enabled"):
            bridge.resume(home, job_id)
    except (CronError, EngineError, OSError, ValueError) as error:
        raise ActionError(f"The skill review job didn't change: {error}"[:300], 503) from error
    with transaction(core.db):
        add_activity(
            core.db,
            workspace_id,
            kind="skills.review.on" if on else "skills.review.off",
            text=f"{JOB_NAME}: " + (f"day {day}, {time}" if on else "off"),
        )
    return job(core, workspace_id)


_jobs_done: set[str] = set()
_jobs_lock = threading.Lock()


def ensure_job(core: Core, workspace_id: str) -> bool:
    """The job is made once, on, at its default time, when the root's cron lacks it
    (once per start; never raises). True when it was made now."""
    from agos_core.actions import automations

    key = f"{core.layout.root}\0{workspace_id}"
    if core.engine is None or automations.cron_bridge(core) is None or key in _jobs_done:
        return False
    with _jobs_lock:
        if key in _jobs_done:
            return False
        try:
            home, jobs = _jobs(core, workspace_id)
            _jobs_done.add(key)
            if any(j.get("name") == JOB_NAME for j in jobs):
                _write_script(home)  # the shipped script text, again
                return False
            set_job(core, workspace_id, on=True, time=JOB_TIME, day=JOB_DAY)
            return True
        except Exception as error:  # noqa: BLE001 — a start never fails on it
            log.warning("skill review job of %s not set up: %s", workspace_id, error)
            return False
