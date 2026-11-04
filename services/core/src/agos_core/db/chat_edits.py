"""Repository of `chat_edits`: the owner's changes to (and deletions of) messages
already answered (Hermes keeps no edit in the middle of a conversation), shown in
the chat and told once to the agent with his next message.

Owns every read and write of chat_edits. Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "hermes_edits",
    "record",
    "record_hermes",
    "take_untold",
]


def record_hermes(
    db: sqlite3.Connection,
    chat_id: int,
    message_id: int,
    before: str,
    after: str,
    *,
    told: bool,
    replace: bool = False,
) -> None:
    """A change of a message in Hermes's conversation (`after` '' = deleted). `told`:
    the agent knows already (no note with his next message). `replace`: the
    message's earlier change goes first."""
    if replace:
        db.execute(
            "DELETE FROM chat_edits WHERE chat_id = ? AND message_id = ? AND hermes = 1",
            (chat_id, message_id),
        )
    db.execute(
        """INSERT INTO chat_edits (chat_id, message_id, before, after, created_at,
             told_at, hermes) VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (chat_id, message_id, before, after, now(), now() if told else None),
    )


def record(db: sqlite3.Connection, chat_id: int, message_id: int, before: str, after: str) -> None:
    """A change of one of AGOS's own lines (a room's) its members already had."""
    db.execute(
        """INSERT INTO chat_edits (chat_id, message_id, before, after, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (chat_id, message_id, before, after, now()),
    )


def take_untold(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """The changes not told yet (id, before, after), marked told now."""
    rows = db.execute(
        "SELECT id, before, after FROM chat_edits WHERE chat_id = ? AND told_at IS NULL ORDER BY id",
        (chat_id,),
    ).fetchall()
    if rows:
        db.execute(
            "UPDATE chat_edits SET told_at = ? WHERE chat_id = ? AND told_at IS NULL",
            (now(), chat_id),
        )
    return rows


def hermes_edits(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """A chat's changes of messages in Hermes's conversation, oldest first."""
    return db.execute(
        "SELECT * FROM chat_edits WHERE chat_id = ? AND hermes = 1 ORDER BY id", (chat_id,)
    ).fetchall()
