"""The `cofounder_actions` table: the Co-Founder's action cards (what it was asked to
do in a chat, its status, the result its Undo needs). actions/services/cofounder/
is its only writer.

Must not: run or undo an action (actions/services/cofounder/dispatch.py does), or
know what a payload means.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "COLUMNS",
    "drop_sealed",
    "get",
    "in_workspace",
    "insert",
    "of_turn",
    "set_fields",
    "set_result",
    "with_results",
]

# The columns `set_fields` may set (its keys are column names).
COLUMNS = frozenset({"status", "error", "result", "title", "decided_at"})


def insert(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_id: int,
    turn_id: int,
    *,
    action: str,
    title: str,
    payload: str,
) -> int:
    cur = db.execute(
        """INSERT INTO cofounder_actions
             (workspace_id, chat_id, turn_id, action, title, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, chat_id, turn_id, action, title, payload, now()),
    )
    return int(cur.lastrowid or 0)


def of_turn(db: sqlite3.Connection, turn_id: int) -> list[sqlite3.Row]:
    return list(
        db.execute("SELECT * FROM cofounder_actions WHERE turn_id = ? ORDER BY id", (turn_id,))
    )


def get(db: sqlite3.Connection, action_id: int) -> sqlite3.Row | None:
    """A card by its id alone (its caller made it in this workspace's chat)."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM cofounder_actions WHERE id = ?", (action_id,)
    ).fetchone()
    return row


def in_workspace(db: sqlite3.Connection, workspace_id: str, action_id: int) -> sqlite3.Row | None:
    """A card, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM cofounder_actions WHERE id = ? AND workspace_id = ?",
        (action_id, workspace_id),
    ).fetchone()
    return row


def set_fields(db: sqlite3.Connection, action_id: int, fields: dict[str, Any]) -> None:
    """Set these columns (names from COLUMNS)."""
    unknown = set(fields) - COLUMNS
    if unknown:
        raise ValueError(f"not a cofounder_actions column: {sorted(unknown)}")
    db.execute(
        sql.text(
            "UPDATE cofounder_actions SET {sets} WHERE id = ?",
            sets=sql.assignments(fields, COLUMNS),
        ),
        (*fields.values(), action_id),
    )


def drop_sealed(db: sqlite3.Connection, action_id: int) -> None:
    """A settled card's sealed pool key goes: the payload's once it is done or
    declined, the result's (a removed key kept for its Undo) once it is undone."""
    db.execute(
        """UPDATE cofounder_actions SET payload = json_remove(payload, '$.key_sealed')
            WHERE id = ? AND status IN ('done', 'rejected', 'undone')
              AND json_valid(payload) AND json_extract(payload, '$.key_sealed') IS NOT NULL""",
        (action_id,),
    )
    db.execute(
        """UPDATE cofounder_actions SET result = json_remove(result, '$.sealed')
            WHERE id = ? AND status = 'undone'
              AND json_valid(result) AND json_extract(result, '$.sealed') IS NOT NULL""",
        (action_id,),
    )


def with_results(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace's cards that keep a JSON result (AGOS's own upkeep only)."""
    return db.execute(
        """SELECT id, workspace_id, action, payload, result, created_at FROM cofounder_actions
            WHERE result IS NOT NULL AND json_valid(result) ORDER BY id"""
    ).fetchall()


def set_result(db: sqlite3.Connection, action_id: int, result: str) -> None:
    db.execute("UPDATE cofounder_actions SET result = ? WHERE id = ?", (result, action_id))
