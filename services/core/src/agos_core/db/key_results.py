"""The `key_results` table: the numbers that measure a workspace's goals (start,
current, target). actions/services/vision/ is its only writer.

Must not: check a rule of the plan (engine/goals.py, actions/services/vision/) or
write another table (the goals: db/goals.py).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = ["COLUMNS", "count_for", "delete", "get", "insert", "next_position", "rows", "update"]

# The columns `update` may set (its keys are column names).
COLUMNS = frozenset(
    {"title", "start_value", "current", "source", "target", "unit", "due_on", "position"}
)


def rows(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT * FROM key_results WHERE workspace_id = ? ORDER BY position, id",
            (workspace_id,),
        )
    )


def get(db: sqlite3.Connection, workspace_id: str, kr_id: int) -> sqlite3.Row | None:
    """One key result, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM key_results WHERE id = ? AND workspace_id = ?", (kr_id, workspace_id)
    ).fetchone()
    return row


def count_for(db: sqlite3.Connection, workspace_id: str, goal_id: int) -> int:
    have = db.execute(
        "SELECT COUNT(*) AS n FROM key_results WHERE workspace_id = ? AND goal_id = ?",
        (workspace_id, goal_id),
    ).fetchone()
    return int(have["n"])


def next_position(db: sqlite3.Connection, goal_id: int) -> int:
    last = db.execute(
        "SELECT COALESCE(MAX(position), -1) AS p FROM key_results WHERE goal_id = ?",
        (goal_id,),
    ).fetchone()
    return int(last["p"]) + 1


def insert(
    db: sqlite3.Connection,
    workspace_id: str,
    goal_id: int,
    *,
    title: str,
    start_value: float,
    current: float,
    target: float | None,
    unit: str,
    due_on: str,
    position: int,
) -> int:
    cur = db.execute(
        """INSERT INTO key_results (workspace_id, goal_id, title, start_value, current,
                                    target, unit, due_on, position, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            goal_id,
            title,
            start_value,
            current,
            target,
            unit,
            due_on,
            position,
            now(),
            now(),
        ),
    )
    return int(cur.lastrowid or 0)


def update(db: sqlite3.Connection, kr_id: int, sets: dict[str, Any]) -> None:
    """Set these columns (names from COLUMNS) and the row's change time."""
    unknown = set(sets) - COLUMNS
    if unknown:
        raise ValueError(f"not a key_results column: {sorted(unknown)}")
    db.execute(
        sql.text(
            "UPDATE key_results SET {sets}, updated_at = ? WHERE id = ?",
            sets=sql.assignments(sets, COLUMNS),
        ),
        (*sets.values(), now(), kr_id),
    )


def delete(db: sqlite3.Connection, workspace_id: str, kr_id: int) -> None:
    db.execute("DELETE FROM key_results WHERE id = ? AND workspace_id = ?", (kr_id, workspace_id))
