"""The post-hire review: a week after the owner approves a hire, the Co-Founder looks
at whether the new member closes the gap it was hired for.

One ONE-SHOT Hermes cron job in the workspace's root profile (the Co-Founder's own
cron, like the Vision page's jobs in actions/rhythm.py), due REVIEW_AFTER_DAYS after
the approve (an ISO time: Hermes's cron/jobs.py parse_schedule makes it a `once`
job, which its scheduler runs one time). AGOS keeps no row: the job's id rides in
the hire's result (the proposal row, or the Co-Founder action's), so Undo of the
hire removes the job. Its answer is delivered to the Co-Founder chat (the 'agos'
platform, FAILURES_TO); `[SILENT]` (the member is gone) sends nothing. A job that
can't be made never stops the hire (logged).
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.engine.cron import FAILURES_TO, CronError, JobSpec
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hire_review")

REVIEW_AFTER_DAYS = 7
JOB_PREFIX = "agos-hire-review-"


def job_name(member: str) -> str:
    return f"{JOB_PREFIX}{member}"


def prompt_for(payload: dict[str, Any], goal: str, since: str) -> str:
    """What the Co-Founder is told when the week is up."""
    name = str(payload.get("name") or "")
    title = str(payload.get("title") or name)
    why = str(payload.get("why") or "").strip() or "(no why was given)"
    served = goal or "the workspace goal (no goal was named)"
    return "\n".join(
        [
            f"This is the post-hire review of @{name} ({title}), hired on {since} for "
            f"{served}. The hire's why: {why}",
            "",
            f"1. Is @{name} still on the team (your view of the team)? If it is gone,"
            " answer exactly `[SILENT]` and stop (nothing is sent).",
            "2. Read that goal's progress with agos_goals (action status) and the member's"
            f" cards and work since {since} (`hermes kanban list --assignee a-{name}`, its"
            " done cards' results, what it is blocked on).",
            "3. The gap is closing: your answer is a short note to the owner (two or"
            " three lines: what it did, what moved); it reaches him in this chat.",
            "4. It is not closing: propose ONE fix with agos_propose, with its why — a"
            " change to its role or instructions, a reports_to move, or ask the owner"
            " (agos_ask_owner) whether to remove the member. Follow your team-design"
            " skill. The owner sees it in his Inbox; your answer says in one line what"
            " you proposed.",
            "",
            "Never remove or change the member yourself in this run, and keep it short.",
        ]
    )


def _goal_line(core: Core, workspace_id: str, goal_id: Any) -> str:
    if not isinstance(goal_id, int):
        return ""
    row = goals_repo.get(core.db, workspace_id, goal_id)
    if row is None:
        return f"#{goal_id}"
    kind = "project" if str(row["level"] or "") == "project" else "sub-goal"
    return f"{kind} #{goal_id} '{row['title']}'"


def schedule(
    core: Core, workspace_id: str, payload: dict[str, Any], *, at: datetime | None = None
) -> str | None:
    """The review job in the Co-Founder's cron (its id), or None when it couldn't be
    made: never raises, the hire stands either way. An earlier review of the same
    name (a hire undone and made again) is replaced."""
    from agos_core.actions.engine import _default_model

    bridge = automation_actions.cron_bridge(core)
    name = str(payload.get("name") or "")
    if bridge is None or core.engine is None or not name:
        return None
    hired = at or datetime.now(UTC)
    due = (hired + timedelta(days=REVIEW_AFTER_DAYS)).replace(microsecond=0)
    try:
        home = core.engine.profile_home(workspace_id)
        for job in bridge.job_states(home):
            if job.get("name") == job_name(name):
                with contextlib.suppress(CronError, EngineError, OSError):
                    bridge.remove(home, str(job["id"]))
        provider, model, effort = _default_model(core, workspace_id) or ("", "", "")
        spec = JobSpec(
            name=job_name(name),
            prompt=prompt_for(
                payload,
                _goal_line(core, workspace_id, payload.get("goal_id")),
                hired.date().isoformat(),
            ),
            schedule=due.isoformat(),
            model=model,
            provider=provider,
            reasoning_effort=effort if effort and effort not in ("standard", "default") else None,
            enabled=True,
            failure_deliver=FAILURES_TO,
            deliver=FAILURES_TO,  # its note reaches the owner in the Co-Founder chat
            skills=tuple(automation_actions.pinned_skills(core, workspace_id, "")),
        )
        made = bridge.create(home, spec)
    except (ActionError, CronError, EngineError, OSError, ValueError) as error:
        log.warning("post-hire review of %s in %s not scheduled: %s", name, workspace_id, error)
        return None
    except Exception:
        log.exception("post-hire review of %s in %s not scheduled", name, workspace_id)
        return None
    return str(made["id"])


def cancel(core: Core, workspace_id: str, job_id: str) -> None:
    """Undo of the hire: its review goes too (already run or gone = nothing)."""
    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None or not job_id:
        return
    try:
        bridge.remove(core.engine.profile_home(workspace_id), job_id)
    except (CronError, EngineError, OSError) as error:
        log.info("post-hire review %s of %s not removed: %s", job_id, workspace_id, error)
