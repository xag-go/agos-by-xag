"""The `skill_requests` table: a member's request for a skill from outside (install,
scan, test, the owner's approval when it has scripts). actions/skill_requests.py
is its only writer.

Must not: install, scan or test a skill (the Library service does), or write
another table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "COLUMNS",
    "count_since",
    "get",
    "insert",
    "of_member",
    "open_for",
    "recent",
    "runs_of",
    "testing",
    "update",
]

# The columns `update` may set (its keys are column names).
COLUMNS = frozenset(
    {
        "name",
        "status",
        "item_id",
        "verdict",
        "scan",
        "scripts",
        "forced",
        "runs",
        "ask_id",
        "note",
    }
)


def count_since(db: sqlite3.Connection, workspace_id: str, since: str) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM skill_requests WHERE workspace_id = ? AND created_at >= ?",
        (workspace_id, since),
    ).fetchone()
    return int(row["n"]) if row else 0


def get(db: sqlite3.Connection, workspace_id: str, request_id: int) -> sqlite3.Row | None:
    """One request, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM skill_requests WHERE id = ? AND workspace_id = ?",
        (request_id, workspace_id),
    ).fetchone()
    return row


def update(db: sqlite3.Connection, request_id: int, fields: dict[str, Any]) -> None:
    """Set these columns (names from COLUMNS) and the row's change time."""
    unknown = set(fields) - COLUMNS
    if unknown:
        raise ValueError(f"not a skill_requests column: {sorted(unknown)}")
    db.execute(
        sql.text(
            "UPDATE skill_requests SET {sets}, updated_at = ? WHERE id = ?",
            sets=sql.assignments(fields, COLUMNS),
        ),
        (*fields.values(), now(), request_id),
    )


def recent(db: sqlite3.Connection, workspace_id: str, limit: int) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT * FROM skill_requests WHERE workspace_id = ? ORDER BY id DESC LIMIT ?",
            (workspace_id, limit),
        )
    )


def of_member(db: sqlite3.Connection, workspace_id: str, member: str) -> list[sqlite3.Row]:
    """A member's ten newest requests."""
    return db.execute(
        """SELECT * FROM skill_requests WHERE workspace_id = ? AND member = ?
           ORDER BY id DESC LIMIT 10""",
        (workspace_id, member),
    ).fetchall()


def open_for(
    db: sqlite3.Connection, workspace_id: str, source: str, statuses: tuple[str, ...]
) -> int | None:
    """A request for this source still in one of these statuses (None: none)."""
    busy = db.execute(
        sql.text(
            """SELECT id FROM skill_requests WHERE workspace_id = ? AND source = ?
            AND status IN ({statuses})""",
            statuses=sql.marks(len(statuses)),
        ),
        (workspace_id, source, *statuses),
    ).fetchone()
    return int(busy["id"]) if busy is not None else None


def insert(
    db: sqlite3.Connection,
    workspace_id: str,
    *,
    member: str,
    source: str,
    reason: str,
    tests: str,
    criteria: str,
    stamp: str,
) -> int:
    """A new request, installing from now."""
    cur = db.execute(
        """INSERT INTO skill_requests (workspace_id, member, source, reason, tests,
             criteria, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'installing', ?, ?)""",
        (workspace_id, member, source, reason, tests, criteria, stamp, stamp),
    )
    return int(cur.lastrowid or 0)


def testing(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM skill_requests WHERE workspace_id = ? AND status = 'testing'",
        (workspace_id,),
    ).fetchall()


def runs_of(db: sqlite3.Connection, workspace_id: str) -> list[Any]:
    """Every request's planned test runs (JSON text each) in the workspace."""
    return [
        raw
        for (raw,) in db.execute(
            "SELECT runs FROM skill_requests WHERE workspace_id = ?", (workspace_id,)
        )
    ]
