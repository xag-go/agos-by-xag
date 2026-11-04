"""Repository of a group chat's Hermes room: `group_rooms` (which room each group is,
its generation, how far AGOS read it, its state and the discussion it answers) and
`room_events` (each room event AGOS took, once, and the line it became).

Owns every read and write of those two tables (the Chat service's room bridge
decides what they hold). Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "advance",
    "chat_of_room",
    "cursors",
    "event_line",
    "get",
    "named_ready",
    "replace_discussion",
    "room_of",
    "set_discussion",
    "synced",
    "take_event",
    "want",
]


def get(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM group_rooms WHERE chat_id = ? AND workspace_id = ?",
        (chat_id, workspace_id),
    ).fetchone()
    return row


def room_of(db: sqlite3.Connection, chat_id: int) -> str | None:
    """The Hermes room a group chat is (any workspace: the caller has its row)."""
    row = db.execute("SELECT room_id FROM group_rooms WHERE chat_id = ?", (chat_id,)).fetchone()
    return str(row["room_id"]) if row is not None else None


def chat_of_room(db: sqlite3.Connection, workspace_id: str, room_id: str) -> int | None:
    row = db.execute(
        "SELECT chat_id FROM group_rooms WHERE workspace_id = ? AND room_id = ?",
        (workspace_id, room_id),
    ).fetchone()
    return int(row["chat_id"]) if row is not None else None


def cursors(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """(room_id, cursor, chat_id) of the workspace's rooms."""
    return db.execute(
        "SELECT room_id, cursor, chat_id FROM group_rooms WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()


def named_ready(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """(workspace_id, chat_id, room_id) of ready rooms whose group still holds a name."""
    return db.execute(
        """SELECT g.workspace_id, g.chat_id, g.room_id FROM group_rooms g
             JOIN chats c ON c.id = g.chat_id
            WHERE g.state = 'ready' AND c.kind = 'group' AND c.title != ''"""
    ).fetchall()


def want(
    db: sqlite3.Connection, chat_id: int, workspace_id: str, room_id: str, generation: int
) -> None:
    """The group's room is (again) this one, wanted: read from its start."""
    db.execute(
        """INSERT INTO group_rooms (chat_id, workspace_id, room_id, generation,
             cursor, state, updated_at) VALUES (?, ?, ?, ?, 0, 'wanted', ?)
           ON CONFLICT (chat_id) DO UPDATE SET room_id = excluded.room_id,
             generation = excluded.generation, cursor = 0,
             state = 'wanted', error = NULL, discussion = NULL,
             updated_at = excluded.updated_at""",
        (chat_id, workspace_id, room_id, generation, now()),
    )


def set_discussion(db: sqlite3.Connection, chat_id: int, discussion: str) -> None:
    db.execute(
        "UPDATE group_rooms SET discussion = ?, updated_at = ? WHERE chat_id = ?",
        (discussion, now(), chat_id),
    )


def replace_discussion(db: sqlite3.Connection, chat_id: int, new: str, old: str) -> None:
    """The id Hermes really gave the message, where the room still answers `old`."""
    db.execute(
        "UPDATE group_rooms SET discussion = ? WHERE chat_id = ? AND discussion = ?",
        (new, chat_id, old),
    )


def synced(db: sqlite3.Connection, chat_id: int, room_id: object, error: str | None) -> None:
    """Hermes made (or refused: `error`) the room."""
    db.execute(
        """UPDATE group_rooms SET state = ?, error = ?, updated_at = ?
           WHERE chat_id = ? AND room_id = ?""",
        ("ready" if error is None else "failed", error, now(), chat_id, room_id),
    )


def advance(db: sqlite3.Connection, chat_id: int, seq: int) -> None:
    db.execute(
        "UPDATE group_rooms SET cursor = MAX(cursor, ?), updated_at = ? WHERE chat_id = ?",
        (seq, now(), chat_id),
    )


def take_event(
    db: sqlite3.Connection, workspace_id: str, room_id: str, event_id: str, seq: int, kind: str
) -> bool:
    """The event is taken once: True the first time."""
    return bool(
        db.execute(
            """INSERT OR IGNORE INTO room_events (workspace_id, room_id, event_id, seq, kind,
                 created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (workspace_id, room_id, event_id, seq, kind, now()),
        ).rowcount
    )


def event_line(
    db: sqlite3.Connection, workspace_id: str, room_id: str, event_id: str, message_id: int | None
) -> None:
    """The chat line a room event became."""
    db.execute(
        """UPDATE room_events SET message_id = ? WHERE workspace_id = ? AND room_id = ?
             AND event_id = ?""",
        (message_id, workspace_id, room_id, event_id),
    )
