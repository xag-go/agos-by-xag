"""The `connector_notes` table: the owner's notes on a workspace's skill or MCP
server (shown in AGOS only). actions/services/library/ and its once-moves are its
writers.

Must not: hold an agent's notes (those are its team row's), or write another table.
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = ["move_item", "notes", "save"]


def notes(db: sqlite3.Connection, workspace_id: str) -> dict[int, str]:
    """Item id -> its notes, in this workspace."""
    return {
        int(r["item_id"]): str(r["notes"])
        for r in db.execute(
            "SELECT item_id, notes FROM connector_notes WHERE workspace_id = ?", (workspace_id,)
        )
    }


def save(db: sqlite3.Connection, workspace_id: str, item_id: int, text: str) -> None:
    db.execute(
        """INSERT INTO connector_notes (workspace_id, item_id, notes, updated_at)
           VALUES (?, ?, ?, ?) ON CONFLICT (workspace_id, item_id) DO UPDATE
           SET notes = excluded.notes, updated_at = excluded.updated_at""",
        (workspace_id, item_id, text, now()),
    )


def move_item(db: sqlite3.Connection, workspace_id: str, old_id: int, new_id: int) -> None:
    """The notes follow an item that got a new id in this workspace."""
    db.execute(
        "UPDATE connector_notes SET item_id = ? WHERE workspace_id = ? AND item_id = ?",
        (new_id, workspace_id, old_id),
    )
