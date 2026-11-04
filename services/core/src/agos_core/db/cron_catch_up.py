"""The cron_catch_up table: what AGOS saw of each Hermes cron job for the catch-up of
missed runs (actions/catch_up.py is its one caller).

Owns: every query on cron_catch_up (a job's on/off change, the missed slot it caught
up or skipped, the catch-ups asked of Hermes), plus the two reads the catch-up needs
to know when to look again (the workspaces to check, each automation's choice).

Must not: decide anything (actions/catch_up.py does), or write another table.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "asked",
    "choices",
    "clear_state",
    "forget",
    "mark_asked",
    "missed",
    "of_workspace",
    "row",
    "turned_off",
    "turned_off_first",
    "turned_on",
    "waiting",
    "workspaces",
]


def row(db: sqlite3.Connection, workspace_id: str, job_id: str) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM cron_catch_up WHERE workspace_id = ? AND job_id = ?",
        (workspace_id, job_id),
    ).fetchone()
    return found


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM cron_catch_up WHERE workspace_id = ?", (workspace_id,)
    ).fetchall()


def asked(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The catch-ups AGOS asked Hermes for (job_id, asked_at, missed_at)."""
    return db.execute(
        "SELECT job_id, asked_at, missed_at FROM cron_catch_up "
        "WHERE workspace_id = ? AND state = 'asked' AND asked_at IS NOT NULL",
        (workspace_id,),
    ).fetchall()


def waiting(db: sqlite3.Connection, workspace_id: str) -> bool:
    """A catch-up waits for the workspace's gateway."""
    return (
        db.execute(
            "SELECT 1 FROM cron_catch_up WHERE workspace_id = ? AND state = 'waiting'",
            (workspace_id,),
        ).fetchone()
        is not None
    )


def forget(db: sqlite3.Connection, workspace_id: str, job_id: str) -> None:
    db.execute(
        "DELETE FROM cron_catch_up WHERE workspace_id = ? AND job_id = ?", (workspace_id, job_id)
    )


def turned_off_first(db: sqlite3.Connection, workspace_id: str, job_id: str, at: str) -> None:
    """A job AGOS had no row for is off: since `at`."""
    db.execute(
        "INSERT INTO cron_catch_up (workspace_id, job_id, off_since) VALUES (?, ?, ?)",
        (workspace_id, job_id, at),
    )


def turned_on(db: sqlite3.Connection, workspace_id: str, job_id: str, at: str) -> None:
    db.execute(
        "UPDATE cron_catch_up SET off_since = NULL, on_since = ?, "
        "state = CASE WHEN state = 'waiting' THEN NULL ELSE state END "
        "WHERE workspace_id = ? AND job_id = ?",
        (at, workspace_id, job_id),
    )


def turned_off(db: sqlite3.Connection, workspace_id: str, job_id: str, at: str) -> None:
    db.execute(
        "UPDATE cron_catch_up SET off_since = ?, "
        "state = CASE WHEN state = 'waiting' THEN NULL ELSE state END "
        "WHERE workspace_id = ? AND job_id = ?",
        (at, workspace_id, job_id),
    )


def missed(db: sqlite3.Connection, workspace_id: str, job_id: str, at: str, state: str) -> None:
    """The missed slot `at` and what happens to it (caught up, waiting, skipped)."""
    db.execute(
        "INSERT INTO cron_catch_up (workspace_id, job_id, missed_at, state) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (workspace_id, job_id) DO UPDATE SET missed_at = excluded.missed_at, "
        "state = excluded.state, asked_at = NULL",
        (workspace_id, job_id, at, state),
    )


def clear_state(db: sqlite3.Connection, workspace_id: str, job_id: str) -> None:
    db.execute(
        "UPDATE cron_catch_up SET state = NULL WHERE workspace_id = ? AND job_id = ?",
        (workspace_id, job_id),
    )


def mark_asked(db: sqlite3.Connection, workspace_id: str, job_id: str, at: str) -> None:
    db.execute(
        "UPDATE cron_catch_up SET state = 'asked', asked_at = ? WHERE workspace_id = ? AND job_id = ?",
        (at, workspace_id, job_id),
    )


def workspaces(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace not in the trash (id, archived_at), archived ones included."""
    return db.execute("SELECT id, archived_at FROM workspaces WHERE deleted_at IS NULL").fetchall()


def choices(db: sqlite3.Connection, workspace_id: str) -> str | None:
    """Every automation's catch-up choice in one text (it changes when one does)."""
    found = db.execute(
        "SELECT group_concat(id || ':' || COALESCE(catch_up, '')) FROM automations "
        "WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchone()[0]
    return None if found is None else str(found)
