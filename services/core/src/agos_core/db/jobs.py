"""The jobs table (migration 147, db/schema_reliability.py): the only writer.

Owns: queuing, claiming (with a lease), finishing, retrying and pruning job rows.
Must not: run a job or decide when to retry it (agos_core/jobs does).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

__all__ = [
    "active",
    "claim",
    "dead",
    "expired",
    "insert",
    "last_finished_at",
    "mark_dead",
    "mark_done",
    "prune_finished",
    "release_leases",
    "retry_at",
]


def insert(
    db: sqlite3.Connection,
    kind: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None,
    dedupe_key: str | None,
    max_attempts: int,
    run_at: str,
    at: str,
) -> int | None:
    """The new job's id; None when a job of this kind and key is still waiting."""
    cursor = db.execute(
        "INSERT OR IGNORE INTO jobs"
        " (kind, workspace_id, payload, dedupe_key, max_attempts, run_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            kind,
            workspace_id,
            json.dumps(payload, ensure_ascii=False),
            dedupe_key,
            max_attempts,
            run_at,
            at,
        ),
    )
    return int(cursor.lastrowid) if cursor.rowcount == 1 and cursor.lastrowid else None


def claim(db: sqlite3.Connection, at: str, lease_until: str) -> sqlite3.Row | None:
    """Takes the next due job for this worker (one statement: no two workers get the
    same job) and counts the try. A running job whose lease ended is due again."""
    row: sqlite3.Row | None = db.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_until = ?"
        " WHERE id = (SELECT id FROM jobs"
        "   WHERE (status = 'pending' AND run_at <= ?)"
        "      OR (status = 'running' AND lease_until < ? AND attempts < max_attempts)"
        "   ORDER BY run_at, id LIMIT 1)"
        " RETURNING id, kind, workspace_id, payload, attempts, max_attempts",
        (lease_until, at, at),
    ).fetchone()
    return row


def expired(db: sqlite3.Connection, at: str) -> list[sqlite3.Row]:
    """Running jobs whose lease ended on their last try (their worker died)."""
    return list(
        db.execute(
            "SELECT id, kind, workspace_id, attempts FROM jobs WHERE status = 'running'"
            " AND lease_until < ? AND attempts >= max_attempts",
            (at,),
        ).fetchall()
    )


def mark_done(db: sqlite3.Connection, workspace_id: str | None, job_id: int, at: str) -> None:
    db.execute(
        "UPDATE jobs SET status = 'done', finished_at = ?, lease_until = NULL,"
        " last_error = NULL WHERE id = ? AND workspace_id IS ?",
        (at, job_id, workspace_id),
    )


def retry_at(
    db: sqlite3.Connection, workspace_id: str | None, job_id: int, run_at: str, error: str
) -> None:
    db.execute(
        "UPDATE jobs SET status = 'pending', run_at = ?, lease_until = NULL, last_error = ?"
        " WHERE id = ? AND workspace_id IS ?",
        (run_at, error[:500], job_id, workspace_id),
    )


def mark_dead(
    db: sqlite3.Connection, workspace_id: str | None, job_id: int, at: str, error: str
) -> None:
    db.execute(
        "UPDATE jobs SET status = 'dead', finished_at = ?, lease_until = NULL, last_error = ?"
        " WHERE id = ? AND workspace_id IS ?",
        (at, error[:500], job_id, workspace_id),
    )


def release_leases(db: sqlite3.Connection) -> int:
    """At start: a run cut by a restart is tried again (its try still counts)."""
    cursor = db.execute(
        "UPDATE jobs SET status = 'pending', lease_until = NULL WHERE status = 'running'"
    )
    return int(cursor.rowcount or 0)


def active(db: sqlite3.Connection, kind: str) -> bool:
    """A job of this kind is waiting or running."""
    found = db.execute(
        "SELECT 1 FROM jobs WHERE kind = ? AND status IN ('pending', 'running') LIMIT 1",
        (kind,),
    ).fetchone()
    return found is not None


def last_finished_at(db: sqlite3.Connection, kind: str) -> str | None:
    row = db.execute(
        "SELECT max(finished_at) FROM jobs WHERE kind = ? AND finished_at IS NOT NULL", (kind,)
    ).fetchone()
    return str(row[0]) if row is not None and row[0] is not None else None


def dead(db: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """The dead letters, the latest first."""
    return list(
        db.execute(
            "SELECT id, kind, workspace_id, attempts, last_error, finished_at FROM jobs"
            " WHERE status = 'dead' ORDER BY finished_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    )


def prune_finished(db: sqlite3.Connection, before: str) -> int:
    """Finished jobs (done or dead) that ended before `before` go."""
    cursor = db.execute(
        "DELETE FROM jobs WHERE status IN ('done', 'dead') AND finished_at < ?", (before,)
    )
    return int(cursor.rowcount or 0)
