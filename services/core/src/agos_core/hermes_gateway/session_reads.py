"""The SQL of AGOS's read-only queries of a profile's Hermes session database
(Hermes's own `messages` table, hermes_state.py), run through the chat store
(db/hermes_chats.Store.query, which opens it read-only).

Owns those queries (the skill growth's week of messages). Must not: write, open the
database itself, or decide what a row means (its caller does).
"""

from __future__ import annotations

import sqlite3
from typing import Protocol

__all__ = ["MESSAGES_LIMIT", "messages_since"]

# The most messages one week's read takes from one profile.
MESSAGES_LIMIT = 20000

_MESSAGES_SINCE = """SELECT session_id, role, content, tool_calls, tool_name FROM messages
   WHERE timestamp >= ? ORDER BY session_id, id LIMIT ?"""


class _Store(Protocol):
    def query(self, profile: str, sql: str, args: tuple[float, int]) -> list[sqlite3.Row]: ...


def messages_since(store: _Store, profile: str, since_epoch: float) -> list[sqlite3.Row]:
    """The profile's messages from `since_epoch` on, session by session, in order."""
    return store.query(profile, _MESSAGES_SINCE, (since_epoch, MESSAGES_LIMIT))
