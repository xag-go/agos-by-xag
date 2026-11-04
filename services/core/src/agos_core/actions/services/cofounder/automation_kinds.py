"""The Co-Founder's automation actions: save an automation, its snapshot for Undo.
Must not: hold the automation logic (actions/automations.py does).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError
from agos_core.context import Core

__all__ = [
    "automation_id_of",
    "automation_snapshot",
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
    core: Core, workspace_id: str, automation_id: int | None, s: dict[str, Any]
) -> int:
    saved = _save_automation_row(core, workspace_id, automation_id, s)
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


def _save_automation_row(
    core: Core, workspace_id: str, automation_id: int | None, s: dict[str, Any]
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
    )
