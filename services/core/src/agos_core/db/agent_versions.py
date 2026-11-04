"""The `agent_versions` table: the identity history of a workspace's members and
skills (each title, summary and definition they had, and why it changed).
Written by the Co-Founder's cards (actions/services/cofounder/) and by Docs'
history (actions/docs.py), both through here.

Must not: decide when a version is kept, or write a member's Hermes profile.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["add", "find_role", "get", "history", "insert_changed", "last_id"]


def find_role(
    db: sqlite3.Connection, workspace_id: str, name: str, title: str, instructions: Any
) -> int | None:
    """The newest version with this title and these instructions (None: none)."""
    found = db.execute(
        """SELECT id FROM agent_versions
            WHERE workspace_id = ? AND name = ? AND title = ?
              AND json_extract(definition, '$.instructions') IS ?
            ORDER BY id DESC LIMIT 1""",
        (workspace_id, name, title, instructions),
    ).fetchone()
    return int(found["id"]) if found is not None else None


def insert_changed(
    db: sqlite3.Connection,
    workspace_id: str,
    name: str,
    *,
    title: str,
    summary: str,
    definition: str,
    created_at: str,
) -> int:
    """A version kept with the event "changed" at this time."""
    cur = db.execute(
        """INSERT INTO agent_versions
             (workspace_id, name, title, summary, definition, event, created_at)
           VALUES (?, ?, ?, ?, ?, 'changed', ?)""",
        (workspace_id, name, title, summary, definition, created_at),
    )
    return int(cur.lastrowid or 0)


def last_id(db: sqlite3.Connection, workspace_id: str, name: str) -> int | None:
    row = db.execute(
        "SELECT MAX(id) AS id FROM agent_versions WHERE workspace_id = ? AND name = ?",
        (workspace_id, name),
    ).fetchone()
    return int(row["id"]) if row and row["id"] is not None else None


def add(
    db: sqlite3.Connection,
    workspace_id: str,
    name: str,
    *,
    title: str,
    summary: str,
    definition: str,
    event: str,
    created_at: str,
) -> None:
    """A kept version of a member's text before it changed or went (`event`)."""
    db.execute(
        """INSERT INTO agent_versions (workspace_id, name, title, summary, definition, event, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, name, title, summary, definition, event, created_at),
    )


def history(db: sqlite3.Connection, workspace_id: str, name: str | None) -> list[sqlite3.Row]:
    """The newest 200 versions of the workspace (of one name when given)."""
    if name:
        return db.execute(
            """SELECT * FROM agent_versions WHERE workspace_id = ? AND name = ?
                ORDER BY id DESC LIMIT 200""",
            (workspace_id, name),
        ).fetchall()
    return db.execute(
        "SELECT * FROM agent_versions WHERE workspace_id = ? ORDER BY id DESC LIMIT 200",
        (workspace_id,),
    ).fetchall()


def get(db: sqlite3.Connection, workspace_id: str, version_id: int) -> sqlite3.Row | None:
    """One version, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM agent_versions WHERE id = ? AND workspace_id = ?", (version_id, workspace_id)
    ).fetchone()
    return row
