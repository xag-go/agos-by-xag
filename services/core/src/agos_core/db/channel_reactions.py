"""Repository of `channel_reactions`: his Telegram messages in chats AGOS answers
itself, whose 👀 Hermes keeps until that answer is out (then its own 👍 / 👎).

Owns every read and write of channel_reactions. Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "add",
    "done",
    "due",
    "failed",
    "older_than",
    "open_for",
    "outcome",
    "waiting",
]


def add(
    db: sqlite3.Connection, connection_id: int, chat_id: int, tg_chat: str, tg_message: str
) -> None:
    db.execute(
        """INSERT OR IGNORE INTO channel_reactions
             (connection_id, chat_id, tg_chat, tg_message, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (connection_id, chat_id, tg_chat, tg_message, now()),
    )


def open_for(db: sqlite3.Connection, connection_id: int, tg_chat: str, tg_message: str) -> bool:
    """Hermes keeps its 👀 on this message (not done yet)."""
    return (
        db.execute(
            """SELECT 1 FROM channel_reactions WHERE connection_id = ? AND tg_chat = ?
                 AND tg_message = ? AND done_at IS NULL""",
            (connection_id, tg_chat, tg_message),
        ).fetchone()
        is not None
    )


def waiting(db: sqlite3.Connection, connection_id: int) -> bool:
    """Some message of the bot still waits for its 👍 / 👎."""
    return (
        db.execute(
            """SELECT 1 FROM channel_reactions WHERE connection_id = ? AND done_at IS NULL
                 AND attempts < 5 LIMIT 1""",
            (connection_id,),
        ).fetchone()
        is not None
    )


def due(db: sqlite3.Connection, connection_id: int, claimed_for_s: int) -> list[sqlite3.Row]:
    """Rows not done (fewer than 5 tries) and not claimed in the last seconds."""
    return db.execute(
        """SELECT * FROM channel_reactions WHERE connection_id = ? AND done_at IS NULL
             AND attempts < 5 AND (claimed_at IS NULL
               OR claimed_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?))
           ORDER BY id LIMIT 100""",
        (connection_id, f"-{claimed_for_s} seconds"),
    ).fetchall()


def older_than(db: sqlite3.Connection, created_at: str, hours: int) -> bool:
    """`created_at` is more than `hours` ago (SQLite's clock, as the rows are written)."""
    return bool(
        db.execute(
            "SELECT ? < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)",
            (created_at, f"-{hours} hours"),
        ).fetchone()[0]
    )


def outcome(db: sqlite3.Connection, row_id: int, how: str) -> None:
    """How the answer went, claimed for the gateway to show."""
    db.execute(
        "UPDATE channel_reactions SET outcome = ?, claimed_at = ? WHERE id = ?",
        (how, now(), row_id),
    )


def failed(db: sqlite3.Connection, row_id: int, connection_id: int) -> None:
    db.execute(
        """UPDATE channel_reactions SET attempts = attempts + 1, claimed_at = NULL
             WHERE id = ? AND connection_id = ?""",
        (row_id, connection_id),
    )


def done(db: sqlite3.Connection, row_id: int, connection_id: int) -> None:
    """Shown; rows done a week ago go."""
    db.execute(
        "UPDATE channel_reactions SET done_at = ? WHERE id = ? AND connection_id = ?",
        (now(), row_id, connection_id),
    )
    db.execute(
        """DELETE FROM channel_reactions WHERE connection_id = ? AND done_at IS NOT NULL
             AND done_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-7 days')""",
        (connection_id,),
    )
