"""The Co-Founder's action cards: storing one, its view, its state, the kinds that have an Undo.
Must not: run an action (dispatch does).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.cofounder_detail import detail as _detail
from agos_core.actions.services.cofounder import base_ops
from agos_core.context import Core
from agos_core.db import cofounder_actions as cards_repo
from agos_core.db.records import CofounderActionView
from agos_core.db.rows import load_json, now
from agos_core.engine import cofounder_actions as rules
from agos_core.engine import cofounder_parity as parity

__all__ = [
    "of_turn",
    "save",
]

# ---- storing --------------------------------------------------------------------------


def save(
    core: Core, workspace_id: str, chat_id: int, turn_id: int, actions: list[rules.Action]
) -> list[int]:
    ids = []
    for action in actions[: rules.MAX_PER_TURN]:
        if action.fields.get("key") and action.do == "add_pool_key":
            # A key the owner gave in the chat is stored only sealed (for its card).
            from agos_core.actions import cofounder_hermes

            fields = {k: v for k, v in action.fields.items() if k != "key"}
            fields["key_sealed"] = cofounder_hermes.seal(core, str(action.fields["key"]))
            action = rules.Action(action.do, fields)
        ids.append(
            cards_repo.insert(
                core.db,
                workspace_id,
                chat_id,
                turn_id,
                action=action.do,
                title=rules.title_of(action),
                payload=json.dumps(action.fields),
            )
        )
    return ids


def _view(r: Any) -> CofounderActionView:
    from agos_core.actions import cofounder_hermes

    payload = load_json(r["payload"]) or {}
    detail = _detail(payload)
    founder = ("assign_founder", "founder_done")
    shown_said = (*cofounder_hermes.REPORTS, *cofounder_hermes.DOES, *founder)
    if r["status"] == "done" and r["action"] in shown_said:
        result = load_json(r["result"]) or {}
        detail = str(result.get("report") or result.get("said") or result.get("now") or "")
    elif (
        r["status"] == "done" and r["action"] in parity.KINDS and r["action"] not in base_ops.NAMES
    ):
        # A base kind (create_automation...) keeps its own detail ("Who does what"):
        # its report answers the Co-Founder, the owner's card stays as it was.
        detail = str((load_json(r["result"]) or {}).get("report") or detail)
    if r["status"] == "done" and r["action"] in rules.HIRES:
        result = load_json(r["result"]) or {}
        if result.get("proposed"):
            detail = (
                f"Proposed on card {result.get('card')}: approve, revise or reject it in "
                "the Inbox. Nothing is created before your Approve."
            )
    if payload.get("held_after"):  # read vs act (actions/owner_gate.py)
        detail = f"⚠️ This came after reading {payload['held_after']}.\n{detail}".strip()
    return CofounderActionView(
        id=r["id"],
        action=r["action"],
        title=r["title"],
        detail=detail,
        status=r["status"],
        error=r["error"],
        can_undo=r["status"] == "done" and r["action"] in _UNDO and not _proposed(r),
    )


def _proposed(r: Any) -> bool:
    """A hire the Co-Founder only proposed (every hire now): decided in the Inbox,
    not undone."""
    if r["action"] not in rules.HIRES or not r["result"]:
        return False
    return bool((load_json(r["result"]) or {}).get("proposed"))


def of_turn(db: Any, turn_id: int) -> list[CofounderActionView]:
    return [_view(r) for r in cards_repo.of_turn(db, turn_id)]


def _row(core: Core, workspace_id: str, action_id: int) -> Any:
    from agos_core.actions.errors import NotFoundError

    row = cards_repo.in_workspace(core.db, workspace_id, action_id)
    if row is None:
        raise NotFoundError("This action")
    return row


def _set(core: Core, action_id: int, **fields: Any) -> None:
    fields.setdefault("decided_at", now())
    cards_repo.set_fields(core.db, action_id, fields)
    if fields.get("status") in _SETTLED:
        _drop_sealed(core, action_id)


# A sealed pool key is kept only while AGOS still needs it: an "add pool key" card's
# (payload.key_sealed) until it is done or declined, a removed key's (result.sealed,
# for its Undo) until the Undo put it back. Then Hermes's managed .env holds it (or it
# was never added), and AGOS keeps no copy. (Migration 121 cleared the old ones.)
_SETTLED = ("done", "rejected", "undone")


def _drop_sealed(core: Core, action_id: int) -> None:
    cards_repo.drop_sealed(core.db, action_id)


_KINDS = ("skill", "agent", "mcp")


def _more_undo() -> frozenset[str]:
    from agos_core.actions import cofounder_more

    return frozenset(cofounder_more.UNDOES)


# The kinds with an Undo: a bundle, and every declared kind whose gate gives its card one
# (ops/specs; actions/cofounder_more.py lists their undo).
_UNDO = {rules.BUNDLE, *_more_undo()}
