"""Repository of `channel_outbox`: what AGOS has for a workspace's bot that Hermes has
no place for (relayed replies, AGOS's own cards), queued once per address and
source, handed to the workspace's Hermes gateway to send, and closed when answered.

Owns: every read and write of channel_outbox (the Channel service decides what
goes in and rings the outbox doorbell). Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import dump_json, now

__all__ = [
    "claim",
    "close_card",
    "closed",
    "closed_by_button",
    "failed",
    "open_cards",
    "queue",
    "queue_sent",
    "seen_all_agent_lines",
    "sends_of",
    "sent",
    "skip",
    "to_close",
    "to_send",
    "unqueued_replies",
]


def queue(
    db: sqlite3.Connection,
    connection_id: int,
    address: str,
    body: str,
    source: str,
    buttons: list[tuple[str, str]] | None = None,
) -> int:
    """`body` queued once per (connection, address, source); 1 when it is new."""
    return db.execute(
        """INSERT OR IGNORE INTO channel_outbox
             (connection_id, address, body, buttons, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (connection_id, address, body, dump_json(buttons or []), source, now()),
    ).rowcount


def queue_sent(
    db: sqlite3.Connection, connection_id: int, address: str, body: str, source: str
) -> None:
    """A line already in Telegram (Hermes sent it itself): recorded so AGOS never
    sends it there again."""
    db.execute(
        """INSERT OR IGNORE INTO channel_outbox
             (connection_id, address, body, source, sent_id, created_at)
           VALUES (?, ?, ?, ?, 'skipped', ?)""",
        (connection_id, address, body, source, now()),
    )


def seen_all_agent_lines(
    db: sqlite3.Connection, connection_id: int, address: str, chat_id: int
) -> None:
    """A new address of a chat: the agent's lines already in it are not re-sent."""
    db.execute(
        """INSERT OR IGNORE INTO channel_outbox (connection_id, address, body, source, sent_id, created_at)
           SELECT ?, ?, '', 'msg:' || id, 'skipped', ? FROM messages
           WHERE chat_id = ? AND author = 'agent'""",
        (connection_id, address, now(), chat_id),
    )


def unqueued_replies(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Each agent reply in a chat with addresses not queued yet for an address,
    with whether the workspace's Hermes sends it itself (its own turn's answer)."""
    return db.execute(
        """SELECT a.connection_id, a.address, m.id, m.body, m.speaker, ch.kind,
                  ch.workspace_id,
                  (c.engine = 'hermes' AND ch.kind != 'group' AND EXISTS (
                    SELECT 1 FROM chat_turns t WHERE t.chat_id = m.chat_id AND t.via = 'hermes'
                      AND (t.reply_id = m.id OR t.status IN ('starting','running','stopping'))
                  )) AS hermes_sends
           FROM messages m JOIN chat_addresses a ON a.chat_id = m.chat_id
           JOIN channel_connections c ON c.id = a.connection_id
           JOIN chats ch ON ch.id = m.chat_id
           WHERE m.author = 'agent' AND m.chat_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM channel_outbox o
                             WHERE o.connection_id = a.connection_id
                               AND o.address = a.address AND o.source = 'msg:' || m.id)"""
    ).fetchall()


def open_cards(db: sqlite3.Connection, within_days: int) -> list[sqlite3.Row]:
    """Cards sent with buttons in the last days, not closed (bot on)."""
    return db.execute(
        """SELECT o.id, o.connection_id, o.address, o.body, o.buttons, o.sent_id
             FROM channel_outbox o JOIN channel_connections c ON c.id = o.connection_id
           WHERE o.closed_at IS NULL AND o.close_text IS NULL AND o.buttons != '[]'
             AND agos_bot_on(c.workspace_id)
             AND o.sent_id IS NOT NULL AND o.sent_id NOT IN ('', 'skipped')
             AND o.created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)""",
        (f"-{within_days} days",),
    ).fetchall()


def close_card(db: sqlite3.Connection, row_id: int, text: str) -> None:
    """The text its gateway closes the card with (the answer shown, no buttons)."""
    db.execute("UPDATE channel_outbox SET close_text = ? WHERE id = ?", (text, row_id))


def closed_by_button(db: sqlite3.Connection, connection_id: int, message_id: str) -> None:
    """Answered by its own button in Telegram."""
    db.execute(
        "UPDATE channel_outbox SET closed_at = ? WHERE connection_id = ? AND sent_id = ?",
        (now(), connection_id, message_id),
    )


def to_send(
    db: sqlite3.Connection, connection_id: int, claimed_for_s: int, limit: int
) -> list[sqlite3.Row]:
    """Rows not sent yet (fewer than 5 tries), not claimed in the last seconds."""
    return db.execute(
        """SELECT * FROM channel_outbox WHERE connection_id = ? AND sent_id IS NULL
             AND attempts < 5 AND (claimed_at IS NULL
               OR claimed_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?))
           ORDER BY id LIMIT ?""",
        (connection_id, f"-{claimed_for_s} seconds", limit),
    ).fetchall()


def skip(db: sqlite3.Connection, row_id: int) -> None:
    db.execute("UPDATE channel_outbox SET sent_id = 'skipped' WHERE id = ?", (row_id,))


def claim(db: sqlite3.Connection, row_id: int) -> None:
    db.execute("UPDATE channel_outbox SET claimed_at = ? WHERE id = ?", (now(), row_id))


def to_close(db: sqlite3.Connection, connection_id: int, limit: int) -> list[sqlite3.Row]:
    return db.execute(
        """SELECT * FROM channel_outbox WHERE connection_id = ? AND close_text IS NOT NULL
             AND closed_at IS NULL LIMIT ?""",
        (connection_id, limit),
    ).fetchall()


def closed(db: sqlite3.Connection, row_id: int, connection_id: int) -> None:
    db.execute(
        "UPDATE channel_outbox SET closed_at = ? WHERE id = ? AND connection_id = ?",
        (now(), row_id, connection_id),
    )


def failed(db: sqlite3.Connection, row_id: int, connection_id: int, error: str) -> None:
    db.execute(
        """UPDATE channel_outbox SET attempts = attempts + 1, error = ?, claimed_at = NULL
           WHERE id = ? AND connection_id = ?""",
        (error, row_id, connection_id),
    )


def sent(db: sqlite3.Connection, row_id: int, connection_id: int, message_id: str) -> None:
    db.execute(
        """UPDATE channel_outbox SET sent_id = ?, error = NULL
           WHERE id = ? AND connection_id = ?""",
        (message_id, row_id, connection_id),
    )


def sends_of(db: sqlite3.Connection, connection_id: int, source: str) -> list[sqlite3.Row]:
    """How far each queued copy of one source got (sent_id, attempts)."""
    return db.execute(
        """SELECT sent_id, attempts FROM channel_outbox
             WHERE connection_id = ? AND source = ?""",
        (connection_id, source),
    ).fetchall()
