"""Reading automations from the workspace's Hermes cron: each profile's cron home,
its jobs, and the Automation view of a row merged with its Hermes job (`_view`:
where each value comes from, see the package docstring).

Owns: the read side (list_all, get, schedule checks). Must not: write a job
(jobs.py) or a row (owner.py).
"""

import logging
import sqlite3
from pathlib import Path
from typing import Any, Literal

from agos_core.actions import (
    account_pause,
    agent_profiles,
    automation_cards,
    hooks,
)
from agos_core.actions.services.automation.instructions import read_instructions
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import automations as repo
from agos_core.db.records import (
    Automation,
    LastRun,
)
from agos_core.engine.cron import (
    AGOS_REASONS,
    HELD_REASONS,
    WORK_HOURS_REASON,
    CronBridge,
    CronError,
    instructions_of,
    read_jobs,
    report_text,
)
from agos_core.engine.models import (
    hermes_python,
    hermes_runtime_argv,
    selection_from_hermes,
)

__all__ = [
    "COFOUNDER",
    "MISSING",
    "TICK_SECONDS",
    "Jobs",
    "Routes",
    "Source",
    "describe_schedule",
    "get",
    "hermes_jobs",
    "homes",
    "list_all",
    "schedule_problem",
]

log = logging.getLogger("agos.automations")


TICK_SECONDS = 20


MISSING = (
    "Its job is missing from the scheduler, so it doesn't run on its schedule. "
    "Open it and save it again to schedule it."
)


def cron_bridge(core: Core) -> CronBridge | None:
    engine = core.engine
    if engine is None:
        return None
    custom = getattr(engine, "cron_bridge", None)
    if custom is not None:
        return custom  # type: ignore[no-any-return]
    try:
        return CronBridge(
            engine.settings,
            hermes_python(engine.settings),
            wall=engine.walled_for_home,
            script_python=hermes_runtime_argv(engine.settings),
        )
    except OSError as error:  # Hermes not installed where the settings say
        log.error("Hermes cron is unavailable: %s", error)
        return None


Jobs = dict[str, dict[str, Any]]


# The Co-Founder's own profile: the workspace's root (Hermes's "default").
COFOUNDER = ""


def homes(core: Core, workspace_id: str) -> dict[str, Path]:
    """The workspace's profiles whose Hermes cron can hold an automation's job:
    the Co-Founder's (the root, "") and each member's own (by the member's name)."""
    assert core.engine is not None
    found = {COFOUNDER: core.engine.profile_home(workspace_id)}
    for ws, agent in agent_profiles.existing(core, workspace_id):
        found[agent] = core.engine.profile_home(agent_profiles.key(ws, agent))
    return found


def hermes_jobs(core: Core, workspace_id: str) -> Jobs | None:
    """The workspace's Hermes cron jobs by id, from every profile of it, read live
    (read-only); each says whose cron holds it ("owner": "" the Co-Founder, else the
    member). None when they can't be read now (no engine, root not set up, an
    unreadable file)."""
    if core.engine is None:
        return None
    if not (core.engine.profile_home(workspace_id) / "config.yaml").is_file():
        return None
    try:
        return read_all(core, workspace_id)
    except (CronError, OSError, ValueError) as error:
        log.warning("cron jobs of %s can't be read: %s", workspace_id, error)
        return None


def read_all(core: Core, workspace_id: str) -> Jobs:
    """hermes_jobs, raising what stopped the read."""
    custom = getattr(core.engine, "cron_bridge", None)
    jobs: Jobs = {}
    for owner, home in homes(core, workspace_id).items():
        if owner and not (home / "config.yaml").is_file():
            continue  # a member's profile still being made: no cron yet
        found = custom.job_states(home) if custom is not None else read_jobs(home)
        jobs |= {str(j["id"]): {**j, "owner": owner} for j in found}
    return jobs


def home_of(core: Core, workspace_id: str, job: dict[str, Any]) -> Path:
    """The profile home whose cron holds the job."""
    assert core.engine is not None
    owner = str(job.get("owner") or COFOUNDER)
    if owner == COFOUNDER:
        return core.engine.profile_home(workspace_id)
    return core.engine.profile_home(agent_profiles.key(workspace_id, owner))


Source = Literal["hermes", "agos", "missing", "unknown"]


Routes = dict[int, hooks.Route]


def automation_view(
    core: Core, row: sqlite3.Row, jobs: Jobs | None, routes: Routes
) -> tuple[Automation, Source]:
    """The automation as the owner sees it, and where its timing came from."""
    workspace_id = str(row["workspace_id"])
    route = routes.get(int(row["id"]))
    base = repo.from_row(
        row, hooks.hook_from(core, workspace_id, int(row["id"]), route) if route else None
    )
    link = row["hermes_job_id"]
    card_runs = bool(base.steps or base.check_first)
    job = jobs.get(str(link)) if (jobs is not None and link) else None
    # The file while there is one (a Kanban automation's, or the owner's request
    # Hermes doesn't hold yet), else the prompt of Hermes's one-agent job.
    pending = read_instructions(core, workspace_id, base.file)
    held = job.get("prompt") if job is not None and not card_runs else None
    update: dict[str, Any] = {
        "instructions": pending if pending is not None else instructions_of(str(held or "")),
        # The owner's name: Hermes's job's own name; AGOS's row only while no job
        # holds it (started by an event only, or a change Hermes refused).
        "name": row["name"]
        or (str(job.get("name") or "") if job is not None else "")
        or (route.title if route is not None else "")
        or f"Automation {row['id']}",
    }
    source: Source
    if row["sync_error"]:
        source = "agos"  # the owner's request Hermes refused (shown with the problem)
    elif not link:
        source = "agos"  # a webhook only: its on/off is its Hermes route's
        update.update(schedule="", on=route.on if route else False)
    elif jobs is None:
        source = "unknown"
    elif job is None:
        source = "missing"  # it doesn't run on a schedule; its webhook still may
        update.update(problem=MISSING, schedule="", on=route.on if route else False)
    else:
        source = "hermes"
        if job.get("owner"):
            update["agent"] = str(job["owner"])  # its own cron holds the job: it does it
        reason = job.get("paused_reason")
        if not card_runs and not row["model"]:
            # A one-agent job runs on the model Hermes's job holds (a model in the
            # row is the owner's new pick, on its way to the job).
            held = selection_from_hermes(
                str(job.get("provider") or ""),
                str(job.get("model") or ""),
                job.get("reasoning_effort"),
            )
            if held is not None:
                update["model"] = held
        update["schedule"] = job["schedule"]
        update["schedule_display"] = job.get("schedule_display")
        update["state"] = job.get("state")
        # An archived workspace's job is paused, not turned off: it comes back on
        # restore. A job the OLD pause held (PAUSE_REASON) is also "on", not off,
        # until move_old_pause resumes it at the next start.
        # Off-hours hold it too (actions/work_hours.py): it runs again at check-in.
        update["on"] = bool(job["enabled"]) or reason in HELD_REASONS
        if not job["enabled"] and reason == WORK_HOURS_REASON:
            update["problem"] = "Paused off-hours (work hours): runs again at check-in."
        if account_pause.paused_by_agos(core, workspace_id):
            # Hermes's own pause holds the root: its cron, its Kanban, new turns.
            update["problem"] = "Waits: an account is at your pause level (Settings → Usage)."
        update["next_run_at"] = job.get("next_run_at")
        if not job["enabled"] and reason and reason not in AGOS_REASONS:
            update["problem"] = f"Paused by the engine: {reason}"[:300]
        if not card_runs and job.get("last_run_at"):
            ok = job.get("last_status") == "ok"
            update["last_run"] = LastRun(
                at=str(job["last_run_at"]),
                result="ok" if ok else "failed",
                summary=repo.summary(
                    report_text(str(job.get("last_output") or "")),
                    None if ok else (job.get("last_error") or "The run failed."),
                ),
            )
    if "last_run" not in update:
        live = automation_cards.last_finished(core, base) if card_runs or base.hook else None
        update["last_run"] = live
    return base.model_copy(update=update), source


def list_all(core: Core, workspace_id: str, kind: str | None = None) -> list[Automation]:
    """The workspace's automations with their timing and webhooks read live from
    Hermes. kind: "event" (has a webhook), "schedule" (has none), None for both."""
    rows = repo.rows(core.db, workspace_id)
    jobs = hermes_jobs(core, workspace_id) if any(r["hermes_job_id"] for r in rows) else {}
    routes = hooks.routes(core, workspace_id)
    if kind is not None:
        rows = [r for r in rows if (int(r["id"]) in routes) == (kind == "event")]
    return _with_catch_up(
        core, workspace_id, [automation_view(core, r, jobs, routes)[0] for r in rows]
    )


def _with_catch_up(core: Core, workspace_id: str, items: list[Automation]) -> list[Automation]:
    """Its latest catch-up run (the last day): the card's "Caught up" chip."""
    from agos_core.actions import catch_up

    asked = catch_up.asked(core, workspace_id)
    if not asked:
        return items
    links = {int(r["id"]): str(r["hermes_job_id"] or "") for r in repo.rows(core.db, workspace_id)}
    return [
        a.model_copy(update={"caught_up": catch_up.recent(asked.get(links.get(a.id, "")))})
        for a in items
    ]


def get(core: Core, workspace_id: str, automation_id: int) -> Automation | None:
    found = get_with_source(core, workspace_id, automation_id)
    return _with_catch_up(core, workspace_id, [found[0]])[0] if found else None


def get_with_source(
    core: Core, workspace_id: str, automation_id: int
) -> tuple[Automation, Source] | None:
    found = repo.row(core.db, workspace_id, automation_id)
    if found is None:
        return None
    jobs = hermes_jobs(core, workspace_id) if found["hermes_job_id"] else {}
    return automation_view(core, found, jobs, hooks.routes(core, workspace_id))


def schedule_problem(core: Core, workspace_id: str, schedule: str) -> str | None:
    """Why Hermes's own parser refuses the schedule (engine/cron.py
    check_schedule), or None. No engine or Hermes not reachable: its job write
    says it later (shown on the automation, never silent)."""
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        return None
    try:
        return bridge.check_schedule(core.engine.profile_home(workspace_id), schedule)
    except (CronError, OSError) as error:
        log.warning("schedule not checked by Hermes: %s", error)
        return None


def describe_schedule(
    core: Core, workspace_id: str, schedule: str
) -> tuple[str | None, str | None]:
    """Hermes's own words for a schedule as the form has it now (what it will save
    as the job's schedule_display), and why it refuses it. (None, None): Hermes
    couldn't be asked; the save checks it again."""
    require_workspace(core, workspace_id)
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None or not schedule.strip():
        return None, None
    try:
        return bridge.describe_schedule(core.engine.profile_home(workspace_id), schedule)
    except (CronError, OSError, AttributeError) as error:
        log.info("schedule not described by Hermes: %s", error)
        return None, None
