"""Repository of the Inbox's own tables: `inbox_marks` (an item read or dismissed by
the owner, keyed by the item) and `inbox_notes` (a note AGOS leaves him about his
team).

Owns every read and write of those two tables (actions/inbox.py decides what an
item is). Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "add_mark",
    "add_note",
    "drop_mark",
    "drop_marks_of_ended_asks",
    "has_note_like",
    "last_note",
    "marks",
    "note_titled",
    "notes",
    "set_note_detail",
    "unread_asks",
    "unread_notes",
]


def marks(db: sqlite3.Connection, workspace_id: str) -> list[tuple[str, str]]:
    """(key, mark) of every mark in the workspace."""
    return [
        (str(key), str(mark))
        for key, mark in db.execute(
            "SELECT key, mark FROM inbox_marks WHERE workspace_id = ?", (workspace_id,)
        )
    ]


def add_mark(db: sqlite3.Connection, workspace_id: str, key: str, mark: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO inbox_marks (workspace_id, key, mark, created_at) VALUES (?, ?, ?, ?)",
        (workspace_id, key, mark, now()),
    )


def drop_mark(db: sqlite3.Connection, workspace_id: str, key: str, mark: str) -> bool:
    """True when there was one."""
    return bool(
        db.execute(
            "DELETE FROM inbox_marks WHERE workspace_id = ? AND key = ? AND mark = ?",
            (workspace_id, key, mark),
        ).rowcount
    )


def drop_marks_of_ended_asks(db: sqlite3.Connection, workspace_id: str) -> int:
    """Marks of asks that ended (decided, answered): their keys read back from the
    rows, never built. How many went."""
    rows = db.execute(
        """SELECT m.key FROM inbox_marks m JOIN kanban_asks a
             ON m.key = 'ask:' || a.id AND a.workspace_id = m.workspace_id
           WHERE m.workspace_id = ? AND a.status != 'waiting'""",
        (workspace_id,),
    ).fetchall()
    for row in rows:
        db.execute(
            "DELETE FROM inbox_marks WHERE workspace_id = ? AND key = ?",
            (workspace_id, row["key"]),
        )
    return len(rows)


def unread_asks(db: sqlite3.Connection, workspace_id: str) -> int:
    """Waiting asks the owner hasn't read or dismissed."""
    row = db.execute(
        """SELECT COUNT(*) AS n FROM kanban_asks a
           WHERE a.workspace_id = ? AND a.status = 'waiting'
             AND NOT EXISTS (SELECT 1 FROM inbox_marks m WHERE m.workspace_id = a.workspace_id
                               AND m.key = 'ask:' || a.id)""",
        (workspace_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def unread_notes(db: sqlite3.Connection, workspace_id: str) -> int:
    """Notes the owner hasn't read or dismissed."""
    row = db.execute(
        """SELECT COUNT(*) AS n FROM inbox_notes n
           WHERE n.workspace_id = ?
             AND NOT EXISTS (SELECT 1 FROM inbox_marks m WHERE m.workspace_id = n.workspace_id
                               AND m.key = 'note:' || n.id)""",
        (workspace_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def notes(db: sqlite3.Connection, workspace_id: str, limit: int = 50) -> list[sqlite3.Row]:
    """The newest notes first."""
    return db.execute(
        "SELECT * FROM inbox_notes WHERE workspace_id = ? ORDER BY id DESC LIMIT ?",
        (workspace_id, limit),
    ).fetchall()


def add_note(db: sqlite3.Connection, workspace_id: str, kind: str, title: str, detail: str) -> int:
    cur = db.execute(
        """INSERT INTO inbox_notes (workspace_id, kind, title, detail, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (workspace_id, kind, title, detail, now()),
    )
    return int(cur.lastrowid or 0)


def last_note(db: sqlite3.Connection, workspace_id: str, kind: str) -> sqlite3.Row | None:
    """(title, detail) of the newest note of this kind."""
    row: sqlite3.Row | None = db.execute(
        """SELECT title, detail FROM inbox_notes WHERE workspace_id = ? AND kind = ?
           ORDER BY id DESC LIMIT 1""",
        (workspace_id, kind),
    ).fetchone()
    return row


def note_titled(db: sqlite3.Connection, workspace_id: str, kind: str, title: str) -> int | None:
    """The id of the note of this kind with this title; None when there is none."""
    row = db.execute(
        "SELECT id FROM inbox_notes WHERE workspace_id = ? AND kind = ? AND title = ?",
        (workspace_id, kind, title),
    ).fetchone()
    return None if row is None else int(row["id"])


def set_note_detail(db: sqlite3.Connection, workspace_id: str, note_id: int, detail: str) -> None:
    db.execute(
        "UPDATE inbox_notes SET detail = ? WHERE id = ? AND workspace_id = ?",
        (detail, note_id, workspace_id),
    )


def has_note_like(db: sqlite3.Connection, workspace_id: str, kind: str, detail_start: str) -> bool:
    """A note of this kind whose detail starts with `detail_start` (no `%` in it)."""
    found = db.execute(
        "SELECT 1 FROM inbox_notes WHERE workspace_id = ? AND kind = ? AND detail LIKE ?",
        (workspace_id, kind, detail_start.replace("%", "") + "%"),
    ).fetchone()
    return found is not None
