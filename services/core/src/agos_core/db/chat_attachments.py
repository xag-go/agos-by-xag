"""AGOS's index of the files sent in a chat (table message_attachments): the files
themselves are in the workspace's files; a Hermes chat's file is known to Hermes by
the queue item its message went in as (`inbox_id`), a room line's by its line.

Owns: the message_attachments rows. Must not: read or write the files, or build
what the web shows of them (actions/services/chat/view.py).
"""

import sqlite3

from agos_core.db import sql

__all__ = [
    "add_attachment",
    "attachment",
    "attachments_of",
    "drop_of_item",
    "of_items",
    "of_lines",
    "set_transcript",
    "unplaced",
]


def add_attachment(
    db: sqlite3.Connection,
    message_id: int | None,
    *,
    kind: str,
    name: str,
    mime: str,
    size: int,
    path: str,
    duration: float | None,
    chat_id: int | None = None,
    inbox_id: int | None = None,
) -> int:
    """A file of his message: a room line's (`message_id`), or the queue item his
    message went to Hermes as (`inbox_id`: Hermes keeps it as that message's id)."""
    cursor = db.execute(
        """INSERT INTO message_attachments (message_id, kind, name, mime, size, path, duration,
             chat_id, inbox_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (message_id, kind, name, mime, size, path, duration, chat_id, inbox_id),
    )
    return int(cursor.lastrowid or 0)


def attachment(
    db: sqlite3.Connection, workspace_id: str, chat_id: int, attachment_id: int
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        """SELECT a.* FROM message_attachments a
           LEFT JOIN message_rows m ON m.id = a.message_id
           JOIN chats c ON c.id = COALESCE(a.chat_id, m.chat_id)
           WHERE a.id = ? AND c.id = ? AND c.workspace_id = ? AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at)""",
        (attachment_id, chat_id, workspace_id),
    ).fetchone()
    return row


def attachments_of(db: sqlite3.Connection, message_ids: list[int]) -> list[sqlite3.Row]:
    if not message_ids:
        return []
    return list(
        db.execute(
            sql.text(
                "SELECT * FROM message_attachments WHERE message_id IN ({ids}) ORDER BY id",
                ids=sql.marks(len(message_ids)),
            ),
            message_ids,
        )
    )


def set_transcript(db: sqlite3.Connection, attachment_id: int, transcript: str) -> None:
    """A room line's voice note words (a room takes text only; the line is AGOS's own).
    A Hermes chat's file never gets one: Hermes hears it and keeps the words."""
    db.execute(
        "UPDATE message_attachments SET transcript = ? WHERE id = ? AND message_id IS NOT NULL",
        (transcript, attachment_id),
    )


def drop_of_item(db: sqlite3.Connection, inbox_id: int) -> None:
    """The files of a queue item that went (his message deleted before Hermes took it)."""
    db.execute("DELETE FROM message_attachments WHERE inbox_id = ?", (inbox_id,))


def of_lines(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """The files of AGOS's own lines of a chat, each with its line (`k`)."""
    return db.execute(
        """SELECT a.*, a.message_id AS k FROM message_attachments a
           JOIN message_rows m ON m.id = a.message_id WHERE m.chat_id = ? ORDER BY a.id""",
        (chat_id,),
    ).fetchall()


def of_items(db: sqlite3.Connection, inbox_ids: list[int]) -> list[sqlite3.Row]:
    """The files of these queue items."""
    return db.execute(
        sql.text(
            "SELECT * FROM message_attachments WHERE inbox_id IN ({ids}) ORDER BY id",
            ids=sql.marks(len(inbox_ids)),
        ),
        list(inbox_ids),
    ).fetchall()


def unplaced(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """A Hermes chat's files (no line of AGOS's): by queue item or Hermes's uid."""
    return db.execute(
        "SELECT * FROM message_attachments WHERE chat_id = ? AND message_id IS NULL ORDER BY id",
        (chat_id,),
    ).fetchall()
