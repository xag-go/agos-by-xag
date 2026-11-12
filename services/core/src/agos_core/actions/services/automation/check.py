"""Check an automation before it is saved: the problems that block the save, the
warnings that don't, and the plain "this is how it will run" preview.

The owner's Save button (the web asks `review`) and the Co-Founder (create / update /
check_automation) get the same words. Every save runs `refuse_if_broken` first, so
nothing reaches the board that the preview could not explain.

Owns: reading the team + schedule words from the workspace and handing them to the
pure checks (engine/automation_check.py). Must not: save anything.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import team
from agos_core.actions.errors import ActionError
from agos_core.actions.services.automation.cron import describe_schedule, schedule_problem
from agos_core.context import Core
from agos_core.db.records import Automation
from agos_core.engine import automation_check as check

__all__ = ["Report", "problems_text", "refuse_if_broken", "review", "review_form"]

Report = check.Report


def _team(core: Core, workspace_id: str) -> dict[str, check.Who]:
    return {
        a.name.lower(): check.Who(a.title or a.name, a.on) for a in team.members(core, workspace_id)
    }


def review(core: Core, workspace_id: str, spec: dict[str, Any], *, words: bool = False) -> Report:
    """`spec`: name, instructions, schedule, hook, agent, steps (dicts), variables
    (dicts), check_first. words=True also asks for the schedule's own words (one more
    call: the preview and the dry run use it, a plain save check does not)."""
    schedule = str(spec.get("schedule") or "").strip()
    display: str | None = None
    problem: str | None = None
    if schedule and words:
        display, problem = describe_schedule(core, workspace_id, schedule)
    elif schedule:
        problem = schedule_problem(core, workspace_id, schedule)
    return check.check(
        spec, _team(core, workspace_id), schedule_problem=problem, schedule_text=display
    )


def refuse_if_broken(
    core: Core,
    workspace_id: str,
    kept: Automation | None,
    said: tuple[str, str, str, bool, str | None, bool],
    steps: list[Any],
    variables: list[Any] | None,
) -> Report:
    """The save's gate: every problem at once, or the report (warnings, preview).
    `said`: name, instructions, schedule, hook, agent, check_first as being saved;
    variables None = what the automation (`kept`) has now."""
    name, instructions, schedule, hook, agent, check_first = said
    held = [v.model_dump() for v in kept.variables] if kept is not None else []
    given = [v if isinstance(v, dict) else v.model_dump() for v in variables or []]
    report = review(
        core,
        workspace_id,
        {
            "name": name,
            "instructions": instructions,
            "schedule": schedule,
            "hook": hook,
            "agent": agent,
            "steps": [s if isinstance(s, dict) else s.model_dump() for s in steps],
            "variables": held if variables is None else given,
            "check_first": check_first,
        },
    )
    if report.problems:
        raise ActionError(problems_text(report.problems))
    return report


def problems_text(problems: tuple[str, ...] | list[str]) -> str:
    if len(problems) == 1:
        return f"Not saved. Fix this first: {problems[0]}"
    lines = "\n".join(f"{n}. {p}" for n, p in enumerate(problems, 1))
    return f"Not saved. Fix these {len(problems)} things first:\n{lines}"


def review_form(
    core: Core, workspace_id: str, automation_id: int | None, spec: dict[str, Any]
) -> Report:
    """What the owner's Save button asks: the form as it will be saved (hook / variables
    left out = what the automation has now), with the schedule's own words."""
    from agos_core.actions import automations

    kept = automations.get(core, workspace_id, automation_id) if automation_id else None
    full = dict(spec)
    if full.get("hook") is None:
        full["hook"] = kept is not None and kept.hook is not None
    if full.get("variables") is None:
        full["variables"] = [v.model_dump() for v in kept.variables] if kept else []
    return review(core, workspace_id, full, words=True)
