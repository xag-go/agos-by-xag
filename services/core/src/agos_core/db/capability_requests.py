"""The `capability_requests` table: what an agent asked to have turned on or off (a
skill, an MCP server, an app) from a chat, waiting for the owner's yes, and what
became of it. actions/capabilities.py is its only writer.

Must not: switch a capability (the Library and Connector services do), or write
another table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "COLUMNS",
    "connecting_for_app",
    "get",
    "insert",
    "of_turn",
    "pending",
    "set_fields",
]

# The columns `set_fields` may set (its keys are column names).
COLUMNS = frozenset({"status", "error", "flow_id", "decided_at"})


def pending(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """(kind, name, turn_on) of the workspace's requests not settled yet."""
    return list(
        db.execute(
            """SELECT kind, name, turn_on FROM capability_requests
               WHERE workspace_id = ? AND status IN ('proposed','connecting')""",
            (workspace_id,),
        )
    )


def insert(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_id: int,
    turn_id: int,
    *,
    kind: str,
    name: str,
    title: str,
    turn_on: bool,
    reason: str,
) -> int:
    cur = db.execute(
        """INSERT INTO capability_requests
             (workspace_id, chat_id, turn_id, kind, name, title, turn_on, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, chat_id, turn_id, kind, name, title, int(turn_on), reason, now()),
    )
    return int(cur.lastrowid or 0)


def of_turn(db: sqlite3.Connection, turn_id: int) -> list[sqlite3.Row]:
    return list(
        db.execute("SELECT * FROM capability_requests WHERE turn_id = ? ORDER BY id", (turn_id,))
    )


def get(db: sqlite3.Connection, workspace_id: str, request_id: int) -> sqlite3.Row | None:
    """One request, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM capability_requests WHERE id = ? AND workspace_id = ?",
        (request_id, workspace_id),
    ).fetchone()
    return row


def set_fields(db: sqlite3.Connection, request_id: int, fields: dict[str, Any]) -> None:
    """Set these columns (names from COLUMNS)."""
    unknown = set(fields) - COLUMNS
    if unknown:
        raise ValueError(f"not a capability_requests column: {sorted(unknown)}")
    db.execute(
        sql.text(
            "UPDATE capability_requests SET {sets} WHERE id = ?",
            sets=sql.assignments(fields, COLUMNS),
        ),
        (*fields.values(), request_id),
    )


def connecting_for_app(db: sqlite3.Connection, workspace_id: str, app: str) -> list[sqlite3.Row]:
    """The workspace's requests for this app that wait on its login."""
    return db.execute(
        """SELECT * FROM capability_requests
           WHERE workspace_id = ? AND kind = 'app' AND name = ? AND status = 'connecting'""",
        (workspace_id, app),
    ).fetchall()
