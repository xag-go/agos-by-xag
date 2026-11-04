"""Repository of `kanban_holds`: one row per Pause or Cancel of a card's subtree,
with the Hermes cards it moved and from what (so Resume releases exactly those).

Owns every read and write of kanban_holds (actions/holds.py, the Board service).
Must not: import actions or engine, or move a card (Hermes's CLI does).
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = ["get", "insert", "open_pauses", "release"]


def insert(db: sqlite3.Connection, workspace_id: str, root: str, action: str, held: str) -> int:
    """A new hold (`held`: the JSON list of the cards it moved); its id."""
    cur = db.execute(
        """INSERT INTO kanban_holds (workspace_id, root_card, action, held, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (workspace_id, root, action, held, now()),
    )
    return int(cur.lastrowid or 0)


def release(db: sqlite3.Connection, workspace_id: str, hold_id: int) -> None:
    db.execute(
        "UPDATE kanban_holds SET released_at = ? WHERE id = ? AND workspace_id = ?",
        (now(), hold_id, workspace_id),
    )


def get(db: sqlite3.Connection, workspace_id: str, hold_id: int) -> sqlite3.Row | None:
    """One hold, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_holds WHERE id = ? AND workspace_id = ?", (hold_id, workspace_id)
    ).fetchone()
    return row


def open_pauses(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """(id, root_card) of the pauses not resumed yet, oldest first."""
    return db.execute(
        """SELECT id, root_card FROM kanban_holds WHERE workspace_id = ? AND action = 'pause'
             AND released_at IS NULL ORDER BY id""",
        (workspace_id,),
    ).fetchall()
