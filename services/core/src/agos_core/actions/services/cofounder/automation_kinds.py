"""The Co-Founder's automation actions: save an automation, its snapshot for Undo.
Must not: hold the automation logic (actions/automations.py does).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.services.automation import check as automation_check
from agos_core.actions.services.cofounder.merges import merged_lines, merged_steps
from agos_core.actions.services.cofounder.team_kinds import _agent_field, _default_model
from agos_core.context import Core

__all__ = [
    "automation_id_of",
    "automation_snapshot",
    "changed_automation",
    "check_spec",
    "how_it_runs",
    "new_automation",
    "precheck",
    "put_back",
    "save_automation",
    "truthy",
]

# ---- doing -----------------------------------------------------------------------------


def automation_id_of(core: Core, workspace_id: str, name: str) -> int:
    wanted = name.strip().lower()
    items = automation_actions.list_all(core, workspace_id)  # names are Hermes's jobs' own
    for a in items:
        if a.name.strip().lower() == wanted or str(a.id) == wanted.lstrip("#"):
            return a.id
    raise ActionError(f"There is no automation named “{name}” in this workspace.", 404)


def truthy(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "no", "off", "0")


def automation_snapshot(core: Core, workspace_id: str, automation_id: int) -> dict[str, Any]:
    a = automation_actions.get(core, workspace_id, automation_id)
    if a is None:
        return {}
    return {
        "name": a.name,
        "instructions": a.instructions,
        "schedule": a.schedule,
        "model": a.model.model_dump(),
        "on": a.on,
        "agent": a.agent,
        "steps": [s.model_dump() for s in a.steps],
        "webhook": a.hook is not None,
        "webhook_events": a.hook.events if a.hook else [],
        "webhook_conditions": [c.model_dump() for c in a.hook.conditions] if a.hook else [],
        "check_first": a.check_first,
        "variables": [v.model_dump() for v in a.variables],
        "policy": a.policy,
        "catch_up": a.catch_up,
    }


def save_automation(
    core: Core,
    workspace_id: str,
    automation_id: int | None,
    s: dict[str, Any],
    *,
    unchecked: bool = False,
) -> int:
    saved = _save_automation_row(core, workspace_id, automation_id, s, unchecked)
    if s.get("webhook") is True and "webhook_conditions" in s:
        # Its webhook's events and "Only if" lines: Hermes's route filters.
        from agos_core.actions import hooks
        from agos_core.db.records import HookCondition

        hooks.set_hook(
            core,
            workspace_id,
            saved,
            on=True,
            events=[str(e) for e in s.get("webhook_events") or []],
            conditions=[HookCondition.model_validate(c) for c in s["webhook_conditions"] or []],
        )
    return saved


def put_back(core: Core, workspace_id: str, automation_id: int | None, s: dict[str, Any]) -> int:
    """Undo puts back what was: saved as it was, not checked again."""
    return save_automation(core, workspace_id, automation_id, s, unchecked=True)


def _save_automation_row(
    core: Core, workspace_id: str, automation_id: int | None, s: dict[str, Any], unchecked: bool
) -> int:
    from agos_core.domain.models import ModelSelection

    return automation_actions.save(
        core,
        workspace_id,
        automation_id,
        name=str(s["name"]),
        instructions=str(s["instructions"]),
        schedule=str(s["schedule"]),
        model=ModelSelection.model_validate(s["model"]),
        on=bool(s["on"]),
        agent=s.get("agent"),
        steps=s.get("steps") or [],
        hook=s.get("webhook") if isinstance(s.get("webhook"), bool) else None,
        check_first=bool(s.get("check_first")),
        variables=s.get("variables") if isinstance(s.get("variables"), list) else None,
        policy=str(s["policy"]) if s.get("policy") else None,
        catch_up=str(s["catch_up"]) if s.get("catch_up") in ("once", "skip") else None,
        who="cofounder",
        unchecked=unchecked,
    )


# ---- what the Co-Founder asked for, as the automation it would save -----------------------


def new_automation(core: Core, workspace_id: str, p: dict[str, Any]) -> dict[str, Any]:
    """create_automation's fields as the automation to save."""
    return {
        "name": p["name"],
        "instructions": p["instructions"],
        "schedule": str(p.get("schedule") or ""),
        "model": _default_model(core, workspace_id),
        "on": truthy(p.get("on")),
        "agent": _agent_field(p.get("agent")),
        "steps": p.get("steps") or [],
        "webhook": truthy(p.get("webhook")) if "webhook" in p else None,
        "check_first": truthy(p.get("check_first"), default=False),
        **(
            {
                "webhook_events": list(p.get("webhook_events") or []),
                "webhook_conditions": list(p.get("webhook_conditions") or []),
            }
            if "webhook_conditions" in p or "webhook_events" in p
            else {}
        ),
    }


def changed_automation(before: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """update_automation's fields applied to the automation as it is now."""
    after = dict(before)
    _text_and_who(before, p, after)
    if "on" in p:
        after["on"] = truthy(p.get("on"))
    if "webhook" in p:
        after["webhook"] = truthy(p.get("webhook"))
    _webhook_lines(before, p, after)
    if "check_first" in p:
        after["check_first"] = truthy(p.get("check_first"), default=False)
    if "variables" in p or "remove_variables" in p:
        after["variables"] = _merged_variables(before, p)
    _plain_settings(p, after)
    return after


def _text_and_who(before: dict[str, Any], p: dict[str, Any], after: dict[str, Any]) -> None:
    """name / schedule / instructions, and who does it (steps, or one agent)."""
    for key in ("name", "schedule", "instructions"):
        if p.get(key):
            after[key] = p[key]
    if p.get("steps") or p.get("remove_steps"):
        after["steps"] = merged_steps(
            list(before.get("steps") or []),
            list(p.get("steps") or []),
            [str(k) for k in p.get("remove_steps") or []],
        )
        after["agent"] = None if after["steps"] else before.get("agent")
    elif p.get("agent"):
        after["agent"], after["steps"] = _agent_field(p["agent"]), []


def _plain_settings(p: dict[str, Any], after: dict[str, Any]) -> None:
    if p.get("policy"):
        after["policy"] = str(p["policy"])
    if p.get("catch_up") in ("once", "skip"):
        after["catch_up"] = str(p["catch_up"])
    if "schedule" in p and p.get("schedule") == "":
        after["schedule"] = ""


def _webhook_lines(before: dict[str, Any], p: dict[str, Any], after: dict[str, Any]) -> None:
    """The webhook's events and "Only if" lines after an update (added / removed)."""
    if "webhook_events" in p or "remove_webhook_events" in p:
        gone = {str(e) for e in p.get("remove_webhook_events") or []}
        events = [str(e) for e in before.get("webhook_events") or []]
        events += [str(e) for e in p.get("webhook_events") or [] if str(e) not in events]
        after["webhook_events"] = [e for e in events if e not in gone]
    if "webhook_conditions" in p or "remove_webhook_conditions" in p:
        after["webhook_conditions"] = merged_lines(
            list(before.get("webhook_conditions") or []),
            list(p.get("webhook_conditions") or []),
            list(p.get("remove_webhook_conditions") or []),
        )


def _merged_variables(before: dict[str, Any], p: dict[str, Any]) -> list[Any]:
    """Variables by name: a sent one replaces its namesake, the rest stay."""
    gone = {str(n) for n in p.get("remove_variables") or []}
    kept_vars = {
        str(v.get("name")): v for v in before.get("variables") or [] if isinstance(v, dict)
    }
    for v in p.get("variables") or []:
        if isinstance(v, dict) and v.get("name"):
            kept_vars[str(v["name"])] = {**kept_vars.get(str(v["name"]), {}), **v}
    return [v for n, v in kept_vars.items() if n not in gone]


def check_spec(s: dict[str, Any], was_hook: bool = False) -> dict[str, Any]:
    """An automation in save_automation's shape, as the checks read it."""
    hook = s.get("webhook")
    return {
        "name": s.get("name"),
        "instructions": s.get("instructions"),
        "schedule": s.get("schedule"),
        "hook": hook if isinstance(hook, bool) else was_hook,
        "agent": s.get("agent"),
        "steps": [x if isinstance(x, dict) else x.model_dump() for x in s.get("steps") or []],
        "variables": s.get("variables") or [],
        "check_first": bool(s.get("check_first")),
    }


def _said(report: automation_check.Report) -> str:
    text = report.preview
    if report.warnings:
        text += "\nWorth a look (not blocking):\n" + "\n".join(f"- {w}" for w in report.warnings)
    return text


def how_it_runs(core: Core, workspace_id: str, automation_id: int) -> str:
    """The saved automation's plain "this is how it runs" text, for the Co-Founder to
    tell the owner."""
    snap = automation_snapshot(core, workspace_id, automation_id)
    report = automation_check.review(core, workspace_id, check_spec(snap), words=True)
    return _said(report)


def precheck(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> str | None:
    """A create / update_automation as it would be saved, checked now (before its card
    waits for the owner): the problems text, or None."""
    if action == "create_automation":
        after = new_automation(core, workspace_id, p)
        was_hook = False
    else:
        before = automation_snapshot(
            core, workspace_id, automation_id_of(core, workspace_id, str(p["automation"]))
        )
        after = changed_automation(before, p)
        was_hook = bool(before.get("webhook"))
    report = automation_check.review(core, workspace_id, check_spec(after, was_hook))
    return automation_check.problems_text(report.problems) if report.problems else None


def dry_run(core: Core, workspace_id: str, p: dict[str, Any]) -> str:
    """check_automation: what saving this would say (problems, or how it will run)."""
    if p.get("automation"):
        before = automation_snapshot(
            core, workspace_id, automation_id_of(core, workspace_id, str(p["automation"]))
        )
        after = changed_automation(before, p) if len(p) > 1 else before
        was_hook = bool(before.get("webhook"))
    else:
        after = new_automation(core, workspace_id, {"name": "", "instructions": "", **p})
        was_hook = False
    report = automation_check.review(core, workspace_id, check_spec(after, was_hook), words=True)
    if report.problems:
        return (
            "Would NOT be saved. "
            + automation_check.problems_text(report.problems)[len("Not saved. ") :]
        )
    return "Nothing is saved. It would be accepted. " + _said(report)
