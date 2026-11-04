"""The outbox table (migration 146): the only writer.

Owns: queuing, claiming and marking notification rows. Must not: send anything
(agos_core/outbox/delivery.py does) or know a channel's payload.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

__all__ = [
    "claim",
    "due",
    "insert",
    "mark_failed",
    "mark_sent",
    "prune",
    "release_claims",
    "retry_at",
]


def insert(
    db: sqlite3.Connection,
    channel: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None,
    dedupe_key: str | None,
    at: str,
) -> int | None:
    """The new row's id; None when a row with the same dedupe key is already there."""
    cursor = db.execute(
        "INSERT OR IGNORE INTO outbox"
        " (channel, workspace_id, payload, dedupe_key, next_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (channel, workspace_id, json.dumps(payload, ensure_ascii=False), dedupe_key, at, at),
    )
    return int(cursor.lastrowid) if cursor.rowcount == 1 and cursor.lastrowid else None


def due(db: sqlite3.Connection, at: str, limit: int) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT id, channel, payload, attempts FROM outbox"
            " WHERE status = 'pending' AND next_at <= ? ORDER BY next_at, id LIMIT ?",
            (at, limit),
        ).fetchall()
    )


def claim(db: sqlite3.Connection, row_id: int) -> bool:
    """This try is ours (one sender per row); counts the try."""
    cursor = db.execute(
        "UPDATE outbox SET status = 'sending', attempts = attempts + 1"
        " WHERE id = ? AND status = 'pending'",
        (row_id,),
    )
    return bool(cursor.rowcount == 1)


def mark_sent(db: sqlite3.Connection, row_id: int, at: str) -> None:
    db.execute(
        "UPDATE outbox SET status = 'sent', sent_at = ?, last_error = NULL WHERE id = ?",
        (at, row_id),
    )


def retry_at(db: sqlite3.Connection, row_id: int, at: str, error: str) -> None:
    db.execute(
        "UPDATE outbox SET status = 'pending', next_at = ?, last_error = ? WHERE id = ?",
        (at, error[:500], row_id),
    )


def mark_failed(db: sqlite3.Connection, row_id: int, error: str) -> None:
    db.execute(
        "UPDATE outbox SET status = 'failed', last_error = ? WHERE id = ?", (error[:500], row_id)
    )


def release_claims(db: sqlite3.Connection) -> int:
    """At start: a send cut by a restart is tried again."""
    cursor = db.execute("UPDATE outbox SET status = 'pending' WHERE status = 'sending'")
    return int(cursor.rowcount or 0)


def prune(db: sqlite3.Connection, before: str) -> int:
    """Delivered rows sent before `before` go (retention); a failed one stays as the
    record of what never reached him."""
    cursor = db.execute("DELETE FROM outbox WHERE status = 'sent' AND sent_at < ?", (before,))
    return int(cursor.rowcount or 0)
