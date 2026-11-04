"""The owner's audit trail of a workspace (the Log shows it). The Dashboard's
"Board activity" is Hermes's Kanban events (actions/kanban_board.events), not this."""

import sqlite3

from agos_core.db.rows import now


def add_activity(db: sqlite3.Connection, workspace_id: str, *, kind: str, text: str) -> None:
    db.execute(
        "INSERT INTO activity (workspace_id, kind, text, created_at) VALUES (?, ?, ?, ?)",
        (workspace_id, kind, text, now()),
    )
