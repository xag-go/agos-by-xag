"""The `skill_candidates` table: a skill's next text evolved from evidence, while AGOS
tests it against the current version (testing -> promoted | discarded).
actions/services/library/growth_candidates.py is its only writer.

Must not: test, grade or promote a candidate (the Library service does), or write
another table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = [
    "decide",
    "get",
    "in_batch",
    "insert",
    "recent",
    "runs_of",
    "set_runs",
    "testing",
    "testing_for",
]


def testing_for(db: sqlite3.Connection, workspace_id: str, item_id: int) -> bool:
    """A candidate of this skill is under test now."""
    return (
        db.execute(
            "SELECT 1 FROM skill_candidates WHERE workspace_id = ? AND item_id = ?"
            " AND status = 'testing'",
            (workspace_id, item_id),
        ).fetchone()
        is not None
    )


def insert(
    db: sqlite3.Connection,
    workspace_id: str,
    item_id: int,
    *,
    name: str,
    batch: str,
    base_version: Any,
    text: str,
    why: str,
    evidence: str,
    created_at: str,
) -> int:
    """A new candidate, under test from now."""
    cur = db.execute(
        """INSERT INTO skill_candidates (workspace_id, item_id, name, batch, base_version,
             text, why, evidence, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'testing', ?)""",
        (workspace_id, item_id, name, batch, base_version, text, why, evidence, created_at),
    )
    return int(cur.lastrowid or 0)


def set_runs(db: sqlite3.Connection, candidate_id: int, runs: str) -> None:
    """The test runs planned for it (JSON)."""
    db.execute("UPDATE skill_candidates SET runs = ? WHERE id = ?", (runs, candidate_id))


def get(db: sqlite3.Connection, workspace_id: str, candidate_id: int) -> sqlite3.Row | None:
    """One candidate, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM skill_candidates WHERE id = ? AND workspace_id = ?",
        (candidate_id, workspace_id),
    ).fetchone()
    return row


def decide(
    db: sqlite3.Connection,
    candidate_id: int,
    *,
    status: str,
    note: str,
    score: Any,
    base_score: Any,
    version: Any,
    decided_at: str,
) -> None:
    """Promoted or discarded, once (only a candidate still under test changes)."""
    db.execute(
        """UPDATE skill_candidates SET status = ?, note = ?, score = ?, base_score = ?,
             version = ?, decided_at = ? WHERE id = ? AND status = 'testing'""",
        (status, note, score, base_score, version, decided_at, candidate_id),
    )


def testing(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The workspace's candidates under test."""
    return db.execute(
        "SELECT * FROM skill_candidates WHERE workspace_id = ? AND status = 'testing'",
        (workspace_id,),
    ).fetchall()


def in_batch(db: sqlite3.Connection, workspace_id: str, batch: str) -> list[sqlite3.Row]:
    """One week's candidates of the workspace, oldest first."""
    return db.execute(
        "SELECT * FROM skill_candidates WHERE workspace_id = ? AND batch = ? ORDER BY id",
        (workspace_id, batch),
    ).fetchall()


def recent(db: sqlite3.Connection, workspace_id: str, limit: int) -> list[sqlite3.Row]:
    """The workspace's newest candidates first."""
    return db.execute(
        "SELECT * FROM skill_candidates WHERE workspace_id = ? ORDER BY id DESC LIMIT ?",
        (workspace_id, limit),
    ).fetchall()


def runs_of(db: sqlite3.Connection, workspace_id: str) -> list[Any]:
    """Every candidate's planned test runs (JSON text each) in the workspace."""
    return [
        raw
        for (raw,) in db.execute(
            "SELECT runs FROM skill_candidates WHERE workspace_id = ?", (workspace_id,)
        )
    ]
