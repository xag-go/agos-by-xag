"""Repository of `status_cards`: the Board's status cards (a goal, project, member
or query the Co-Founder summarises on a schedule; the summary itself is a document).

Owns every read and write of status_cards. Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "add",
    "change",
    "delete",
    "get",
    "of_workspace",
    "refresh_asked",
    "titles",
    "written",
]


def get(db: sqlite3.Connection, workspace_id: str, card_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM status_cards WHERE id = ? AND workspace_id = ?", (card_id, workspace_id)
    ).fetchone()
    return row


def titles(db: sqlite3.Connection, workspace_id: str) -> dict[int, str]:
    return {
        int(r["id"]): str(r["title"])
        for r in db.execute(
            "SELECT id, title FROM status_cards WHERE workspace_id = ?", (workspace_id,)
        )
    }


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM status_cards WHERE workspace_id = ? ORDER BY id", (workspace_id,)
    ).fetchall()


def add(
    db: sqlite3.Connection, workspace_id: str, title: str, scope: str, ref: str, policy: str
) -> int:
    at = now()
    return int(
        db.execute(
            """INSERT INTO status_cards (workspace_id, title, scope, scope_ref, policy,
                                         created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (workspace_id, title, scope, ref, policy, at, at),
        ).lastrowid
        or 0
    )


def change(
    db: sqlite3.Connection,
    workspace_id: str,
    card_id: int,
    title: str,
    scope: str,
    ref: str,
    policy: str,
) -> None:
    db.execute(
        """UPDATE status_cards SET title = ?, scope = ?, scope_ref = ?, policy = ?, updated_at = ?
           WHERE id = ? AND workspace_id = ?""",
        (title, scope, ref, policy, now(), card_id, workspace_id),
    )


def refresh_asked(db: sqlite3.Connection, card_id: int) -> None:
    db.execute("UPDATE status_cards SET refresh_asked_at = ? WHERE id = ?", (now(), card_id))


def written(db: sqlite3.Connection, card_id: int) -> None:
    """Its summary was just written: no refresh is waited for any more."""
    db.execute(
        "UPDATE status_cards SET refresh_asked_at = NULL, updated_at = ? WHERE id = ?",
        (now(), card_id),
    )


def delete(db: sqlite3.Connection, workspace_id: str, card_id: int) -> None:
    db.execute(
        "DELETE FROM status_cards WHERE id = ? AND workspace_id = ?", (card_id, workspace_id)
    )
