"""The `goals` table: a workspace's plan rows (its Vision, the goals under it, the
projects under each goal). actions/services/vision/ is its only writer; the
other services read it through here.

Must not: check a rule of the plan (engine/goals.py, actions/services/vision/) or
write another table (key results: db/key_results.py).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "COLUMNS",
    "active_children",
    "clear_owner",
    "delete",
    "delete_children",
    "get",
    "insert_goal",
    "insert_project",
    "insert_vision",
    "next_position",
    "projects",
    "rows",
    "update",
    "update_vision",
    "vision_id",
]

# The columns `update` may set (its keys are column names).
COLUMNS = frozenset(
    {
        "title",
        "why",
        "owner",
        "status",
        "position",
        "due_on",
        "parent_id",
        "project_kind",
        "starts_on",
        "ends_on",
        "rhythm",
    }
)


def rows(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """Every row of the workspace's plan, in the plan's order."""
    return list(
        db.execute(
            "SELECT * FROM goals WHERE workspace_id = ? ORDER BY position, id", (workspace_id,)
        )
    )


def get(db: sqlite3.Connection, workspace_id: str, goal_id: int) -> sqlite3.Row | None:
    """One row, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM goals WHERE id = ? AND workspace_id = ?", (goal_id, workspace_id)
    ).fetchone()
    return row


def projects(db: sqlite3.Connection, workspace_id: str) -> list[tuple[int, str]]:
    """(id, title) of the workspace's projects, oldest first."""
    return [
        (int(r["id"]), str(r["title"]))
        for r in db.execute(
            "SELECT id, title FROM goals WHERE workspace_id = ? AND level = 'project' ORDER BY id",
            (workspace_id,),
        )
    ]


def vision_id(db: sqlite3.Connection, workspace_id: str) -> int | None:
    found = db.execute(
        "SELECT id FROM goals WHERE workspace_id = ? AND parent_id IS NULL", (workspace_id,)
    ).fetchone()
    return int(found["id"]) if found is not None else None


def insert_vision(
    db: sqlite3.Connection, workspace_id: str, title: str, why: str, strategy: str
) -> int:
    cur = db.execute(
        """INSERT INTO goals (workspace_id, parent_id, level, title, why, strategy,
                              created_at, updated_at)
           VALUES (?, NULL, 'vision', ?, ?, ?, ?, ?)""",
        (workspace_id, title, why, strategy, now(), now()),
    )
    return int(cur.lastrowid or 0)


def update_vision(
    db: sqlite3.Connection, goal_id: int, title: str, why: str, strategy: str
) -> None:
    db.execute(
        """UPDATE goals SET level = 'vision', title = ?, why = ?, strategy = ?,
                  updated_at = ? WHERE id = ?""",
        (title, why, strategy, now(), goal_id),
    )


def next_position(db: sqlite3.Connection, workspace_id: str, parent: int) -> int:
    last = db.execute(
        "SELECT COALESCE(MAX(position), -1) AS p FROM goals WHERE workspace_id = ? AND parent_id = ?",
        (workspace_id, parent),
    ).fetchone()
    return int(last["p"]) + 1


def active_children(db: sqlite3.Connection, workspace_id: str, parent: int) -> int:
    count = db.execute(
        "SELECT COUNT(*) AS n FROM goals WHERE workspace_id = ? AND parent_id = ? AND status = 'active'",
        (workspace_id, parent),
    ).fetchone()
    return int(count["n"])


def insert_goal(
    db: sqlite3.Connection,
    workspace_id: str,
    parent: int,
    *,
    title: str,
    why: str,
    owner: str,
    due_on: str,
    position: int,
) -> int:
    cur = db.execute(
        """INSERT INTO goals (workspace_id, parent_id, level, title, why, owner, due_on,
                              position, created_at, updated_at)
           VALUES (?, ?, 'goal', ?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, parent, title, why, owner, due_on, position, now(), now()),
    )
    return int(cur.lastrowid or 0)


def insert_project(
    db: sqlite3.Connection,
    workspace_id: str,
    parent: int,
    *,
    title: str,
    why: str,
    owner: str,
    project_kind: str,
    starts_on: str,
    ends_on: str,
    rhythm: str,
    position: int,
) -> int:
    cur = db.execute(
        """INSERT INTO goals (workspace_id, parent_id, level, title, why, owner,
                              project_kind, starts_on, ends_on, rhythm, position,
                              created_at, updated_at)
           VALUES (?, ?, 'project', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            parent,
            title,
            why,
            owner,
            project_kind,
            starts_on,
            ends_on,
            rhythm,
            position,
            now(),
            now(),
        ),
    )
    return int(cur.lastrowid or 0)


def update(db: sqlite3.Connection, goal_id: int, sets: dict[str, Any]) -> None:
    """Set these columns (names from COLUMNS) and the row's change time."""
    unknown = set(sets) - COLUMNS
    if unknown:
        raise ValueError(f"not a goals column: {sorted(unknown)}")
    db.execute(
        sql.text(
            "UPDATE goals SET {sets}, updated_at = ? WHERE id = ?",
            sets=sql.assignments(sets, COLUMNS),
        ),
        (*sets.values(), now(), goal_id),
    )


def delete_children(db: sqlite3.Connection, workspace_id: str, parent: int) -> None:
    db.execute("DELETE FROM goals WHERE workspace_id = ? AND parent_id = ?", (workspace_id, parent))


def delete(db: sqlite3.Connection, workspace_id: str, goal_id: int) -> None:
    db.execute("DELETE FROM goals WHERE id = ? AND workspace_id = ?", (goal_id, workspace_id))


def clear_owner(db: sqlite3.Connection, workspace_id: str, name: str) -> int:
    """Rows this member owned have no owner now; how many changed."""
    cur = db.execute(
        "UPDATE goals SET owner = '', updated_at = ? WHERE workspace_id = ? AND owner = ?",
        (now(), workspace_id, name),
    )
    return int(cur.rowcount)
