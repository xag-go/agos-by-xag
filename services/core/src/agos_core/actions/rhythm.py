"""The Co-Founder's daily rhythm on the Vision page (Step 53): three Hermes cron
jobs in the workspace's root profile (the Co-Founder's own cron), made, re-timed
and paused the way the heartbeat's job is (actions/heartbeat.py):

- 'AGOS daily plan' (08:00): proposes today's plan (the owner's items and each
  member's) to the owner: Inbox + Telegram, Accept / Change / Skip;
- 'AGOS recap' (20:00): done / left / moves to tomorrow (informational);
- 'AGOS weekly review' (Fridays 17:00): reviews the goals and their key
  results, proposes new numbers when it has a source (asks the owner otherwise)
  and the changes the week calls for.

AGOS keeps no row: each job is found again by its name in the root's cron, its
time is the job's schedule, on / off is the job enabled / paused (paused with
AGOS's reason, so the time stays). The jobs are made with the first Vision; the
owner re-times or turns each off in the Vision page's settings. Each run's prompt
ends cheap when nothing changed (one short turn).

The times are on the owner's clock: Hermes's cron reads a schedule in its
`timezone` (Settings → General), else in this server's local time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.engine.cron import FAILURES_TO, WORK_HOURS_REASON, CronError, JobSpec
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.rhythm")

OFF_REASON = "Turned off on the Vision page"


@dataclass(frozen=True)
class Job:
    name: str
    time: str  # HH:MM on the owner's clock (Hermes's timezone)
    day: int | None  # 0 = Sunday … 6 = Saturday (a cron day of week), None = every day


JOBS: dict[str, Job] = {
    "daily": Job("AGOS daily plan", "08:00", None),
    "recap": Job("AGOS recap", "20:00", None),
    "weekly": Job("AGOS weekly review", "17:00", 5),
}
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_SCHEDULE = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* (\*|[0-6])$")

PROMPTS: dict[str, str] = {
    "daily": "\n".join(
        [
            "This is your daily plan run: propose today's plan to the owner, once a day.",
            "",
            "1. Call agos_goals with action status: the Vision, each goal's key results,"
            " each project's cards, today's plan (already waiting or accepted?) and the"
            " last recap.",
            "2. Today's plan already waiting for the owner or accepted: answer"
            " `Nothing to do.` and stop.",
            "3. Read the board: `hermes kanban list` (ready, running, review) and"
            " `hermes kanban list --status blocked` (blocked or stalled cards, and what each"
            " waits on).",
            "4. Pick today's few moves that push the key results most. Each member: 1-3"
            " cards for a project it owns (or the one its role fits); none for a member"
            " with enough open work already. The owner: only what needs HIM (a decision,"
            " a login, a call, a review, what only he can make), at most 5 items. Carry"
            " over what the last recap moved to tomorrow, and unblock what waits on him.",
            "5. Propose it with agos_goals: action propose, kind daily_plan, payload"
            ' {"date": "<today, YYYY-MM-DD>", "summary": "<one line>", "you":'
            ' [{"title": "...", "why": "..."}], "members": [{"member": "<name>", "title":'
            ' "...", "body": "<what done looks like>", "project_id": <id>}]}. The owner'
            " accepts it (AGOS creates today's cards), changes it with a note (propose"
            ' again with "revises": "<that card>") or skips it.',
            "",
            "Never create today's cards yourself and never write to the owner otherwise."
            " When nothing changed since yesterday and nobody has work to give, answer"
            " `Nothing to do.` and stop: this run must stay cheap.",
        ]
    ),
    "recap": "\n".join(
        [
            "This is your evening recap run: tell the owner how today went, once a day.",
            "",
            "1. Call agos_goals with action status (today's plan and the key results).",
            "2. No plan today and no card moved: answer `Nothing to do.` and stop.",
            "3. Read today's cards on the board (`hermes kanban list`): what is done, what"
            " is left, what is blocked and on what.",
            "4. Post the recap with agos_goals: action post, kind recap, words in three"
            " short parts: Done, Left, Moves to tomorrow (what tomorrow's plan should"
            " carry), and one line on a key result whose number moved.",
            "",
            "Do not create, move or close cards in this run and never write to the owner"
            " otherwise. Keep it short: this run must stay cheap.",
        ]
    ),
    "weekly": "\n".join(
        [
            "This is your weekly review run: review the goals and their key results.",
            "",
            "1. Call agos_goals with action status: each goal, its key results (current /"
            " target) and its projects' cards.",
            "2. Each key result: when you have a source for its current number (a report,"
            " a connector, a card's result), propose it with agos_goals (action propose,"
            ' kind kr_update, payload {"kr_id", "current", "source"}). When you have none,'
            " ask the owner with agos_ask_owner, once for all the numbers you lack.",
            "3. A goal off track, a project done or stalled, a missing project or key"
            " result: propose the change with agos_goals (kind goal, kr or project) with"
            " its why. The Vision and the strategy are the owner's: suggest a change"
            " (kind vision) only when the week showed they no longer fit.",
            "4. Read the team scorecards at the end of agos_goals status (cards done,"
            " median time, blocks and their wait, returns from review, the owner's"
            " 👍 / 👎, last heartbeat). For a member that struggles, propose the fix it"
            " needs, with its why: a skill (agos_skill_request), a model or access"
            " change, or a hire (agos_propose kind hire). A member with no card done this"
            " week: say why (no work given, blocked, or failing) and fix that cause.",
            "5. Post the review with agos_goals: action post, kind weekly, words: each"
            " goal on track or not and why; Team: one line per member (what it delivered,"
            " what blocked it, or that it did nothing); what you proposed; what you need"
            " from the owner.",
            "",
            "When nothing moved this week and nothing needs changing, post one line and"
            " stop: this run must stay cheap.",
        ]
    ),
}


def schedule_of(time: str, day: int | None) -> str:
    """The cron expression Hermes's parser takes (cron/jobs.py parse_schedule)."""
    hours, minutes = time.split(":")
    return f"{int(minutes)} {int(hours)} * * {'*' if day is None else day}"


def _when(schedule: str) -> tuple[str, int | None] | None:
    found = _SCHEDULE.match(schedule.strip())
    if found is None or int(found[1]) > 59 or int(found[2]) > 23:
        return None
    day = None if found[3] == "*" else int(found[3])
    return f"{int(found[2]):02d}:{int(found[1]):02d}", day


def _jobs(core: Core, workspace_id: str) -> tuple[Any, list[dict[str, Any]]]:
    from agos_core.actions import heartbeat

    return heartbeat._home_and_jobs(core, workspace_id, automation_actions.COFOUNDER)


def _shown(which: str, job: dict[str, Any] | None) -> dict[str, Any]:
    plan = JOBS[which]
    if job is None:
        return {"which": which, "name": plan.name, "on": False, "time": plan.time, "day": plan.day}
    when = _when(str(job.get("schedule") or "")) or (plan.time, plan.day)
    reason = job.get("paused_reason")
    enabled = bool(job.get("enabled"))
    off_hours = not enabled and reason == WORK_HOURS_REASON  # held until check-in
    return {
        "which": which,
        "name": plan.name,
        "on": enabled or off_hours,
        "time": when[0],
        "day": when[1],
        "nextAt": job.get("next_run_at") if enabled else None,
        "lastAt": job.get("last_run_at"),
        "lastStatus": job.get("last_status"),
        "problem": (
            "Paused off-hours (work hours): runs at check-in."
            if off_hours
            else f"Paused by Hermes: {reason}"[:300]
            if not enabled and reason != OFF_REASON
            else None
        ),
    }


def list_all(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The three jobs as the Vision page's settings show them (the root's cron, read
    only: no Hermes process). Never raises: a problem is shown on each."""
    if core.engine is None:
        return [_shown(w, None) for w in JOBS]
    try:
        _home, jobs = _jobs(core, workspace_id)
    except (CronError, OSError, ValueError, ActionError) as error:
        return [{**_shown(w, None), "problem": str(error)[:300]} for w in JOBS]
    by_name = {str(j.get("name")): j for j in jobs}
    return [_shown(w, by_name.get(p.name)) for w, p in JOBS.items()]


def _spec(core: Core, workspace_id: str, which: str, time: str, day: int | None) -> JobSpec:
    from agos_core.actions.engine import _default_model

    provider, model, effort = _default_model(core, workspace_id) or ("", "", "")
    return JobSpec(
        name=JOBS[which].name,
        prompt=PROMPTS[which],
        schedule=schedule_of(time, day),
        model=model,
        provider=provider,
        reasoning_effort=effort if effort and effort not in ("standard", "default") else None,
        enabled=True,
        failure_deliver=FAILURES_TO,
        skills=tuple(automation_actions.pinned_skills(core, workspace_id, "")),
    )


def set_job(
    core: Core, workspace_id: str, which: str, *, on: bool, time: str, day: int | None = None
) -> list[dict[str, Any]]:
    """One job's toggle and time: on makes (or re-times and resumes) it in the
    Co-Founder's cron, off pauses it (its time stays)."""
    require_workspace(core, workspace_id)
    if which not in JOBS:
        raise ActionError("The jobs are daily, recap and weekly.", 404)
    if not _TIME.match(time):
        raise ActionError("A time is HH:MM, 00:00 to 23:59.")
    if which == "weekly":
        if day is None or not 0 <= day <= 6:
            raise ActionError("The weekly review's day: 0 (Sunday) to 6 (Saturday).")
    else:
        day = None
    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so the Co-Founder's jobs can't change now.", 409)
    home, jobs = _jobs(core, workspace_id)
    job = next((j for j in jobs if j.get("name") == JOBS[which].name), None)
    try:
        if job is None:
            made = bridge.create(home, _spec(core, workspace_id, which, time, day))
            job_id = str(made["id"])
        else:
            job_id = str(job["id"])
            bridge.update(home, job_id, _spec(core, workspace_id, which, time, day))
        if not on:
            bridge.pause(home, job_id, OFF_REASON)
        elif job is not None and not job.get("enabled"):
            bridge.resume(home, job_id)
    except (CronError, EngineError, OSError, ValueError) as error:
        raise ActionError(f"The Co-Founder's job didn't change: {error}"[:300], 503) from error
    add_activity(
        core.db,
        workspace_id,
        kind="rhythm.on" if on else "rhythm.off",
        text=f"{JOBS[which].name}: " + (time if on else "off"),
    )
    return list_all(core, workspace_id)


def ensure(core: Core, workspace_id: str) -> None:
    """The first Vision: each job the root's cron doesn't have yet is made, on, at
    its default time. Never raises (the Vision is saved either way)."""
    if core.engine is None or automation_actions.cron_bridge(core) is None:
        return
    try:
        _home, jobs = _jobs(core, workspace_id)
        have = {str(j.get("name")) for j in jobs}
        for which, plan in JOBS.items():
            if plan.name not in have:
                set_job(core, workspace_id, which, on=True, time=plan.time, day=plan.day)
    except (ActionError, CronError, EngineError, OSError, ValueError) as error:
        log.warning("the Co-Founder's jobs of %s not set up: %s", workspace_id, error)


def refresh_prompts(core: Core, workspace_id: str) -> int:
    """Each of the Co-Founder's rhythm jobs whose prompt is an older AGOS's text gets
    this AGOS's prompt (Hermes's `cron edit`), its time, day and on/off kept. A job
    AGOS holds for a while (archived, account pause) is left for later, so the edit
    never turns it off for good. Never raises; the number of jobs changed."""
    from agos_core.engine.cron import HELD_REASONS

    if core.engine is None:
        return 0
    bridge = automation_actions.cron_bridge(core)
    if bridge is None:
        return 0
    try:
        home, jobs = _jobs(core, workspace_id)
    except (CronError, OSError, ValueError, ActionError):
        return 0
    names = {plan.name: which for which, plan in JOBS.items()}
    changed = 0
    for job in jobs:
        which = names.get(str(job.get("name")))
        if which is None or str(job.get("prompt") or "") == PROMPTS[which]:
            continue
        enabled = bool(job.get("enabled"))
        reason = job.get("paused_reason")
        if not enabled and reason in HELD_REASONS and reason != WORK_HOURS_REASON:
            continue
        shown = _shown(which, job)
        spec = _spec(core, workspace_id, which, shown["time"], shown["day"])
        spec = JobSpec(**{**spec.as_dict(), "enabled": bool(shown["on"])})
        try:
            bridge.update(home, str(job["id"]), spec)
            changed += 1
        except (CronError, EngineError, OSError, ValueError):
            log.exception("could not refresh %s for %s", job.get("name"), workspace_id)
    return changed


def refresh_all(core: Core) -> int:
    """At start: every workspace's rhythm jobs at this AGOS's prompts."""
    from agos_core.db import workspaces as workspaces_repo

    return sum(refresh_prompts(core, w.id) for w in workspaces_repo.list_workspaces(core.db))
