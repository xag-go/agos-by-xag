"""A heartbeat per member (Step 48, F42): a Hermes cron job in the member's own
profile that wakes it on an interval with no task: review its cards, its pending
questions and proposals, the Co-Founder's requests and its connectors' inboxes;
do what is its, propose or ask when the owner is needed, write nothing otherwise.

The job is Hermes's (its cron holds the schedule, on/off, the executions ledger
AGOS shows as "last heartbeat"); AGOS keeps no row: the job is found again by its
name in the profile's cron. Default off; the owner toggles it per member with an
interval (15m / 1h / 4h / daily). Pausing a member (team.park) pauses its job with
AGOS's reason; deleting the member deletes its profile and the job with it. The
Co-Founder has the same toggle on the workspace's root, with one more line (the
team's blocked or stalled cards and the workspace's goal).

A no-work run must stay cheap: the prompt ends with "when there is nothing to do,
answer with one line and stop", so the run is one short turn.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agos_core.actions import agent_profiles
from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.db.records import Record
from agos_core.engine.cron import FAILURES_TO, WORK_HOURS_REASON, CronError, JobSpec
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.heartbeat")

JOB_NAME = "AGOS heartbeat"
PARKED_REASON = "Member paused in AGOS"
COFOUNDER = automation_actions.COFOUNDER  # "" = the workspace's root profile
# The owner's interval → the schedule Hermes's parser takes (cron/jobs.py parse_schedule).
INTERVALS: dict[str, str] = {"15m": "15m", "1h": "1h", "4h": "4h", "daily": "0 8 * * *"}
PROMPT_HEAD = "This is your heartbeat: a short review of what is yours, with no task given."


class Heartbeat(Record):
    """A member's heartbeat as the agent card shows it (the Co-Founder: agent "")."""

    agent: str
    on: bool
    interval: str | None = None
    schedule_display: str | None = None
    next_at: str | None = None
    last_at: str | None = None
    last_status: str | None = None
    problem: str | None = None


def prompt_for(agent: str | None, cofounder_lines: bool) -> str:
    """The heartbeat prompt (one template; who the agent is comes from its SOUL.md)."""
    lines = [
        PROMPT_HEAD,
        "",
        "Review, in this order, and only read what is needed to decide:",
        "1. Your open cards on the board: `hermes kanban list --mine` (ready, running,"
        " review, blocked). Continue what is yours; a blocked card of yours that you can"
        " unblock, unblock and work.",
        "2. Your pending questions and proposals to the owner (cards in his Inbox with your"
        " name): an answer that came back is work to pick up.",
        "3. The Co-Founder's recent requests to you (your DM and your topic): do what was"
        " asked within your role.",
        "4. Your connectors' inboxes, if you have any (mail, chat apps): anything addressed"
        " to your role.",
    ]
    if cofounder_lines:
        lines += [
            "5. The team's blocked or stalled cards (`hermes kanban list --status blocked`): a"
            " member that waits on something you can give, give it; one that needs the owner,"
            " leave it to his Inbox. Cards assigned to `founder` are the owner's own tasks:"
            " never work, unblock or reassign them, and never remind him of them here.",
            "6. The workspace goal: the Vision in your SOUL.md and its progress, from"
            " agos_goals with action status (each goal's key results, each project's cards"
            " done / open / blocked). A project with nothing open and not done: create its"
            " next card (its body starts with the project's '## Goal' line) for the member"
            " that owns it. A team stalled under a paused or stuck lead: say so to the"
            " owner once (agos_ask_owner). Today's plan and the recap are their own runs.",
            "7. A goal, key result or project whose work no member's role covers (a gap):"
            " follow your team-design skill (a role change or a reports_to move first);"
            " only when neither covers it, propose ONE hire with agos_propose kind hire,"
            " its why naming the gap, the goal or project (#id) and why no member covers"
            " it. A hire you proposed still waiting for the owner: propose nothing more.",
        ]
    lines += [
        "",
        "Do the work that is yours. When you need the owner, propose with agos_propose or ask"
        " with agos_ask_owner (never write to him otherwise). Never start work no card or"
        " request asked for.",
        "When there is nothing to do, answer with one line (`Nothing to do.`) and stop: this"
        " run must stay cheap.",
    ]
    return "\n".join(lines)


_MINUTES: dict[int, str] = {15: "15m", 60: "1h", 240: "4h"}
_EVERY = re.compile(r"every\s+(\d+)m")


def interval_of(schedule: Any) -> str | None:
    """The owner's interval a job's schedule stands for (None: another schedule).

    Hermes saves the parsed schedule (cron/jobs.py parse_schedule): `{"kind":
    "interval", "minutes": 240, "display": "every 240m"}` or `{"kind": "cron",
    "expr": "0 8 * * *"}`; AGOS's job reader hands over its expr or display text,
    and "4h" is what was asked for."""
    if isinstance(schedule, dict):
        if schedule.get("kind") == "interval":
            try:
                return _MINUTES.get(int(schedule.get("minutes") or 0))
            except (TypeError, ValueError):
                return None
        if schedule.get("kind") == "cron":
            schedule = str(schedule.get("expr") or "")
        else:
            return None
    text = str(schedule).strip()
    for name, expr in INTERVALS.items():
        if text == expr:
            return name
    every = _EVERY.fullmatch(text)  # Hermes's display ("every 240m"), as job_state reads it
    return _MINUTES.get(int(every.group(1))) if every else None


def _home_and_jobs(core: Core, workspace_id: str, agent: str) -> tuple[Any, list[dict[str, Any]]]:
    homes = automation_actions.homes(core, workspace_id)
    home = homes.get(agent)
    if home is None:
        raise NotFoundError("This member")
    if not (home / "config.yaml").is_file():
        raise ActionError("This member's profile isn't set up yet.", 409)
    custom = getattr(core.engine, "cron_bridge", None)
    from agos_core.engine.cron import read_jobs

    jobs = custom.job_states(home) if custom is not None else read_jobs(home)
    return home, jobs


def _job_of(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((j for j in jobs if j.get("name") == JOB_NAME), None)


def _view(agent: str, job: dict[str, Any] | None) -> Heartbeat:
    if job is None:
        return Heartbeat(agent=agent, on=False)
    reason = job.get("paused_reason")
    enabled = bool(job.get("enabled"))
    return Heartbeat(
        agent=agent,
        # Paused with the member, or off-hours (work hours): still "on".
        on=enabled or reason in (PARKED_REASON, WORK_HOURS_REASON),
        interval=interval_of(job.get("schedule") or "") or "custom",
        schedule_display=job.get("schedule_display"),
        next_at=job.get("next_run_at"),
        last_at=job.get("last_run_at"),
        last_status=job.get("last_status"),
        problem=(
            "Paused with the member."
            if reason == PARKED_REASON
            else "Paused off-hours: it wakes the agent at check-in."
            if reason == WORK_HOURS_REASON
            else f"Paused by the engine: {reason}"[:300]
            if not enabled and reason
            else None
        ),
    )


def list_all(core: Core, workspace_id: str) -> list[Heartbeat]:
    """Every member's heartbeat and the Co-Founder's (agent ""), read from the
    profiles' crons (read only; one read for the page)."""
    require_workspace(core, workspace_id)
    if core.engine is None:
        return []
    out = []
    for agent, home in automation_actions.homes(core, workspace_id).items():
        if not (home / "config.yaml").is_file():
            out.append(Heartbeat(agent=agent, on=False))
            continue
        try:
            _, jobs = _home_and_jobs(core, workspace_id, agent)
        except (CronError, OSError, ValueError, ActionError) as error:
            out.append(Heartbeat(agent=agent, on=False, problem=str(error)[:300]))
            continue
        out.append(_view(agent, _job_of(jobs)))
    return out


def _spec(core: Core, workspace_id: str, agent: str, interval: str, enabled: bool) -> JobSpec:
    from agos_core.actions import team
    from agos_core.actions.engine import _default_model
    from agos_core.actions.hermes_channel import cofounder_chat

    if agent:
        member = team.get(core, workspace_id, agent)
        found = agent_profiles.model_of(core, workspace_id, member) if member else None
    else:
        found = _default_model(core, workspace_id)
    provider, model, effort = found or ("", "", "")
    chat = cofounder_chat(core, workspace_id) if agent else None
    return JobSpec(
        name=JOB_NAME,
        prompt=prompt_for(agent or None, cofounder_lines=not agent),
        schedule=INTERVALS[interval],
        model=model,
        provider=provider,
        reasoning_effort=effort if effort and effort not in ("standard", "default") else None,
        enabled=enabled,
        failure_deliver=f"{FAILURES_TO}:{chat}" if chat is not None else FAILURES_TO,
        skills=tuple(automation_actions.pinned_skills(core, workspace_id, agent)),
    )


def set_heartbeat(
    core: Core,
    workspace_id: str,
    agent: str,
    *,
    on: bool,
    interval: str,
    record_revision: bool = True,
) -> Heartbeat:
    """The toggle: on makes (or re-times) the job in the member's own cron, off
    removes it. A parked member's job is made paused (it resumes with the member)."""
    require_workspace(core, workspace_id)
    if interval not in INTERVALS:
        raise ActionError("Interval: 15m, 1h, 4h or daily.")
    if agent and agent not in agent_profiles.team_names(core, workspace_id):
        raise NotFoundError("This member")
    if on and agent:
        from agos_core.actions import hire_kit

        if hire_kit.busy_only_onboarding(core, workspace_id, agent):  # step 62
            raise ActionError(
                f"@{agent} isn't ready for work yet: finish its Readiness (or Start anyway) "
                "before its heartbeat goes on.",
                409,
            )
    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so the heartbeat can't change now.", 409)
    home, jobs = _home_and_jobs(core, workspace_id, agent)
    job = _job_of(jobs)
    who = f"@{agent}" if agent else "the Co-Founder"
    if agent and record_revision:
        from agos_core.actions import agent_revisions

        agent_revisions.catch_up(core, workspace_id, agent)
    try:
        if not on:
            if job is not None:
                bridge.remove(home, str(job["id"]))
                add_activity(
                    core.db, workspace_id, kind="heartbeat.off", text=f"Heartbeat off for {who}"
                )
                _revision(core, workspace_id, agent, record_revision)
            return Heartbeat(agent=agent, on=False)
        parked = bool(agent) and _parked(core, workspace_id, agent)
        spec = _spec(core, workspace_id, agent, interval, enabled=not parked)
        if job is None:
            made = bridge.create(home, spec)
            job_id = str(made["id"])
        else:
            job_id = str(job["id"])
            bridge.update(home, job_id, spec)
        if parked:
            bridge.pause(home, job_id, PARKED_REASON)
    except (CronError, EngineError, OSError, ValueError) as error:
        raise ActionError(f"The heartbeat didn't change: {error}"[:300], 503) from error
    add_activity(
        core.db,
        workspace_id,
        kind="heartbeat.on",
        text=f"Heartbeat for {who}: every {interval}",
    )
    _revision(core, workspace_id, agent, record_revision)
    _, jobs = _home_and_jobs(core, workspace_id, agent)
    return _view(agent, _job_of(jobs))


def _revision(core: Core, workspace_id: str, agent: str, wanted: bool) -> None:
    """A member's heartbeat is part of who it is: its change is a revision."""
    if agent and wanted:
        from agos_core.actions import agent_revisions

        agent_revisions.record(core, workspace_id, agent)


def _parked(core: Core, workspace_id: str, agent: str) -> bool:
    from agos_core.actions import team
    from agos_core.engine import profile_meta

    where = team.home(core, workspace_id, agent)
    return where is not None and profile_meta.parked(where)


def follow_parked(core: Core, workspace_id: str, agent: str, parked: bool) -> None:
    """The member was paused (parked) or resumed: its heartbeat job follows (paused
    with AGOS's reason, resumed). Nothing to do without a job; never raises."""
    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None:
        return
    try:
        home, jobs = _home_and_jobs(core, workspace_id, agent)
        job = _job_of(jobs)
        if job is None:
            return
        if parked and job.get("enabled"):
            bridge.pause(home, str(job["id"]), PARKED_REASON)
        elif not parked and not job.get("enabled") and job.get("paused_reason") == PARKED_REASON:
            bridge.resume(home, str(job["id"]))
    except (CronError, EngineError, OSError, ValueError, ActionError, NotFoundError) as error:
        log.warning("heartbeat of %s in %s not followed: %s", agent, workspace_id, error)


def refresh_prompts(core: Core, workspace_id: str) -> int:
    """Each heartbeat job (the Co-Founder's and every member's) whose prompt is an
    older AGOS's text gets this AGOS's prompt (Hermes's `cron edit`), its interval
    and on/off kept. A job AGOS holds for a while (archived, account pause, off-hours)
    or on a schedule AGOS didn't set is left for later. Never raises; the number of
    jobs changed."""
    from agos_core.engine.cron import HELD_REASONS

    if core.engine is None:
        return 0
    bridge = automation_actions.cron_bridge(core)
    if bridge is None:
        return 0
    changed = 0
    for agent, home in automation_actions.homes(core, workspace_id).items():
        try:
            home, jobs = _home_and_jobs(core, workspace_id, agent)
        except (CronError, OSError, ValueError, ActionError):
            continue
        job = _job_of(jobs)
        if job is None:
            continue
        if str(job.get("prompt") or "") == prompt_for(agent or None, cofounder_lines=not agent):
            continue
        enabled = bool(job.get("enabled"))
        interval = interval_of(job.get("schedule") or "")
        if interval is None or (not enabled and job.get("paused_reason") in HELD_REASONS):
            continue
        try:
            # Paused with the member (or by the engine): edit keeps that reason.
            bridge.update(home, str(job["id"]), _spec(core, workspace_id, agent, interval, enabled))
            changed += 1
        except (CronError, EngineError, OSError, ValueError, ActionError):
            log.exception("could not refresh the heartbeat of %r in %s", agent, workspace_id)
    return changed


def refresh_all(core: Core) -> int:
    """At start: every workspace's heartbeat jobs at this AGOS's prompt."""
    from agos_core.db import workspaces as workspaces_repo

    return sum(refresh_prompts(core, w.id) for w in workspaces_repo.list_workspaces(core.db))
