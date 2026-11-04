"""An agent's suggested change to the plan: checked, then applied once the owner approves.
Must not: apply a change he did not approve.

Split out of agos_core.actions.goals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.vision.plan_edits import (
    _owner,
    add_goal,
    add_project,
    add_result,
    delete_item,
    delete_result,
    set_vision,
    update_item,
    update_result,
)
from agos_core.actions.services.vision.plan_rows import _one, _one_result, top
from agos_core.context import Core
from agos_core.engine import goals as rules

__all__ = [
    "apply_change",
    "check_change",
]

# ---- an agent's proposed change (Inbox kind 'goal') ---------------------------------

_ROW_OF: dict[str, tuple[str, str]] = {
    # change -> (the payload's id field, the level it must name)
    "update_goal": ("goal_id", "goal"),
    "drop_goal": ("goal_id", "goal"),
    "update_subgoal": ("goal_id", ""),
    "drop_subgoal": ("goal_id", ""),
    "add_kr": ("goal_id", "goal"),
    "add_project": ("goal_id", "goal"),
    "update_project": ("project_id", "project"),
    "drop_project": ("project_id", "project"),
    "delete_goal": ("goal_id", "goal"),
    "delete_project": ("project_id", "project"),
}


def check_change(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """What keeps a proposed plan change from being approved."""
    from agos_core.actions import today
    from agos_core.engine import proposals as proposal_rules

    payload = proposal_rules.as_delete(payload)
    change = str(payload.get("change") or "")
    out = proposal_rules.problems("goal", payload)
    named = _ROW_OF.get(change)
    if named is not None and payload.get(named[0]):
        try:
            found: rules.Goal | None = _one(core, workspace_id, int(payload.get(named[0]) or 0))
        except (NotFoundError, ValueError):
            found = None
        if found is None or found.parent_id is None or (named[1] and found.level != named[1]):
            out.append(f"{named[0]} must be a {named[1] or 'goal'} of this workspace")
    if change in ("update_kr", "drop_kr", "kr_update", "delete_kr") and payload.get("kr_id"):
        try:
            _one_result(core, workspace_id, int(payload.get("kr_id") or 0))
        except (NotFoundError, ValueError):
            out.append("kr_id must be a key result of this workspace")
    if change in ("add_goal", "add_subgoal") and top(core, workspace_id) is None:
        out.append("there is no Vision yet: the owner writes it first")
    if payload.get("owner"):
        try:
            _owner(core, workspace_id, payload.get("owner"))
        except ActionError as error:
            out.append(error.message)
    if change == "daily_plan":
        out += today.plan_problems(core, workspace_id, payload)
    return out


def apply_change(core: Core, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The owner approved it (as it was, or as he edited it): made as if he made it."""
    from agos_core.actions import today
    from agos_core.engine import proposals as proposal_rules

    payload = proposal_rules.as_delete(payload)
    change = str(payload.get("change") or "")
    p = payload
    title = str(p.get("title") or "")
    if change in ("suggest_vision", "set_goal"):
        vision = top(core, workspace_id)
        return {
            "goal_id": set_vision(
                core,
                workspace_id,
                title=title,
                why=str(
                    p.get("vision_why")
                    or p.get("goal_why")
                    or (vision.why if vision is not None else "")
                ),
                strategy=str(p.get("strategy") or (vision.strategy if vision is not None else "")),
            )
        }
    if change == "add_subgoal" and p.get("parent_id"):
        parent = _one(core, workspace_id, int(p["parent_id"]))
        if parent.level == "goal":
            change, p = "add_project", {**p, "goal_id": parent.id}
    if change in ("add_goal", "add_subgoal"):
        goal_id = add_goal(
            core,
            workspace_id,
            title=title,
            why=str(p.get("goal_why") or ""),
            owner=str(p.get("owner") or ""),
            due_on=str(p.get("due_on") or ""),
        )
        # Its key results and projects, when the proposal carries them (the Vision
        # notes' goals, actions/vision_notes.py).
        kr_ids = [
            add_result(
                core,
                workspace_id,
                goal_id,
                title=str(kr.get("title") or ""),
                target=kr.get("target"),
                unit=str(kr.get("unit") or ""),
                due_on=str(kr.get("due_on") or ""),
            )
            for kr in p.get("key_results") or []
            if isinstance(kr, dict)
        ]
        project_ids = [
            add_project(core, workspace_id, goal_id, title=str(pr.get("title") or ""))
            for pr in p.get("projects") or []
            if isinstance(pr, dict)
        ]
        if kr_ids or project_ids:
            return {"goal_id": goal_id, "kr_ids": kr_ids, "project_ids": project_ids}
        return {"goal_id": goal_id}
    if change == "add_project":
        return {
            "goal_id": add_project(
                core,
                workspace_id,
                int(p.get("goal_id") or 0),
                title=title,
                why=str(p.get("project_why") or ""),
                owner=str(p.get("owner") or ""),
                project_kind=str(p.get("project_kind") or "dated"),
                starts_on=str(p.get("starts_on") or ""),
                ends_on=str(p.get("ends_on") or ""),
                rhythm=str(p.get("rhythm") or ""),
            )
        }
    if change == "add_kr":
        return {
            "kr_id": add_result(
                core,
                workspace_id,
                int(p.get("goal_id") or 0),
                title=title,
                start=p.get("start"),
                current=p.get("current"),
                target=p.get("target"),
                unit=str(p.get("unit") or ""),
                due_on=str(p.get("due_on") or ""),
            )
        }
    if change in ("update_kr", "kr_update", "drop_kr", "delete_kr"):
        kr_id = int(p.get("kr_id") or 0)
        if change in ("drop_kr", "delete_kr"):
            delete_result(core, workspace_id, kr_id)
        elif change == "kr_update":
            update_result(
                core,
                workspace_id,
                kr_id,
                {"current": p.get("current"), "source": p.get("source")},
            )
        else:
            numbers = ("title", "start", "current", "target", "unit", "due_on")
            update_result(core, workspace_id, kr_id, {k: p[k] for k in numbers if k in p})
        return {"kr_id": kr_id}
    if change == "daily_plan":
        return today.accept(core, workspace_id, p)
    item_id = int(p.get("project_id") or p.get("goal_id") or 0)
    if change in ("delete_goal", "delete_project"):
        delete_item(core, workspace_id, item_id)  # a goal goes with its projects and KRs
        return {"goal_id": item_id, "deleted": True}
    if change in ("drop_goal", "drop_subgoal", "drop_project"):
        update_item(core, workspace_id, item_id, {"status": "dropped"})
        return {"goal_id": item_id}
    renames = {"goal_why": "why", "project_why": "why", "parent_id": "parent_id"}
    fields = (
        "title",
        "owner",
        "status",
        "due_on",
        "project_kind",
        "starts_on",
        "ends_on",
        "rhythm",
        "goal_why",
        "project_why",
    )
    update_item(
        core,
        workspace_id,
        item_id,
        {renames.get(k, k): p[k] for k in fields if k in p and p[k] is not None},
    )
    return {"goal_id": item_id}
