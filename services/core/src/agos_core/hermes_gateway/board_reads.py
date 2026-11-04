"""The SQL of AGOS's read-only queries of a workspace's Hermes Kanban board database
(Hermes's own `tasks`, `task_links` and `task_comments` tables, hermes_cli/kanban_db.py),
run on a connection the caller opened with `hermes_db.connect_ro`.

Owns those queries (the Founder's cards, the Vision plan's board, the skill growth's
review notes). Must not: write, open the database itself, or decide what a row
means (its caller does). Errors are sqlite3.Error, for the caller to handle.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection
from typing import Any

from agos_core.db import sql

__all__ = [
    "PLAN_COLUMNS",
    "assigned",
    "card_skills",
    "links",
    "links_of",
    "plan_tasks",
    "review_comments",
]

# Rows are plain tuples (connect_ro sets no row factory), in the SELECT's order.

# The task columns the Vision plan reads (an older board lacks some: NULL then).
PLAN_COLUMNS = (
    "id",
    "status",
    "body",
    "title",
    "assignee",
    "idempotency_key",
    "priority",
    "created_at",
)


def assigned(db: sqlite3.Connection, assignee: str) -> list[Any]:
    """(id, title, body, status, created_at, completed_at, created_by, result) of the
    cards assigned to `assignee`, archived ones left out."""
    return db.execute(
        """SELECT id, title, body, status, created_at, completed_at, created_by, result
             FROM tasks WHERE assignee = ? AND status != 'archived'""",
        (assignee,),
    ).fetchall()


def links_of(db: sqlite3.Connection, ids: Collection[str]) -> list[Any]:
    """(parent_id, child_id) of every link touching one of `ids` ([] for none)."""
    if not ids:
        return []
    marks = sql.marks(len(ids))
    return db.execute(
        sql.text(
            """SELECT parent_id, child_id FROM task_links
                 WHERE parent_id IN ({marks}) OR child_id IN ({marks})""",
            marks=marks,
        ),
        (*ids, *ids),
    ).fetchall()


def links(db: sqlite3.Connection) -> list[Any]:
    """(parent_id, child_id) of every link on the board."""
    return db.execute("SELECT parent_id, child_id FROM task_links").fetchall()


def plan_tasks(db: sqlite3.Connection) -> list[Any]:
    """Every card's PLAN_COLUMNS, in that order (NULL for a column the board lacks)."""
    have = {str(r[1]) for r in db.execute("PRAGMA table_info(tasks)")}
    picked = sql.or_null(PLAN_COLUMNS, have, PLAN_COLUMNS)
    return db.execute(sql.text("SELECT {picked} FROM tasks", picked=picked)).fetchall()


def card_skills(db: sqlite3.Connection, card: str) -> str | None:
    """The card's `skills` (JSON text as Hermes keeps it); None when it has none."""
    row = db.execute("SELECT skills FROM tasks WHERE id = ?", (card,)).fetchone()
    return str(row[0]) if row and row[0] else None


def review_comments(db: sqlite3.Connection, since: int) -> list[Any]:
    """(task_id, body) of the review-mark comments made at `since` (epoch s) or later."""
    return db.execute(
        """SELECT task_id, body FROM task_comments
           WHERE created_at >= ? AND body LIKE '%[agos-review %' ORDER BY id""",
        (since,),
    ).fetchall()
