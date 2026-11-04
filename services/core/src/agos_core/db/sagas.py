"""The saga journal (tables `sagas`, `saga_steps`; migration 146): the only writer.

Owns: the rows of each saga and its steps. Must not: decide what a step does or
when to compensate (agos_core/saga.py does).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agos_core.db.rows import now

__all__ = [
    "attach",
    "data_of",
    "finish",
    "get",
    "open_sagas",
    "prune_completed",
    "record_step",
    "start",
    "steps",
]


def start(db: sqlite3.Connection, name: str, workspace_id: str | None, data: dict[str, Any]) -> int:
    cursor = db.execute(
        "INSERT INTO sagas (name, workspace_id, data, started_at) VALUES (?, ?, ?, ?)",
        (name, workspace_id, json.dumps(data), now()),
    )
    return int(cursor.lastrowid or 0)


def attach(db: sqlite3.Connection, saga_id: int, workspace_id: str | None) -> None:
    """The workspace the saga made now exists: its journal goes with it (None:
    the journal is kept apart, e.g. while a failed create removes the workspace)."""
    db.execute("UPDATE sagas SET workspace_id = ? WHERE id = ?", (workspace_id, saga_id))


def record_step(
    db: sqlite3.Connection, saga_id: int, seq: int, name: str, status: str, error: str | None
) -> None:
    db.execute(
        "INSERT INTO saga_steps (saga_id, seq, name, status, error, at) VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (saga_id, seq) DO UPDATE SET status = excluded.status,"
        " error = excluded.error, at = excluded.at",
        (saga_id, seq, name, status, error, now()),
    )


def finish(db: sqlite3.Connection, saga_id: int, status: str, error: str | None = None) -> None:
    db.execute(
        "UPDATE sagas SET status = ?, error = ?, finished_at = ? WHERE id = ?",
        (status, error, now(), saga_id),
    )


def get(db: sqlite3.Connection, saga_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute("SELECT * FROM sagas WHERE id = ?", (saga_id,)).fetchone()
    return row


def data_of(db: sqlite3.Connection, saga_id: int) -> dict[str, Any]:
    row = get(db, saga_id)
    found = json.loads(row["data"]) if row is not None else {}
    return found if isinstance(found, dict) else {}


def steps(db: sqlite3.Connection, saga_id: int) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT seq, name, status, error, at FROM saga_steps WHERE saga_id = ? ORDER BY seq",
            (saga_id,),
        ).fetchall()
    )


def open_sagas(
    db: sqlite3.Connection, name: str, workspace_id: str | None = None
) -> list[sqlite3.Row]:
    """The sagas of `name` that need attention (a step left to finish), oldest first."""
    if workspace_id is None:
        return list(
            db.execute(
                "SELECT * FROM sagas WHERE name = ? AND status = 'needs_attention' ORDER BY id",
                (name,),
            ).fetchall()
        )
    return list(
        db.execute(
            """SELECT * FROM sagas WHERE name = ? AND status = 'needs_attention'
                 AND workspace_id = ? ORDER BY id""",
            (name, workspace_id),
        ).fetchall()
    )


def prune_completed(db: sqlite3.Connection, before: str) -> int:
    """Journals of sagas that completed (done, or fully undone) before `before` go,
    their steps with them (ON DELETE CASCADE); one that needs attention stays."""
    cursor = db.execute(
        "DELETE FROM sagas WHERE status IN ('done', 'compensated') AND finished_at < ?",
        (before,),
    )
    return int(cursor.rowcount or 0)
