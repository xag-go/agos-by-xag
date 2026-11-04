"""The chat writes other loops wait on: AGOS's own lines in a chat and its turn
records, each written through its repository (db/chats.py, db/chat_turns.py) and
followed by the doorbell ring that wakes who waits (the send round relays an
agent's line and a finished turn's held lines; a chat's open live views look again).

Out of db/chats.py: a repository rings no engine doorbell (layer rule).

Owns: those rings. Must not: hold SQL (the repositories do) or decide what a line
says.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db import chat_turns
from agos_core.db import chats as repo
from agos_core.engine import doorbell
from agos_core.engine.chat import live_key, turn_key

__all__ = [
    "add_chat_message",
    "insert_turn",
    "set_turn",
]


def add_chat_message(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_id: int,
    author: repo.Author,
    body: str,
    speaker: str | None = None,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int | None:
    """db/chats.py add_chat_message; an agent's line rings the send round (it relays
    it on the chat's bots)."""
    added = repo.add_chat_message(
        db, workspace_id, chat_id, author, body, speaker, reply_to, reply_excerpt
    )
    if added is not None and author == "agent":
        doorbell.ring(doorbell.SEND)
    return added


def insert_turn(
    db: sqlite3.Connection,
    *,
    chat_id: int,
    workspace_id: str,
    asked_up_to: int,
    speaker: str | None = None,
    status: str = "starting",
) -> int:
    """db/chat_turns.py insert_turn; the chat's open live views look now."""
    turn_id = chat_turns.insert_turn(
        db,
        chat_id=chat_id,
        workspace_id=workspace_id,
        asked_up_to=asked_up_to,
        speaker=speaker,
        status=status,
    )
    doorbell.ring(doorbell.LIVE, live_key(chat_id))
    return turn_id


def set_turn(db: sqlite3.Connection, turn_id: int, **fields: Any) -> None:
    """db/chat_turns.py set_turn; a new status (a turn's end) lets the chat's held
    lines go out and its open live views see it."""
    chat_turns.set_turn(db, turn_id, **fields)
    if "status" in fields:
        doorbell.ring(doorbell.SEND)
        doorbell.ring(doorbell.LIVE, turn_key(turn_id))
