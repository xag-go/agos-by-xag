"""The system_log table: AGOS's own warnings and errors (actions/system_log.py writes it;
db/status_reads.py reads it for the workspace Log).

Owns: one line written, the oldest lines dropped past a limit or an age, and the workspace ids
a line may name.

Must not: format or redact a line (actions/system_log.py does).
"""

from __future__ import annotations

import sqlite3

__all__ = ["add", "keep_last", "prune_before", "workspace_ids"]


def add(
    db: sqlite3.Connection, workspace_id: str | None, level: str, source: str, text: str, at: str
) -> None:
    db.execute(
        """INSERT INTO system_log (workspace_id, level, source, text, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (workspace_id, level, source, text, at),
    )


def keep_last(db: sqlite3.Connection, keep: int) -> None:
    """Only the newest `keep` lines stay."""
    db.execute(
        """DELETE FROM system_log WHERE id <=
             (SELECT id FROM system_log ORDER BY id DESC LIMIT 1 OFFSET ?)""",
        (keep,),
    )


def prune_before(db: sqlite3.Connection, before: str) -> int:
    """Lines written before `before` go (retention, agos_core/background/retention.py)."""
    return int(db.execute("DELETE FROM system_log WHERE created_at < ?", (before,)).rowcount or 0)


def workspace_ids(db: sqlite3.Connection) -> set[str]:
    """Every workspace id, the trashed ones too (a line may still name one)."""
    return {str(r[0]) for r in db.execute("SELECT id FROM workspaces")}
