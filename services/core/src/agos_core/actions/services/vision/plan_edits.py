"""Changing the plan: the Vision, goals, projects and results added, updated, deleted; a member who left.
Must not: decide an agent's suggestion (plan_changes does).

Split out of agos_core.actions.goals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.vision.plan_rows import (
    GOALS_MAX,
    PROJECTS_MAX,
    RESULTS_MAX,
    _one,
    _one_result,
    refresh,
    top,
)
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import key_results as key_results_repo
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.engine import goals as rules

__all__ = [
    "add_goal",
    "add_project",
    "add_result",
    "delete_item",
    "delete_result",
    "member_left",
    "note_owner_change",
    "set_vision",
    "update_item",
    "update_result",
]

# ---- writing ------------------------------------------------------------------------


def _text(value: Any, cap: int, what: str, *, required: bool = False) -> str:
    text = (
        " ".join(str(value or "").split()) if cap <= rules.TITLE_MAX else str(value or "").strip()
    )
    if required and not text:
        raise ActionError(f"Give the {what} a title.")
    if len(text) > cap:
        raise ActionError(f"Keep the {what} to {cap} characters.")
    return text


def _date(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if text and not rules.is_date(text):
        raise ActionError(f"The {what} is a date: YYYY-MM-DD.")
    return text


def _number(value: Any, what: str, *, empty_ok: bool = False) -> float | None:
    from agos_core.engine.proposals import _num

    if value is None or (isinstance(value, str) and not value.strip()):
        if empty_ok:
            return None
        raise ActionError(f"Give the {what} a number.")
    found = _num(value)
    if found is None:
        raise ActionError(f"The {what} must be a number.")
    return found


def _owner(core: Core, workspace_id: str, owner: Any) -> str:
    from agos_core.actions import team

    name = str(owner or "").strip().lstrip("@").lower()
    if name in ("", "cofounder", "co-founder"):
        return ""
    if name not in team._profile_names(core, workspace_id):
        raise ActionError(f"There is no agent named {name} in this workspace to own it.", 404)
    return name


def set_vision(
    core: Core, workspace_id: str, *, title: str, why: str = "", strategy: str = ""
) -> int:
    """The workspace's Vision, made or changed (one per workspace; the owner's). The
    first one also sets up the Co-Founder's daily rhythm (actions/rhythm.py)."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    title = _text(title, rules.TITLE_MAX, "Vision", required=True)
    why = _text(why, rules.TEXT_MAX, "why")
    strategy = _text(strategy, rules.TEXT_MAX, "strategy")
    made = False
    with transaction(core.db):
        found = goals_repo.vision_id(core.db, workspace_id)
        if found is None:
            goal_id = goals_repo.insert_vision(core.db, workspace_id, title, why, strategy)
            made = True
        else:
            goal_id = found
            goals_repo.update_vision(core.db, goal_id, title, why, strategy)
    refresh(core, workspace_id)
    if made:
        from agos_core.actions import rhythm

        rhythm.ensure(core, workspace_id)
    return goal_id


def _vision(core: Core, workspace_id: str) -> rules.Goal:
    found = top(core, workspace_id)
    if found is None:
        raise ActionError("Write the Vision first: goals serve it.", 409)
    return found


def _next_position(core: Core, workspace_id: str, parent: int) -> int:
    return goals_repo.next_position(core.db, workspace_id, parent)


def add_goal(
    core: Core,
    workspace_id: str,
    *,
    title: str,
    why: str = "",
    owner: str = "",
    due_on: str = "",
) -> int:
    """A goal under the Vision."""
    vision = _vision(core, workspace_id)
    if sum(1 for g in vision.children if g.status == "active") >= GOALS_MAX:
        raise ActionError(f"Keep to {GOALS_MAX} active goals: drop or finish one first.", 409)
    clean = (
        _text(title, rules.TITLE_MAX, "goal", required=True),
        _text(why, rules.TEXT_MAX, "why"),
        _owner(core, workspace_id, owner),
        _date(due_on, "due date"),
    )
    title, why, owner, due_on = clean
    with transaction(core.db):
        new_id = goals_repo.insert_goal(
            core.db,
            workspace_id,
            vision.id,
            title=title,
            why=why,
            owner=owner,
            due_on=due_on,
            position=_next_position(core, workspace_id, vision.id),
        )
    refresh(core, workspace_id)
    return new_id


def _project_fields(changes: dict[str, Any], current: rules.Goal | None) -> dict[str, Any]:
    sets: dict[str, Any] = {}
    if "project_kind" in changes:
        kind = str(changes["project_kind"] or "dated")
        if kind not in rules.PROJECT_KINDS:
            raise ActionError("A project is dated (start / end) or recurring (a rhythm).")
        sets["project_kind"] = kind
    if "starts_on" in changes:
        sets["starts_on"] = _date(changes["starts_on"], "start")
    if "ends_on" in changes:
        sets["ends_on"] = _date(changes["ends_on"], "end")
    if "rhythm" in changes:
        sets["rhythm"] = _text(changes["rhythm"], rules.RHYTHM_MAX, "rhythm")
    starts = sets.get("starts_on", current.starts_on if current else "")
    ends = sets.get("ends_on", current.ends_on if current else "")
    if starts and ends and ends < starts:
        raise ActionError("A project ends on or after its start.")
    return sets


def add_project(
    core: Core,
    workspace_id: str,
    goal_id: int,
    *,
    title: str,
    why: str = "",
    owner: str = "",
    project_kind: str = "dated",
    starts_on: str = "",
    ends_on: str = "",
    rhythm: str = "",
) -> int:
    """A project under one of the goals: dated (start / end) or recurring (a rhythm)."""
    goal = _one(core, workspace_id, int(goal_id))
    if goal.level != "goal":
        raise ActionError("A project serves a goal: pick one of the goals.")
    if goals_repo.active_children(core.db, workspace_id, goal.id) >= PROJECTS_MAX:
        raise ActionError(f"Keep to {PROJECTS_MAX} active projects per goal.", 409)
    shape = _project_fields(
        {
            "project_kind": project_kind or "dated",
            "starts_on": starts_on,
            "ends_on": ends_on,
            "rhythm": rhythm,
        },
        None,
    )
    with transaction(core.db):
        new_id = goals_repo.insert_project(
            core.db,
            workspace_id,
            goal.id,
            title=_text(title, rules.TITLE_MAX, "project", required=True),
            why=_text(why, rules.TEXT_MAX, "why"),
            owner=_owner(core, workspace_id, owner),
            project_kind=shape["project_kind"],
            starts_on=shape["starts_on"],
            ends_on=shape["ends_on"],
            rhythm=shape["rhythm"],
            position=_next_position(core, workspace_id, goal.id),
        )
    refresh(core, workspace_id)
    return new_id


def update_item(core: Core, workspace_id: str, item_id: int, changes: dict[str, Any]) -> None:
    """A goal's or a project's title, why, owner, status, position, due date (a
    goal), shape (a project) or goal (a project moves to another goal)."""
    current = _one(core, workspace_id, item_id)
    if current.parent_id is None:
        raise ActionError("That is the Vision: change it with its own form.")
    what = "project" if current.level == "project" else "goal"
    sets: dict[str, Any] = {}
    if "title" in changes:
        sets["title"] = _text(changes["title"], rules.TITLE_MAX, what, required=True)
    if "why" in changes:
        sets["why"] = _text(changes["why"], rules.TEXT_MAX, "why")
    if "owner" in changes:
        sets["owner"] = _owner(core, workspace_id, changes["owner"])
    if "status" in changes:
        status = str(changes["status"] or "")
        if status not in rules.STATUSES:
            raise ActionError(
                f"A {what} is {', '.join(rules.STATUSES[:-1])} or {rules.STATUSES[-1]}."
            )
        sets["status"] = status
    if "position" in changes:
        sets["position"] = int(changes["position"] or 0)
    if what == "goal" and "due_on" in changes:
        sets["due_on"] = _date(changes["due_on"], "due date")
    if what == "project":
        sets.update(_project_fields(changes, current))
        if changes.get("parent_id"):
            goal = _one(core, workspace_id, int(changes["parent_id"]))
            if goal.level != "goal":
                raise ActionError("A project serves a goal: pick one of the goals.")
            sets["parent_id"] = goal.id
    if not sets:
        return
    with transaction(core.db):
        goals_repo.update(core.db, item_id, sets)
    refresh(core, workspace_id)


def delete_item(core: Core, workspace_id: str, item_id: int) -> None:
    """A goal (with its projects and key results) or a project goes. Cards that
    named it keep their line (shown as gone, counted nowhere)."""
    current = _one(core, workspace_id, item_id)
    if current.parent_id is None:
        raise ActionError("The Vision stays: change it instead.", 409)
    with transaction(core.db):
        if current.level != "project":
            goals_repo.delete_children(core.db, workspace_id, item_id)
        goals_repo.delete(core.db, workspace_id, item_id)
    refresh(core, workspace_id)


def add_result(
    core: Core,
    workspace_id: str,
    goal_id: int,
    *,
    title: str,
    start: Any = 0,
    current: Any = None,
    target: Any = None,
    unit: str = "",
    due_on: str = "",
) -> int:
    """A key result of a goal: a number from its start to its target."""
    goal = _one(core, workspace_id, int(goal_id))
    if goal.level != "goal":
        raise ActionError("Key results measure a goal: pick one of the goals.")
    if key_results_repo.count_for(core.db, workspace_id, goal.id) >= RESULTS_MAX:
        raise ActionError(f"Keep to {RESULTS_MAX} key results per goal.", 409)
    begin = _number(start, "start", empty_ok=True) or 0.0
    now_value = _number(current, "current value", empty_ok=True)
    with transaction(core.db):
        position = key_results_repo.next_position(core.db, goal.id)
        new_id = key_results_repo.insert(
            core.db,
            workspace_id,
            goal.id,
            title=_text(title, rules.TITLE_MAX, "key result", required=True),
            start_value=begin,
            current=begin if now_value is None else now_value,
            target=_number(target, "target", empty_ok=True),
            unit=_text(unit, rules.UNIT_MAX, "unit"),
            due_on=_date(due_on, "due date"),
            position=position,
        )
    refresh(core, workspace_id)
    return new_id


def update_result(core: Core, workspace_id: str, kr_id: int, changes: dict[str, Any]) -> None:
    """A key result's title, numbers, unit, due date (and where its number came from)."""
    _one_result(core, workspace_id, kr_id)
    sets: dict[str, Any] = {}
    if "title" in changes:
        sets["title"] = _text(changes["title"], rules.TITLE_MAX, "key result", required=True)
    if "start" in changes:
        sets["start_value"] = _number(changes["start"], "start")
    if "current" in changes:
        sets["current"] = _number(changes["current"], "current value")
        sets["source"] = _text(changes.get("source") or "the owner", 300, "source")
    if "target" in changes:
        sets["target"] = _number(changes["target"], "target", empty_ok=True)
    if "unit" in changes:
        sets["unit"] = _text(changes["unit"], rules.UNIT_MAX, "unit")
    if "due_on" in changes:
        sets["due_on"] = _date(changes["due_on"], "due date")
    if "position" in changes:
        sets["position"] = int(changes["position"] or 0)
    if not sets:
        return
    with transaction(core.db):
        key_results_repo.update(core.db, kr_id, sets)
    refresh(core, workspace_id)


def delete_result(core: Core, workspace_id: str, kr_id: int) -> None:
    _one_result(core, workspace_id, kr_id)
    with transaction(core.db):
        key_results_repo.delete(core.db, workspace_id, kr_id)
    refresh(core, workspace_id)


def member_left(core: Core, workspace_id: str, name: str) -> None:
    """A member leaves the team: the goals and projects it owned have no owner now."""
    with transaction(core.db):
        changed = goals_repo.clear_owner(core.db, workspace_id, name)
    if changed:
        refresh(core, workspace_id)


def note_owner_change(core: Core, workspace_id: str, text: str) -> None:
    """The owner's change to the plan, in the workspace's Log (who did what, step 55)."""
    add_activity(core.db, workspace_id, kind="goal.changed", text=text[:300])
