"""Repository of `card_doc_annotations`: comments on a passage of a card's document
(the quote and its context, where it sits now, resolved or not).

Owns every read and write of card_doc_annotations (actions/card_docs.py, the Board
service). Must not: import actions or engine, or read the document's files.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = [
    "add",
    "delete",
    "get",
    "of_doc",
    "open_counts",
    "open_of_doc",
    "set_anchor",
    "set_resolved",
]


def open_counts(db: sqlite3.Connection, workspace_id: str, card_id: str) -> dict[str, int]:
    """{document key: its open comments} of a card."""
    return {
        str(r["key"]): int(r["n"])
        for r in db.execute(
            """SELECT key, COUNT(*) AS n FROM card_doc_annotations
               WHERE workspace_id = ? AND card = ? AND resolved_at IS NULL GROUP BY key""",
            (workspace_id, card_id),
        )
    }


def of_doc(db: sqlite3.Connection, workspace_id: str, card_id: str, key: str) -> list[sqlite3.Row]:
    """A document's comments: open ones first, then by place."""
    return list(
        db.execute(
            """SELECT * FROM card_doc_annotations WHERE workspace_id = ? AND card = ? AND key = ?
               ORDER BY resolved_at IS NOT NULL, pos_start, id""",
            (workspace_id, card_id, key),
        )
    )


def open_of_doc(
    db: sqlite3.Connection, workspace_id: str, card_id: str, key: str
) -> list[sqlite3.Row]:
    return db.execute(
        """SELECT * FROM card_doc_annotations
           WHERE workspace_id = ? AND card = ? AND key = ? AND resolved_at IS NULL""",
        (workspace_id, card_id, key),
    ).fetchall()


def add(db: sqlite3.Connection, row: dict[str, Any]) -> int:
    """A new open comment, anchored `active` at its revision; its id. `row`: workspace_id,
    card, key, revision, quote, prefix, suffix, pos_start, pos_end, body, author, at."""
    cursor = db.execute(
        """INSERT INTO card_doc_annotations (workspace_id, card, key, revision, quote, prefix,
               suffix, pos_start, pos_end, body, author, anchor, anchored_revision, created_at,
               updated_at)
           VALUES (:workspace_id, :card, :key, :revision, :quote, :prefix, :suffix,
                   :pos_start, :pos_end, :body, :author, 'active', :revision, :at, :at)""",
        row,
    )
    return int(cursor.lastrowid or 0)


def get(db: sqlite3.Connection, workspace_id: str, annotation_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM card_doc_annotations WHERE id = ? AND workspace_id = ?",
        (annotation_id, workspace_id),
    ).fetchone()
    return row


def set_resolved(
    db: sqlite3.Connection, workspace_id: str, annotation_id: int, resolved_at: str | None, at: str
) -> bool:
    """False when the comment isn't this workspace's."""
    return bool(
        db.execute(
            """UPDATE card_doc_annotations SET resolved_at = ?, updated_at = ?
               WHERE id = ? AND workspace_id = ?""",
            (resolved_at, at, annotation_id, workspace_id),
        ).rowcount
    )


def delete(db: sqlite3.Connection, workspace_id: str, annotation_id: int) -> bool:
    """False when the comment isn't this workspace's."""
    return bool(
        db.execute(
            "DELETE FROM card_doc_annotations WHERE id = ? AND workspace_id = ?",
            (annotation_id, workspace_id),
        ).rowcount
    )


def set_anchor(
    db: sqlite3.Connection,
    workspace_id: str,
    annotation_id: int,
    start: int,
    end: int,
    state: str,
    revision: int,
    at: str,
) -> None:
    """Where the comment sits in the document's new text, and how well it holds."""
    db.execute(
        """UPDATE card_doc_annotations SET pos_start = ?, pos_end = ?, anchor = ?,
               anchored_revision = ?, updated_at = ? WHERE id = ? AND workspace_id = ?""",
        (start, end, state, revision, at, annotation_id, workspace_id),
    )
