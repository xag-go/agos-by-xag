"""The kanban_watchdogs table: a "Watch this tree" on a Hermes card (actions/watchdogs.py
is its one caller).

Owns: every query on kanban_watchdogs: a watch by id or by its root card, the
workspace's watches, its Hermes cron job, and what each wake saw (the stop
fingerprint, how many wakes acted, when it was escalated to the owner).

Must not: decide anything (actions/watchdogs.py does), or write another table.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "acted",
    "add",
    "by_card",
    "by_id",
    "every_root",
    "of_workspace",
    "remove",
    "roots",
    "seen",
    "set_job",
]


def by_id(db: sqlite3.Connection, workspace_id: str, watchdog_id: int) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_watchdogs WHERE id = ? AND workspace_id = ?",
        (watchdog_id, workspace_id),
    ).fetchone()
    return found


def by_card(db: sqlite3.Connection, workspace_id: str, root_card: str) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_watchdogs WHERE workspace_id = ? AND root_card = ?",
        (workspace_id, root_card),
    ).fetchone()
    return found


def roots(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The workspace's watches (id, root_card)."""
    return db.execute(
        "SELECT id, root_card FROM kanban_watchdogs WHERE workspace_id = ?", (workspace_id,)
    ).fetchall()


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM kanban_watchdogs WHERE workspace_id = ? ORDER BY id", (workspace_id,)
    ).fetchall()


def every_root(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace's watches (workspace_id, root_card)."""
    return db.execute(
        "SELECT workspace_id, root_card FROM kanban_watchdogs ORDER BY workspace_id"
    ).fetchall()


def add(db: sqlite3.Connection, workspace_id: str, root_card: str, at: str) -> None:
    db.execute(
        """INSERT INTO kanban_watchdogs (workspace_id, root_card, created_at)
           VALUES (?, ?, ?)""",
        (workspace_id, root_card, at),
    )


def remove(db: sqlite3.Connection, watchdog_id: int) -> None:
    db.execute("DELETE FROM kanban_watchdogs WHERE id = ?", (watchdog_id,))


def set_job(db: sqlite3.Connection, watchdog_id: int, job_id: str) -> None:
    db.execute("UPDATE kanban_watchdogs SET hermes_job_id = ? WHERE id = ?", (job_id, watchdog_id))


def seen(db: sqlite3.Connection, watchdog_id: int, at: str) -> None:
    """A wake that found nothing new."""
    db.execute("UPDATE kanban_watchdogs SET observed_at = ? WHERE id = ?", (at, watchdog_id))


def acted(
    db: sqlite3.Connection,
    watchdog_id: int,
    *,
    fingerprint: str,
    acts: int,
    at: str,
    escalated: str | None,
) -> None:
    """A wake that acted on a new stop (escalated: when the owner got the root card)."""
    db.execute(
        """UPDATE kanban_watchdogs SET fingerprint = ?, acts = ?, observed_at = ?, acted_at = ?,
             escalated_at = COALESCE(?, escalated_at) WHERE id = ?""",
        (fingerprint, acts, at, at, escalated, watchdog_id),
    )
