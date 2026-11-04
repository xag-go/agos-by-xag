"""Repository of `hermes_inbox`: the agos platform's queue into a workspace's Hermes
gateway (the owner's messages and replies, AGOS's /commands, approval answers, room
jobs). The agos-guard plugin takes each item once and says when it is done.

Owns the Chat and Channel services' reads and writes of hermes_inbox. Must not:
import actions or engine (the callers ring the inbox doorbell).
"""

import sqlite3
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "claim",
    "delete_waiting",
    "done",
    "done_mark",
    "drop_unfinished",
    "finished",
    "for_gateway",
    "for_rooms",
    "get",
    "last_command",
    "pending_command_text",
    "purge_done",
    "put",
    "queued_messages",
    "sent_at",
    "set_media",
    "set_waiting_text",
    "waiting_item",
    "waiting_message",
    "waits_of_kind",
]


def put(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_ref: str,
    text: str,
    kind: str,
    media: str | None = None,
) -> int:
    """One item for the gateway (`media`: its files, JSON; none: no column set)."""
    if media is None:
        cursor = db.execute(
            """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (workspace_id, chat_ref, text, kind, now()),
        )
    else:
        cursor = db.execute(
            """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, media, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (workspace_id, chat_ref, text, kind, media, now()),
        )
    return int(cursor.lastrowid or 0)


def get(db: sqlite3.Connection, workspace_id: str, item_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT chat_ref, kind, text FROM hermes_inbox WHERE id = ? AND workspace_id = ?",
        (item_id, workspace_id),
    ).fetchone()
    return row


def set_media(db: sqlite3.Connection, item_id: int, media: str) -> None:
    db.execute("UPDATE hermes_inbox SET media = ? WHERE id = ?", (media, item_id))


def for_gateway(
    db: sqlite3.Connection, workspace_id: str, retry_before: str, *, agos: bool
) -> list[sqlite3.Row]:
    """Items not done and not taken since `retry_before`, for the gateway's agos
    conversations (`agos`) or its Telegram ones; never a room's."""
    return db.execute(
        """SELECT id, chat_ref, text, kind, media, created_at FROM hermes_inbox
           WHERE workspace_id = ? AND done_at IS NULL
             AND (taken_at IS NULL OR taken_at < ?)
             AND (chat_ref LIKE 'agos:%') = ? AND chat_ref NOT LIKE 'room:%'
           ORDER BY id LIMIT 60""",
        (workspace_id, retry_before, 1 if agos else 0),
    ).fetchall()


def for_rooms(
    db: sqlite3.Connection, workspace_id: str, retry_before: str, kinds: tuple[str, ...]
) -> list[sqlite3.Row]:
    """A workspace's room jobs not done and not taken since `retry_before`."""
    return db.execute(
        sql.text(
            """SELECT id, chat_ref, text, kind FROM hermes_inbox
           WHERE workspace_id = ? AND done_at IS NULL AND (taken_at IS NULL OR taken_at < ?)
             AND chat_ref LIKE 'room:%'
             AND kind IN ({kinds}) ORDER BY id LIMIT 20""",
            kinds=sql.marks(len(kinds)),
        ),
        (workspace_id, retry_before, *kinds),
    ).fetchall()


def claim(db: sqlite3.Connection, item_id: int, retry_before: str) -> bool:
    """Taken once, even with several gateways asking."""
    return bool(
        db.execute(
            """UPDATE hermes_inbox SET taken_at = ? WHERE id = ? AND done_at IS NULL
                 AND (taken_at IS NULL OR taken_at < ?)""",
            (now(), item_id, retry_before),
        ).rowcount
    )


def done(db: sqlite3.Connection, workspace_id: str, item_id: int, ok: bool) -> None:
    """The gateway's word on an item: done, or handed back (taken again later)."""
    db.execute(
        "UPDATE hermes_inbox SET done_at = CASE WHEN ? THEN ? END, taken_at = NULL "
        "WHERE id = ? AND workspace_id = ?",
        (1 if ok else 0, now(), item_id, workspace_id),
    )


def finished(db: sqlite3.Connection, item_id: int) -> None:
    db.execute("UPDATE hermes_inbox SET done_at = ? WHERE id = ?", (now(), item_id))


def purge_done(db: sqlite3.Connection) -> int:
    """Items done for a day go (never one a sent file still points to)."""
    return db.execute(
        """DELETE FROM hermes_inbox WHERE done_at IS NOT NULL
             AND created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')
             AND id NOT IN (SELECT inbox_id FROM message_attachments
                            WHERE inbox_id IS NOT NULL)"""
    ).rowcount


def last_command(db: sqlite3.Connection, workspace_id: str, chat_ref: str) -> str | None:
    """The text of the last /command queued for this conversation."""
    row = db.execute(
        """SELECT text FROM hermes_inbox WHERE workspace_id = ? AND chat_ref = ?
             AND kind = 'command' ORDER BY id DESC LIMIT 1""",
        (workspace_id, chat_ref),
    ).fetchone()
    return str(row["text"]) if row is not None else None


def pending_command_text(
    db: sqlite3.Connection, workspace_id: str, chat_ref: str, command: str
) -> str | None:
    """The full text of the newest `command …` for this conversation not done yet."""
    found = db.execute(
        """SELECT text FROM hermes_inbox WHERE workspace_id = ? AND chat_ref = ?
             AND kind = 'command' AND text LIKE ? AND done_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (workspace_id, chat_ref, f"{command} %"),
    ).fetchone()
    return str(found["text"]) if found else None


def waiting_message(db: sqlite3.Connection, workspace_id: str, chat_refs: list[str]) -> bool:
    """He sent something to one of these conversations Hermes hasn't taken yet."""
    return (
        db.execute(
            sql.text(
                """SELECT 1 FROM hermes_inbox WHERE workspace_id = ? AND chat_ref IN ({refs})
                  AND kind IN ('message', 'reply') AND done_at IS NULL LIMIT 1""",
                refs=sql.marks(len(chat_refs)),
            ),
            (workspace_id, *chat_refs),
        ).fetchone()
        is not None
    )


def queued_messages(
    db: sqlite3.Connection, workspace_id: str, chat_refs: list[str]
) -> list[sqlite3.Row]:
    """His messages and replies to these conversations: not done, or done in the
    last three minutes (shown until Hermes's transcript has them)."""
    return db.execute(
        sql.text(
            """SELECT * FROM hermes_inbox WHERE workspace_id = ? AND chat_ref IN ({refs})
              AND kind IN ('message', 'reply')
              AND (done_at IS NULL OR created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-3 minutes'))
            ORDER BY id""",
            refs=sql.marks(len(chat_refs)),
        ),
        (workspace_id, *chat_refs),
    ).fetchall()


def sent_at(db: sqlite3.Connection, item_ids: list[int]) -> list[sqlite3.Row]:
    """(id, created_at) of these items."""
    return db.execute(
        sql.text(
            "SELECT id, created_at FROM hermes_inbox WHERE id IN ({ids})",
            ids=sql.marks(len(item_ids)),
        ),
        list(item_ids),
    ).fetchall()


def waiting_item(db: sqlite3.Connection, workspace_id: str, item_id: int) -> sqlite3.Row | None:
    """(kind, text) of an item Hermes hasn't taken yet."""
    row: sqlite3.Row | None = db.execute(
        """SELECT kind, text FROM hermes_inbox WHERE id = ? AND workspace_id = ?
             AND taken_at IS NULL AND done_at IS NULL""",
        (item_id, workspace_id),
    ).fetchone()
    return row


def set_waiting_text(db: sqlite3.Connection, item_id: int, text: Any) -> bool:
    """A new text for an item not taken yet; False when Hermes took it meanwhile."""
    return (
        db.execute(
            "UPDATE hermes_inbox SET text = ? WHERE id = ? AND taken_at IS NULL",
            (text, item_id),
        ).rowcount
        > 0
    )


def delete_waiting(db: sqlite3.Connection, workspace_id: str, item_id: int) -> bool:
    """An item not taken yet goes; False when Hermes has it already."""
    return bool(
        db.execute(
            """DELETE FROM hermes_inbox WHERE id = ? AND workspace_id = ?
                 AND taken_at IS NULL AND done_at IS NULL""",
            (item_id, workspace_id),
        ).rowcount
    )


def done_mark(db: sqlite3.Connection, workspace_id: str, item_id: int) -> tuple[bool, bool]:
    """(the item is still there, Hermes said it is done)."""
    row = db.execute(
        "SELECT done_at FROM hermes_inbox WHERE id = ? AND workspace_id = ?",
        (item_id, workspace_id),
    ).fetchone()
    return row is not None, row is not None and row["done_at"] is not None


def drop_unfinished(db: sqlite3.Connection, workspace_id: str, item_id: int) -> None:
    """The item goes unless Hermes said it is done (taken or not)."""
    db.execute(
        "DELETE FROM hermes_inbox WHERE id = ? AND workspace_id = ? AND done_at IS NULL",
        (item_id, workspace_id),
    )


def waits_of_kind(db: sqlite3.Connection, workspace_id: str, chat_ref: str, kind: str) -> bool:
    """An item of this kind for this conversation is not done yet."""
    return (
        db.execute(
            """SELECT 1 FROM hermes_inbox WHERE workspace_id = ? AND chat_ref = ?
                 AND kind = ? AND done_at IS NULL""",
            (workspace_id, chat_ref, kind),
        ).fetchone()
        is not None
    )
