"""Reads of a profile's Hermes session store (state.db) for the Board and the
learning conversation, read-only (ADR 0024). A chat's own conversation is read by
hermes_gateway/chat_sessions.py.

Owns: those SQL statements on state.db (Hermes's sessions and messages).
Must not: write a Hermes store, or shape rows for a page.
Errors are sqlite3.Error, as from the database itself.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from agos_core.hermes_gateway import hermes_db

__all__ = ["DECISIONS_SQL", "card_todos", "user_messages"]

# His words in the sessions whose key matches (newest first).
DECISIONS_SQL = """SELECT m.content, m.timestamp FROM messages m
   WHERE m.session_id IN (SELECT s.id FROM sessions s WHERE s.session_key LIKE ?)
     AND m.role = 'user'
   ORDER BY m.timestamp DESC LIMIT ?"""


def card_todos(state: Path, card_id: str) -> str | None:
    """The content of the latest todo-tool message in a Kanban work session on this
    card (Hermes's own todo list of the member's run); None when there is none."""
    with contextlib.closing(hermes_db.connect_ro(state, timeout=2)) as db:
        row = db.execute(
            """SELECT m.content FROM messages m JOIN sessions s ON s.id = m.session_id
               WHERE s.source = 'kanban' AND m.tool_name IN ('todo', 'todo_list')
                 AND EXISTS (SELECT 1 FROM messages f WHERE f.session_id = s.id
                               AND f.role = 'user' AND f.content = ?)
               ORDER BY m.id DESC LIMIT 1""",
            (f"work kanban task {card_id}",),
        ).fetchone()
    return None if row is None else str(row[0])


def user_messages(state: Path, session_key_like: str, limit: int) -> list[Any]:
    """(content, timestamp) of the user's messages in the sessions whose key is LIKE
    `session_key_like`, newest first."""
    with contextlib.closing(hermes_db.connect_ro(state, timeout=2)) as db:
        return db.execute(DECISIONS_SQL, (session_key_like, limit)).fetchall()
