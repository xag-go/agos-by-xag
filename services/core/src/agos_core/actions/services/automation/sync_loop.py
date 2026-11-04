"""The automations' background loop: keeps every row and its Hermes job in step
(re-sends a write Hermes refused, with backoff; forgets copies Hermes now holds;
hands a member's jobs over when he leaves), and refreshes the tools list.

Owns: run_forever and its timers' state (_retries, _tools_at). Must not: hold
an owner action.
"""

import asyncio
import logging
import sqlite3
import time
from typing import Any

from agos_core.actions import (
    account_pause,
    automation_cards,
    hooks,
)
from agos_core.actions.services.automation.cron import (
    COFOUNDER,
    TICK_SECONDS,
    Jobs,
    Source,
    automation_view,
    hermes_jobs,
)
from agos_core.actions.services.automation.instructions import read_instructions
from agos_core.actions.services.automation.jobs import (
    gone_notice,
    pinned_skills,
    runner,
    set_notice,
    sync_job,
    team_notice,
    write_scripts,
)
from agos_core.context import Core
from agos_core.db import automations as repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.engine.cron import (
    fire_script_name,
    legacy_job_name,
)

__all__ = [
    "RETRY_FIRST_S",
    "RETRY_MAX_S",
    "TOOLS_LOOK_S",
    "hand_over",
    "keep_in_step",
    "run_forever",
    "sync_agent_jobs",
]

log = logging.getLogger("agos.automations")


def keep_in_step(core: Core) -> None:
    """The Hermes jobs follow who does them: its agent was turned off (the
    Co-Founder's cron takes the job) or back on (the job goes back to the agent's own
    cron); a write Hermes refused before is retried. Nothing else is compared: a
    job's prompt, model and timing are Hermes's own (an edit there is the edit).

    Live moves, safe to run again: a job still in the Co-Founder's cron for a member
    (made before each member ran its own) moves to the member's cron; a one-agent
    job whose instructions AGOS still kept in a file (before Hermes's prompt was
    their one copy) gets them from the file once, and the file goes. Archived
    workspaces are left parked."""
    for workspace_id in workspaces_repo.ids(core.db, trashed=False, archived=False):
        rows = repo.rows(core.db, workspace_id)
        if not rows:
            continue
        jobs = hermes_jobs(core, workspace_id) if any(r["hermes_job_id"] for r in rows) else {}
        routes = hooks.routes(core, workspace_id)
        for row in rows:
            automation, source = automation_view(core, row, jobs, routes)
            _forget_copies(core, row, source, jobs or {})
            if automation_cards.card_runs(automation):
                write_scripts(core, automation)  # Hermes's script follows its plan
            board = bool(automation.steps or automation.check_first)
            if not row["sync_error"]:
                _retries.pop((workspace_id, automation.id), None)  # Hermes took it
            if row["sync_error"] and automation.schedule:
                # Hermes didn't take the owner's last change: try again, with a pause
                # that grows while it keeps refusing (each try is a Hermes cron run).
                asked_for = (automation.schedule, automation.on)
                if _retry_due(workspace_id, automation.id, (str(row["sync_error"]), asked_for)):
                    sync_job(core, workspace_id, automation.id, want=asked_for)
            elif source != "hermes":
                if automation.steps:
                    set_notice(core, automation, team_notice(core, automation))
                elif not board:
                    set_notice(core, automation, gone_notice(core, automation))
            elif board:
                if _strays(row, jobs or {}) or _name_waits(row, jobs or {}):
                    sync_job(core, workspace_id, automation.id)  # its clock in Hermes
                elif automation.steps:
                    set_notice(core, automation, team_notice(core, automation))
            else:
                held = (jobs or {}).get(str(row["hermes_job_id"])) or {}
                owner = str(held.get("owner") or COFOUNDER)
                want = runner(core, automation, owner)
                kept = read_instructions(core, workspace_id, automation.file) is not None
                # The agent's pinned skills changed: the job's own skills follow.
                skills = list(held.get("skills") or []) != pinned_skills(core, workspace_id, want)
                renamed = _name_waits(row, jobs or {})
                if want != owner or _strays(row, jobs or {}) or kept or skills or renamed:
                    sync_job(core, workspace_id, automation.id)
                else:
                    set_notice(core, automation, gone_notice(core, automation))


def _name_waits(row: sqlite3.Row, jobs: Jobs) -> bool:
    """The owner's name is still AGOS's (an old automation, its job named by AGOS's
    id) while Hermes's job holds another: the next sync gives the job his name."""
    job = jobs.get(str(row["hermes_job_id"] or ""))
    return bool(row["name"]) and job is not None and job.get("name") != row["name"]


def _strays(row: sqlite3.Row, jobs: Jobs) -> bool:
    """A job of this automation besides its linked one (a move that stopped
    halfway): the next sync removes it."""
    name, script = legacy_job_name(int(row["id"])), fire_script_name(int(row["id"]))
    return any(
        (j.get("name") == name or j.get("script") == script)
        and str(j["id"]) != str(row["hermes_job_id"])
        for j in jobs.values()
    )


def hand_over(core: Core, workspace_id: str, agent: str) -> None:
    """A member leaves the team (turned off, or deleted with its profile): the
    jobs its own cron holds move to the Co-Founder's cron first, so none is lost
    with its profile, and none runs as an agent that is off."""
    sync_agent_jobs(core, workspace_id, agent)


def sync_agent_jobs(core: Core, workspace_id: str, agent: str) -> None:
    """The jobs the agent's own cron holds follow it again (where they belong, its
    pinned skills): after it changed or leaves the team."""
    jobs = hermes_jobs(core, workspace_id)
    if not jobs:
        return
    held = {str(j["id"]) for j in jobs.values() if j.get("owner") == agent}
    for row in repo.rows(core.db, workspace_id):
        if str(row["hermes_job_id"] or "") in held:
            sync_job(core, workspace_id, int(row["id"]))


def _forget_copies(core: Core, row: sqlite3.Row, source: Source, jobs: Jobs) -> None:
    """Copies AGOS kept before (the schedule; a one-agent job's model) go once
    Hermes's job has them. Nothing is cleared while Hermes can't be read."""
    if source != "hermes":
        return
    job = jobs.get(str(row["hermes_job_id"])) or {}
    model = not (row["steps"] or row["check_first"]) and bool(job.get("model"))
    name = bool(row["name"]) and job.get("name") == row["name"]
    if row["schedule"] or (model and row["model"]) or name:
        repo.forget_request(core.db, int(row["id"]), model=model, name=name)


# The loop's last look at Hermes's list of tools (monotonic), None before the first:
# monotonic counts from boot, so 0.0 would read as "looked" for 10 min after a boot.
_tools_at: float | None = None


# How often the loop may ask Hermes's list when it is due (hermes_tools.due: not
# read yet, old, or a new Hermes): a Hermes that doesn't answer is asked again after
# this, not on every 20 s pass.
TOOLS_LOOK_S = 600.0


def _tools_due(core: Core) -> bool:
    """Whether this pass asks Hermes's list of tools: only when it is due. The start
    sync has just read it (api/app.py), so the loop's first pass doesn't ask again."""
    global _tools_at
    from agos_core.engine import hermes_tools

    if not hermes_tools.due(core):
        return False
    if _tools_at is not None and time.monotonic() - _tools_at < TOOLS_LOOK_S:
        return False
    _tools_at = time.monotonic()
    return True


RETRY_FIRST_S = 60.0  # a write Hermes refused: tried again after this, then twice as long


RETRY_MAX_S = 1800.0


# (workspace, automation) -> (what was asked and refused, next try at, pause)
_retries: dict[tuple[str, int], tuple[Any, float, float]] = {}


def _retry_due(workspace_id: str, automation_id: int, asked: Any) -> bool:
    """Whether a refused write is tried again now: at once the first time, then after
    1 min, 2, 4 ... up to 30 min while Hermes keeps refusing the same thing (it was
    every 20 s: a Hermes cron run each time). A new ask (the owner changed it, or a
    new refusal) starts again at once."""
    key = (workspace_id, automation_id)
    found = _retries.get(key)
    now_s = time.monotonic()
    if found is not None and found[0] == asked and now_s < found[1]:
        return False
    pause = RETRY_FIRST_S if found is None or found[0] != asked else min(found[2] * 2, RETRY_MAX_S)
    _retries[key] = (asked, now_s + pause, pause)
    return True


async def _timed(took: dict[str, float], name: str, fn: Any, core: Core) -> None:
    began = time.monotonic()
    try:
        await asyncio.to_thread(fn, core)
    finally:
        took[name] = time.monotonic() - began


async def run_forever(core: Core) -> None:
    while True:
        started = time.monotonic()
        took: dict[str, float] = {}
        try:
            await _timed(took, "relay", hooks.relay_map, core)  # follows Hermes's routes
            await _timed(took, "keep_in_step", keep_in_step, core)
            await _timed(took, "account_pause", account_pause.keep, core)
            from agos_core.actions import work_hours

            # Check-in / check-out on Hermes's own switches (Settings → Work hours).
            await _timed(took, "work_hours", work_hours.keep, core)
            from agos_core.actions import catch_up

            # A run missed while the server was off: once, or skipped (its choice).
            await _timed(took, "catch_up", catch_up.keep, core)
            from agos_core.actions import watchdogs

            await _timed(took, "watchdogs", watchdogs.sweep, core)  # a watched tree that ended
            # The generated playbooks view follows Hermes's jobs and profiles: a
            # cheap fingerprint each pass, rewritten only when a source changed.
            from agos_core.actions import team_files

            await _timed(took, "team_files", team_files.refresh_all, core)
            if await asyncio.to_thread(_tools_due, core):
                # Hermes's list of tools: what it added appears (and is on) by itself.
                from agos_core.actions.library import refresh_tools

                await _timed(took, "tools", refresh_tools, core)
        except Exception:
            log.exception("automation loop failed")
        if time.monotonic() - started > 10:
            slow = ", ".join(f"{k} {v:.1f}s" for k, v in took.items() if v >= 1)
            log.warning("automation loop: slow pass (%.1fs: %s)", time.monotonic() - started, slow)
        await asyncio.sleep(TICK_SECONDS)
