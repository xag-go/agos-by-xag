"""Subtree holds: Pause / Resume / Cancel a card and everything under it.

The subtree is Hermes's own tree (task_links parent -> child, read from the board
database, read only). Every move is Hermes's own Kanban operation, through its CLI:
- Pause: each card of the subtree that the dispatcher could still start (todo,
  ready) is parked with `kanban schedule` (Hermes's "waiting on time, not a human"
  status: not dispatchable until unblocked, hermes_cli/kanban_db.py schedule_task).
  A blocked card is already held by its block (and `schedule` would lose that
  block: unblock lands it in ready), a running one finishes its run (Hermes has no
  "hold after the run" and reclaiming kills the worker), done ones are done.
- Resume: `kanban unblock` for each card the pause parked that is STILL scheduled
  — exactly what the pause held and nothing the owner moved meanwhile.
- Cancel: `kanban archive` for each card of the subtree not done or archived (a
  running one's worker is terminated by Hermes's archive_task). No Undo: Hermes's
  CLI has no unarchive; the UI asks before.
One hold row (kanban_holds) per action records the cards it moved and from what.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import kanban_cli
from agos_core.context import Core
from agos_core.db import kanban_holds
from agos_core.db.connection import transaction
from agos_core.hermes_gateway import kanban_rows

log = logging.getLogger(__name__)

PAUSABLE = ("todo", "ready")
TERMINAL = ("done", "archived")
PAUSE_REASON = "Paused by the owner (with card {root})."


def subtree(core: Core, workspace_id: str, root: str) -> dict[str, str]:
    """{card: status} of `root` and every descendant (Hermes's task_links), from the
    board database (read only). NotFoundError when the root isn't on the board."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        raise ActionError("Hermes isn't set up yet.")
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        raise NotFoundError("This card")
    try:
        with kanban_rows.opened(board_db) as board:
            statuses = {str(i): str(s or "") for i, s in board.statuses()}
            children: dict[str, list[str]] = {}
            for parent, child in board.links():
                children.setdefault(str(parent), []).append(str(child))
    except sqlite3.Error as error:
        raise ActionError("Hermes's board can't be read right now.") from error
    if root not in statuses:
        raise NotFoundError("This card")
    found: dict[str, str] = {}
    queue = [root]
    while queue:
        card = queue.pop()
        if card in found:
            continue
        found[card] = statuses.get(card, "")
        queue.extend(children.get(card, []))
    return found


def _cli(core: Core, workspace_id: str, *args: str) -> bool:
    """`hermes kanban <args>`; False when Hermes refused (kanban_cli.tried)."""
    return kanban_cli.tried(core, workspace_id, *args)


def pause(core: Core, workspace_id: str, root: str) -> dict[str, Any]:
    tree = subtree(core, workspace_id, root)
    held = []
    for card, status in tree.items():
        if status in PAUSABLE and _cli(
            core, workspace_id, "schedule", card, PAUSE_REASON.format(root=root)
        ):
            held.append({"card": card, "was": status})
    return _record(core, workspace_id, root, "pause", held, tree)


def cancel(core: Core, workspace_id: str, root: str) -> dict[str, Any]:
    tree = subtree(core, workspace_id, root)
    held = []
    # Children first: an archived parent would promote its children for a moment.
    for card, status in reversed(list(tree.items())):
        if status not in TERMINAL and _cli(core, workspace_id, "archive", card):
            held.append({"card": card, "was": status})
    return _record(core, workspace_id, root, "cancel", held, tree)


def _record(
    core: Core,
    workspace_id: str,
    root: str,
    action: str,
    held: list[dict[str, str]],
    tree: dict[str, str],
) -> dict[str, Any]:
    with transaction(core.db):
        hold_id = kanban_holds.insert(core.db, workspace_id, root, action, json.dumps(held))
    return {
        **_view(core, workspace_id, hold_id),
        "left": sorted(
            c for c, s in tree.items() if s not in TERMINAL and c not in {h["card"] for h in held}
        ),
    }


def resume(core: Core, workspace_id: str, hold_id: int) -> dict[str, Any]:
    row = _row(core, workspace_id, hold_id)
    if str(row["action"]) != "pause":
        raise ActionError("Only a pause is resumed.", 409)
    if row["released_at"]:
        return _view(core, workspace_id, hold_id)  # resumed already
    tree = subtree(core, workspace_id, str(row["root_card"]))
    released = []
    for item in json.loads(str(row["held"]) or "[]"):
        card = str(item.get("card") or "")
        if tree.get(card) == "scheduled" and _cli(core, workspace_id, "unblock", card):
            released.append(card)
    with transaction(core.db):
        kanban_holds.release(core.db, workspace_id, hold_id)
    return {**_view(core, workspace_id, hold_id), "released": released}


def _row(core: Core, workspace_id: str, hold_id: int) -> Any:
    row = kanban_holds.get(core.db, workspace_id, hold_id)
    if row is None:
        raise NotFoundError("This hold")
    return row


def _view(core: Core, workspace_id: str, hold_id: int) -> dict[str, Any]:
    row = _row(core, workspace_id, hold_id)
    return {
        "id": int(row["id"]),
        "card": str(row["root_card"]),
        "action": str(row["action"]),
        "held": json.loads(str(row["held"]) or "[]"),
        "createdAt": str(row["created_at"]),
        "releasedAt": row["released_at"],
    }


def open_holds(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    """The pauses not yet resumed, by root card (the Board's Resume button)."""
    return {
        str(r["root_card"]): _view(core, workspace_id, int(r["id"]))
        for r in kanban_holds.open_pauses(core.db, workspace_id)
    }
