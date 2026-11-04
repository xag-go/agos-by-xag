"""A Hermes Kanban task as the Board page shows it: the card's fields, its member's
name, the goal it serves, its labels, and the buttons its column allows.

Split out of agos_core.actions.kanban_board (its `_card` and `_with_actions`).

Owns: turning one task dict (Hermes's list / show) into the page's card.
Must not: read Hermes (the callers pass what they read) or write a card.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.services.board import card_members
from agos_core.actions.services.board.card_text import skill_pins, without_pins
from agos_core.actions.services.board.kanban_workflow import card_actions

__all__ = [
    "card_of",
    "with_actions",
]


def with_actions(
    card: dict[str, Any], cols: list[dict[str, Any]], manual: dict[str, set[str]]
) -> dict[str, Any]:
    labels = {c["status"]: c["label"] for c in cols}
    status = str(card.get("status") or "")
    return {
        **card,
        "statusLabel": labels.get(status, status),
        "actions": card_actions(status, manual),
    }


def card_of(
    raw: dict[str, Any], members: dict[str, dict[str, str]], cofounder: str
) -> dict[str, Any]:
    from agos_core.engine import goals as goal_rules
    from agos_core.engine import reviews as review_rules
    from agos_core.engine import threads as thread_rules

    assignee = str(raw.get("assignee") or "")
    who = members.get(assignee) or card_members.legacy_member(assignee, members)
    labels = thread_rules.card_labels(str(raw.get("body") or ""))
    body = thread_rules.without_labels(review_rules.without_policy(str(raw.get("body") or "")))
    own_goal = goal_rules.card_goal(body)
    goal_id = own_goal if own_goal is not None else raw.get("goal_id")
    return {
        "id": str(raw["id"]),
        "title": str(raw.get("title") or ""),
        "body": goal_rules.without_card_goal(without_pins(body)),
        # The sub-goal it serves: its body's '## Goal' line, else its nearest
        # parent's (`goalInherited`; engine/goals.py card_goals).
        "goalId": int(goal_id) if goal_id is not None else None,
        "goalInherited": own_goal is None and goal_id is not None,
        # The skill versions it was made with (create's pins block), shown on the card.
        "skillPins": skill_pins(body),
        "status": str(raw.get("status") or ""),
        "member": who["name"]
        if who
        else ("" if not assignee or assignee == cofounder else assignee),
        "memberTitle": who["title"] if who else ("Co-Founder" if assignee == cofounder else ""),
        "createdAt": int(raw.get("created_at") or 0),
        "createdBy": card_members.creator(str(raw.get("created_by") or ""), members, cofounder),
        "model": str(raw.get("model_override") or ""),
        "goal": bool(raw.get("goal_mode")),
        # Waits for an answer from him (Hermes's needs_input block) — shown as ❓.
        "blockKind": str(raw.get("block_kind") or ""),
        "startedAt": int(raw["started_at"]) if raw.get("started_at") else None,
        "completedAt": int(raw["completed_at"]) if raw.get("completed_at") else None,
        # Its review stages / plan first (actions/reviews.py chip): None = none.
        "reviewChip": raw.get("review_chip"),
        # Its labels (ids of the workspace's labels): a block in its Hermes body.
        "labels": labels,
        # Hermes's own priority (a sort of the Board's views).
        "priority": int(raw.get("priority") or 0),
    }
