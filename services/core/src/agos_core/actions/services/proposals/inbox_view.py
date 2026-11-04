"""How a waiting proposal is shown to the owner: its view, the goals it serves, model choices, the count.
Must not: change a proposal.

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.proposals.proposal_states import _goals_of, _json
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.engine import proposals as rules

__all__ = [
    "count",
    "waiting",
]


def _serves(
    core: Core,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    known: dict[int, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """The goal or project a hire names (goal_id), as it is now: its title, or
    title None when it is gone."""
    goal_id = payload.get("goal_id")
    if kind != "hire" or not isinstance(goal_id, int) or isinstance(goal_id, bool):
        return None
    found = (known if known is not None else _goals_of(core, workspace_id)).get(goal_id)
    return {
        "id": goal_id,
        "title": found["title"] if found else None,
        "level": found["level"] if found else "",
        "status": found["status"] if found else "",
    }


def ask_view(
    core: Core, workspace_id: str, r: Any, goals_known: dict[int, dict[str, Any]] | None = None
) -> dict[str, Any]:
    from agos_core.actions import voice

    payload = _json(r["payload"])
    result = _json(r["result"])
    label = str(r["label"])
    if str(r["kind"]) == "goal" and rules.as_delete(payload) is not payload:
        # A delete written as status 'deleted' (before delete_* existed): shown as
        # the delete that approving it makes.
        payload = rules.as_delete(payload)
        label = rules.label("goal", payload)
    return {
        "id": int(r["id"]),
        "card": str(r["card"]),
        "kind": str(r["kind"]),
        "member": str(r["member"]),
        "memberName": voice.name_of(core, workspace_id, str(r["member"]) or None),
        "label": label,
        "payload": payload,
        "problems": [p for p in str(r["detail"]).split("; ") if p],
        "round": int(r["round"]),
        "status": str(r["status"]),
        "note": r["note"],
        "createdAt": str(r["created_at"]),
        "decidedAt": r["decided_at"],
        "canUndo": str(r["status"]) == "approved"
        and bool(result.get("member_id") or result.get("kit_for")),
        # What the owner approved when he edited the proposal first (None: as proposed).
        "editedPayload": result.get("edited") if isinstance(result.get("edited"), dict) else None,
        # A hire's goal_id read against the goals as they are now (None: no goal named).
        "serves": _serves(core, workspace_id, str(r["kind"]), payload, goals_known),
        # A waiting hire: the models the owner may pick for it (Hermes's catalog).
        "modelChoices": _model_choices(core, workspace_id, r),
    }


def _model_choices(core: Core, workspace_id: str, r: Any) -> dict[str, Any] | None:
    if str(r["kind"]) not in ("hire", "kit") or str(r["status"]) != "waiting":
        return None
    from agos_core.actions import hire_model

    return hire_model.choices(core, workspace_id)


def waiting(core: Core, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = kanban_asks.waiting_in_kinds(core.db, workspace_id, rules.KINDS, limit)
    # One read of the goals for every hire on the page (no read per card).
    known = _goals_of(core, workspace_id) if any(str(r["kind"]) == "hire" for r in rows) else {}
    return [ask_view(core, workspace_id, r, known) for r in rows]


def count(core: Core, workspace_id: str) -> int:
    """Everything waiting for him in the Inbox (one cheap read of AGOS's rows)."""
    return kanban_asks.waiting_count(core.db, workspace_id)


def ask_row(core: Core, workspace_id: str, ask_id: int) -> Any:
    row = kanban_asks.in_kinds(core.db, workspace_id, ask_id, rules.KINDS)
    if row is None:
        raise NotFoundError("This proposal")
    return row
