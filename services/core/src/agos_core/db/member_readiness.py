"""The `member_readiness` table: the owner's choices on a member's readiness items
(Not needed with his reason, Start anyway, Skip test, ...). actions/services/hire/
is its only writer.

Must not: check whether an item is there (the Hire service reads that from Hermes),
or write another table.
"""

from __future__ import annotations

import sqlite3

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = ["clear", "clear_member", "of_member", "save"]


def of_member(db: sqlite3.Connection, workspace_id: str, member: str) -> dict[str, sqlite3.Row]:
    """Item -> the owner's choice on it, for this member."""
    return {
        str(r["item"]): r
        for r in db.execute(
            "SELECT * FROM member_readiness WHERE workspace_id = ? AND member = ?",
            (workspace_id, member),
        )
    }


def save(
    db: sqlite3.Connection, workspace_id: str, member: str, item: str, choice: str, reason: str
) -> None:
    """His choice on one item (a new one replaces the old)."""
    db.execute(
        """INSERT OR REPLACE INTO member_readiness
             (workspace_id, member, item, choice, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (workspace_id, member, item, choice, reason, now()),
    )


def clear(
    db: sqlite3.Connection, workspace_id: str, member: str, item: str, choices: tuple[str, ...]
) -> None:
    """His choice on one item goes (only one of these choices)."""
    db.execute(
        sql.text(
            """DELETE FROM member_readiness WHERE workspace_id = ? AND member = ?
             AND item = ? AND choice IN ({choices})""",
            choices=sql.marks(len(choices)),
        ),
        (workspace_id, member, item, *choices),
    )


def clear_member(db: sqlite3.Connection, workspace_id: str, member: str) -> None:
    """Every choice of this member goes (a new hire of the same name)."""
    db.execute(
        "DELETE FROM member_readiness WHERE workspace_id = ? AND member = ?",
        (workspace_id, member),
    )
