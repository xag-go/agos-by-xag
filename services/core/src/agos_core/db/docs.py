"""The doc_versions and doc_settings tables: a workspace's documents' versions and its
document rules (actions/docs.py is their one caller).

Owns: every query on doc_versions (a version saved, a document's history, one version,
the one before it) and doc_settings (the Latin-letters-only rule).

Must not: read or write the documents themselves (actions/docs.py does, in the
workspace's folder).
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "add_version",
    "has_versions",
    "latin_only",
    "previous_body",
    "set_latin_only",
    "version",
    "versions",
]


def add_version(
    db: sqlite3.Connection,
    workspace_id: str,
    path: str,
    body: str,
    digest: str,
    author: str,
    why: str,
    at: str,
) -> None:
    db.execute(
        """INSERT INTO doc_versions (workspace_id, path, body, hash, author, why, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, path, body, digest, author, why, at),
    )


def versions(db: sqlite3.Connection, workspace_id: str, path: str) -> list[sqlite3.Row]:
    """A document's last 100 versions, newest first (id, created_at, author, why, body)."""
    return db.execute(
        """SELECT id, created_at, author, why, body FROM doc_versions
           WHERE workspace_id = ? AND path = ? ORDER BY id DESC LIMIT 100""",
        (workspace_id, path),
    ).fetchall()


def version(db: sqlite3.Connection, workspace_id: str, version_id: int) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM doc_versions WHERE id = ? AND workspace_id = ?", (version_id, workspace_id)
    ).fetchone()
    return found


def previous_body(
    db: sqlite3.Connection, workspace_id: str, path: str, version_id: int
) -> str | None:
    """The document's text in the version before `version_id`, None when it is the first."""
    found = db.execute(
        """SELECT body FROM doc_versions WHERE workspace_id = ? AND path = ? AND id < ?
           ORDER BY id DESC LIMIT 1""",
        (workspace_id, path, version_id),
    ).fetchone()
    return None if found is None else str(found["body"])


def has_versions(db: sqlite3.Connection, workspace_id: str, path: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM doc_versions WHERE workspace_id = ? AND path = ? LIMIT 1",
            (workspace_id, path),
        ).fetchone()
        is not None
    )


def latin_only(db: sqlite3.Connection, workspace_id: str) -> bool:
    row = db.execute(
        "SELECT latin_only FROM doc_settings WHERE workspace_id = ?", (workspace_id,)
    ).fetchone()
    return bool(row and row["latin_only"])


def set_latin_only(db: sqlite3.Connection, workspace_id: str, on: bool) -> None:
    db.execute(
        """INSERT INTO doc_settings (workspace_id, latin_only) VALUES (?, ?)
           ON CONFLICT (workspace_id) DO UPDATE SET latin_only = excluded.latin_only""",
        (workspace_id, 1 if on else 0),
    )
