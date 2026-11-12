"""What the agents keep going for the owner in a workspace: the jobs they scheduled
in the workspace's Hermes (its cron: a reminder to come back, an eye kept on
something), shown here with Stop. Hermes runs them; AGOS only shows and stops
them. AGOS's own automations (Automations) are listed there, not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.records import Ongoing, OngoingJob
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.ongoing")


def _jobs(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The workspace's Hermes cron jobs, as Hermes keeps them (read only)."""
    if core.engine is None:
        return []
    path = core.engine.profile_home(workspace_id) / "cron" / "jobs.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    return [j for j in jobs or [] if isinstance(j, dict) and j.get("id")]


def _ours(core: Core, workspace_id: str) -> set[str]:
    """Jobs AGOS made for its automations (shown in Automations)."""
    return {
        str(r["hermes_job_id"])
        for r in core.db.execute(
            "SELECT hermes_job_id FROM automations WHERE workspace_id = ? "
            "AND hermes_job_id IS NOT NULL",
            (workspace_id,),
        )
    }


def agent_jobs(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    from agos_core.actions import digest, skill_updates

    ours = (
        _ours(core, workspace_id)
        | digest.job_ids(core, workspace_id)
        | skill_updates.job_ids(core, workspace_id)
    )
    return [j for j in _jobs(core, workspace_id) if str(j["id"]) not in ours]


def _system(job: dict[str, Any]) -> str | None:
    """AGOS's own rhythm jobs (actions/rhythm.py, actions/heartbeat.py), found by
    the name AGOS gives them in the root's cron."""
    from agos_core.actions import heartbeat, rhythm, skill_growth

    name = str(job.get("name") or "")
    if name == heartbeat.JOB_NAME:
        return "heartbeat"
    if name == skill_growth.JOB_NAME:
        return "skills"
    return next((key for key, j in rhythm.JOBS.items() if j.name == name), None)


def _view(job: dict[str, Any]) -> OngoingJob:
    schedule = job.get("schedule_display") or job.get("schedule") or ""
    if isinstance(schedule, dict):
        schedule = schedule.get("display") or schedule.get("expr") or json.dumps(schedule)
    return OngoingJob(
        id=str(job["id"]),
        name=str(job.get("name") or "")[:200],
        prompt=str(job.get("prompt") or "")[:2000],
        schedule=str(schedule)[:200],
        next_run_at=str(job.get("next_run_at") or "") or None,
        last_run_at=str(job.get("last_run_at") or "") or None,
        enabled=bool(job.get("enabled", True)),
        state=str(job.get("state") or "")
        or ("scheduled" if job.get("enabled", True) else "paused"),
        paused_reason=str(job.get("paused_reason") or "") or None,
        system=_system(job),
    )


def ongoing(core: Core, workspace_id: str) -> Ongoing:
    require_workspace(core, workspace_id)
    return Ongoing(jobs=[_view(j) for j in agent_jobs(core, workspace_id)])


def remove_job(core: Core, workspace_id: str, job_id: str) -> None:
    """His Stop: the job is removed from the workspace's Hermes."""
    require_workspace(core, workspace_id)
    job = next((j for j in agent_jobs(core, workspace_id) if str(j["id"]) == job_id), None)
    if job is None:
        raise NotFoundError("This scheduled job")
    if _system(job):
        raise ActionError(
            "This is AGOS's own rhythm: turn it off on the Vision page or the agent card.",
            status=409,
        )
    assert core.engine is not None
    try:
        hermes_cli.cli(core.engine, workspace_id, "cron", "remove", job_id)
    except (EngineError, OSError) as error:
        raise ActionError(f"The engine didn't remove it: {error}", status=502) from error
