"""Repository of `template_installs`: which ready-made team (a catalog bundle) a
workspace installed, its hash then and what each of its items became there.

Owns every read and write of template_installs. Must not: import actions or engine,
or read the bundle (actions/teams_catalog.py does).
"""

import sqlite3

from agos_core.db.rows import now

__all__ = ["add", "of_workspace"]


def add(
    db: sqlite3.Connection, workspace_id: str, slug: str, title: str, content_hash: str, items: str
) -> None:
    """One install (`items`: JSON of what the template's items are named here)."""
    db.execute(
        """INSERT INTO template_installs (workspace_id, slug, title, content_hash, items,
                                          installed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (workspace_id, slug, title, content_hash, items, now()),
    )


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The workspace's installs, oldest first."""
    return db.execute(
        "SELECT * FROM template_installs WHERE workspace_id = ? ORDER BY id", (workspace_id,)
    ).fetchall()
