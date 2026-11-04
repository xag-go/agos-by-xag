"""The slo_samples table (migration 147, db/schema_reliability.py): the only writer.

Owns: one measured SLI sample written, read back for a window, and old ones pruned.
Must not: measure anything (agos_core/background/slis.py does) or judge a sample
against its SLO (scripts/slo.py does).
"""

from __future__ import annotations

import sqlite3

__all__ = ["SLIS", "add", "in_window", "prune_before"]

SLIS = ("page", "first_output", "automation_delay", "health")


def add(
    db: sqlite3.Connection,
    sli: str,
    *,
    at: str,
    value_ms: int | None = None,
    ok: bool = True,
    subject: str = "",
    workspace_id: str | None = None,
    once_key: str | None = None,
) -> bool:
    """True when written; False when this `once_key` was recorded already."""
    cursor = db.execute(
        "INSERT OR IGNORE INTO slo_samples"
        " (sli, workspace_id, subject, value_ms, ok, once_key, at)"
        " VALUES (?, (SELECT id FROM workspaces WHERE id = ?), ?, ?, ?, ?, ?)",
        (sli, workspace_id, subject[:200], value_ms, 1 if ok else 0, once_key, at),
    )
    return bool(cursor.rowcount == 1)


def in_window(db: sqlite3.Connection, sli: str, start: str, end: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT subject, value_ms, ok, at FROM slo_samples"
            " WHERE sli = ? AND at >= ? AND at < ? ORDER BY at",
            (sli, start, end),
        ).fetchall()
    )


def prune_before(db: sqlite3.Connection, before: str) -> int:
    return int(db.execute("DELETE FROM slo_samples WHERE at < ?", (before,)).rowcount or 0)
