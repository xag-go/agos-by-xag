"""The operation runs table (`op_runs`, migration 146): the only writer.

One row per run of a registered operation (agos_core/ops/registry.py): the audit
row of who did what, how it ended, and the idempotency key that hands a retry the
first run's result.

Owns: those rows. Must not: decide who may run what (the registry does).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agos_core.db.rows import now

__all__ = [
    "find",
    "finish",
    "forget_key",
    "get",
    "latest",
    "mark_undone",
    "prune_finished",
    "result_of",
    "start",
]


def start(
    db: sqlite3.Connection, operation: str, actor: str, title: str, idempotency_key: str | None
) -> int:
    """Raises sqlite3.IntegrityError when the key is already taken (another run)."""
    cursor = db.execute(
        "INSERT INTO op_runs (operation, actor, title, idempotency_key, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (operation, actor, title[:300], idempotency_key, now()),
    )
    return int(cursor.lastrowid or 0)


def finish(
    db: sqlite3.Connection,
    run_id: int,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Its end; the workspace is kept only if it exists (a failed create made none),
    so its rows go with it."""
    db.execute(
        "UPDATE op_runs SET status = ?, result = ?, error = ?, finished_at = ?,"
        " workspace_id = (SELECT id FROM workspaces WHERE id = ?) WHERE id = ?",
        (
            status,
            json.dumps(result) if result is not None else None,
            error[:2000] if error else None,
            now(),
            workspace_id,
            run_id,
        ),
    )


def find(db: sqlite3.Connection, operation: str, idempotency_key: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM op_runs WHERE operation = ? AND idempotency_key = ?",
        (operation, idempotency_key),
    ).fetchone()
    return row


def forget_key(db: sqlite3.Connection, run_id: int) -> None:
    """A failed run lets its key go: the retry is a new run (the old one stays audited)."""
    db.execute("UPDATE op_runs SET idempotency_key = NULL WHERE id = ?", (run_id,))


def get(db: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute("SELECT * FROM op_runs WHERE id = ?", (run_id,)).fetchone()
    return row


def latest(db: sqlite3.Connection, operation: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM op_runs WHERE operation = ? ORDER BY id DESC LIMIT 1", (operation,)
    ).fetchone()
    return row


def mark_undone(db: sqlite3.Connection, run_id: int) -> bool:
    cursor = db.execute(
        "UPDATE op_runs SET status = 'undone', finished_at = ? WHERE id = ? AND status = 'done'",
        (now(), run_id),
    )
    return bool(cursor.rowcount == 1)


def prune_finished(db: sqlite3.Connection, before: str) -> int:
    """Runs that ended before `before` go (retention); a running one stays."""
    cursor = db.execute(
        "DELETE FROM op_runs WHERE status != 'running' AND finished_at < ?", (before,)
    )
    return int(cursor.rowcount or 0)


def result_of(row: sqlite3.Row) -> dict[str, Any]:
    found = json.loads(row["result"]) if row["result"] else {}
    return found if isinstance(found, dict) else {}
