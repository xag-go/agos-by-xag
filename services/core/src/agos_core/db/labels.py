"""Repository of `labels`: a workspace's card labels (a name, a colour, the folder
that groups them). Which cards carry a label is in each card's Hermes body.

Owns every read and write of labels (actions/labels.py, the Board service).
Must not: import actions or engine, or touch a card.
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = ["delete", "insert", "move_folder", "of_workspace", "update"]


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The workspace's labels, by folder then name."""
    return list(
        db.execute(
            "SELECT * FROM labels WHERE workspace_id = ? ORDER BY folder, name COLLATE NOCASE",
            (workspace_id,),
        )
    )


def insert(db: sqlite3.Connection, workspace_id: str, name: str, color: str, folder: str) -> int:
    """A new label; its id."""
    cur = db.execute(
        """INSERT INTO labels (workspace_id, name, color, folder, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (workspace_id, name, color, folder, now()),
    )
    return int(cur.lastrowid or 0)


def update(
    db: sqlite3.Connection, workspace_id: str, label_id: int, name: str, color: str, folder: str
) -> None:
    db.execute(
        "UPDATE labels SET name = ?, color = ?, folder = ? WHERE id = ? AND workspace_id = ?",
        (name, color, folder, label_id, workspace_id),
    )


def move_folder(db: sqlite3.Connection, workspace_id: str, old: str, new: str) -> None:
    """Every label of folder `old` goes into `new` ('' = no folder)."""
    db.execute(
        "UPDATE labels SET folder = ? WHERE workspace_id = ? AND folder = ?",
        (new, workspace_id, old),
    )


def delete(db: sqlite3.Connection, workspace_id: str, label_id: int) -> None:
    db.execute("DELETE FROM labels WHERE id = ? AND workspace_id = ?", (label_id, workspace_id))
