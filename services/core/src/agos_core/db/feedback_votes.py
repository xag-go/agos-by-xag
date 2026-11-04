"""Repository of `feedback_votes`: the owner's 👍 / 👎 on an agent's reply or on a
document revision, with his note.

Owns the Docs and Chat services' reads and writes of feedback_votes (actions/feedback.py
writes; the chat view reads a chat's votes; the Library's skill growth reads the 👎).
Must not: import actions or engine, or tell Hermes about a vote (actions/learning.py does).
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = ["delete", "dislikes_since", "put", "with_prefix"]


def put(
    db: sqlite3.Connection, workspace_id: str, kind: str, ref: str, vote: int, note: str
) -> None:
    """The owner's vote on one item, new or changed."""
    db.execute(
        """INSERT INTO feedback_votes (workspace_id, kind, ref, vote, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (workspace_id, kind, ref) DO UPDATE SET
               vote = excluded.vote, note = excluded.note, created_at = excluded.created_at""",
        (workspace_id, kind, ref, vote, note, now()),
    )


def delete(db: sqlite3.Connection, workspace_id: str, kind: str, ref: str) -> None:
    db.execute(
        "DELETE FROM feedback_votes WHERE workspace_id = ? AND kind = ? AND ref = ?",
        (workspace_id, kind, ref),
    )


def with_prefix(
    db: sqlite3.Connection, workspace_id: str, kind: str, prefix: str
) -> dict[str, int]:
    """{ref: vote} of the items of `kind` whose ref starts with `prefix`."""
    return {
        str(r["ref"]): int(r["vote"])
        for r in db.execute(
            """SELECT ref, vote FROM feedback_votes
               WHERE workspace_id = ? AND kind = ? AND ref >= ? AND ref < ?""",
            (workspace_id, kind, prefix, prefix + "\uffff"),
        )
    }


def dislikes_since(db: sqlite3.Connection, workspace_id: str, since: str) -> list[sqlite3.Row]:
    """(id, kind, ref, note) of the 👎 votes made at `since` (ISO) or later, oldest first."""
    return db.execute(
        """SELECT id, kind, ref, note FROM feedback_votes
           WHERE workspace_id = ? AND vote = -1 AND created_at >= ? ORDER BY id""",
        (workspace_id, since),
    ).fetchall()
