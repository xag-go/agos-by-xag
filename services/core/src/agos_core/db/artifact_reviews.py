"""Repository of `artifact_reviews`: the owner's review (approved / needs work, a note)
of a card's attachment or document on the Artifacts page.

Owns every read and write of artifact_reviews (actions/artifacts.py, the Board
service; the Co-Founder's review reads). Must not: import actions or engine, or touch
the artifact itself.
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = ["delete", "get", "of_workspace", "put"]


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> dict[str, dict[str, str]]:
    """{artifact: {state, note}} of the workspace's reviews."""
    return {
        str(r["artifact"]): {"state": str(r["state"]), "note": str(r["note"])}
        for r in db.execute(
            "SELECT artifact, state, note FROM artifact_reviews WHERE workspace_id = ?",
            (workspace_id,),
        )
    }


def get(db: sqlite3.Connection, workspace_id: str, artifact: str) -> sqlite3.Row | None:
    """(state, note) of one artifact's review; None when it has none."""
    row: sqlite3.Row | None = db.execute(
        "SELECT state, note FROM artifact_reviews WHERE workspace_id = ? AND artifact = ?",
        (workspace_id, artifact),
    ).fetchone()
    return row


def put(db: sqlite3.Connection, workspace_id: str, artifact: str, state: str, note: str) -> None:
    """The artifact's review, new or changed."""
    db.execute(
        """INSERT INTO artifact_reviews (workspace_id, artifact, state, note, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (workspace_id, artifact) DO UPDATE SET
               state = excluded.state, note = excluded.note, updated_at = excluded.updated_at""",
        (workspace_id, artifact, state, note, now()),
    )


def delete(db: sqlite3.Connection, workspace_id: str, artifact: str) -> None:
    db.execute(
        "DELETE FROM artifact_reviews WHERE workspace_id = ? AND artifact = ?",
        (workspace_id, artifact),
    )
