"""The `workspace_app_logins` table: a workspace's app logins as AGOS keeps their
bookkeeping (when, the tools it got, Composio's session, the last error). Hermes
holds the login itself. actions/services/connector/ is its only writer.

Must not: sign in or out of an app (the Connector service and Hermes do), or write
another table.
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "delete",
    "delete_all",
    "get",
    "key_sessions",
    "key_sessions_elsewhere",
    "save_connected",
    "save_key_session",
    "set_error",
    "set_session",
]


def get(db: sqlite3.Connection, workspace_id: str, app: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM workspace_app_logins WHERE workspace_id = ? AND app = ?",
        (workspace_id, app),
    ).fetchone()
    return row


def save_connected(db: sqlite3.Connection, workspace_id: str, app: str, tools: str) -> None:
    """A login that just finished (its tools, as JSON); a re-login replaces it."""
    stamp = now()
    db.execute(
        """INSERT INTO workspace_app_logins
             (workspace_id, app, status, tools, error, connected_at, updated_at)
           VALUES (?, ?, 'connected', ?, NULL, ?, ?)
           ON CONFLICT (workspace_id, app) DO UPDATE SET status = 'connected',
             tools = excluded.tools, error = NULL, connected_at = excluded.connected_at,
             updated_at = excluded.updated_at""",
        (workspace_id, app, tools, stamp, stamp),
    )


def save_key_session(
    db: sqlite3.Connection, workspace_id: str, app: str, session: str, stamp: str
) -> None:
    """An app reached with a project key (Composio): its session, connected now."""
    db.execute(
        """INSERT INTO workspace_app_logins
             (workspace_id, app, status, tools, error, connected_at, updated_at, via, session)
           VALUES (?, ?, 'connected', '[]', NULL, ?, ?, 'key', ?)
           ON CONFLICT (workspace_id, app) DO UPDATE SET status = 'connected', tools = '[]',
             error = NULL, connected_at = excluded.connected_at,
             updated_at = excluded.updated_at, via = 'key', session = excluded.session""",
        (workspace_id, app, stamp, stamp, session),
    )


def set_session(db: sqlite3.Connection, workspace_id: str, app: str, session: str) -> None:
    db.execute(
        "UPDATE workspace_app_logins SET session = ?, updated_at = ? WHERE workspace_id = ? AND app = ?",
        (session, now(), workspace_id, app),
    )


def set_error(db: sqlite3.Connection, workspace_id: str, app: str, error: str | None) -> None:
    """A failed re-login keeps the old login; only its error is noted."""
    db.execute(
        "UPDATE workspace_app_logins SET error = ?, updated_at = ? WHERE workspace_id = ? AND app = ?",
        (error, now(), workspace_id, app),
    )


def key_sessions(db: sqlite3.Connection, app: str) -> list[sqlite3.Row]:
    """(workspace_id, session) of every workspace on this app through a project key."""
    return db.execute(
        "SELECT workspace_id, session FROM workspace_app_logins WHERE app = ? AND via = 'key'",
        (app,),
    ).fetchall()


def key_sessions_elsewhere(
    db: sqlite3.Connection, app: str, workspace_id: str
) -> list[sqlite3.Row]:
    """The same, of the other workspaces that still exist."""
    return db.execute(
        """SELECT l.workspace_id, l.session FROM workspace_app_logins l
             JOIN workspaces w ON w.id = l.workspace_id
           WHERE l.app = ? AND l.via = 'key' AND l.workspace_id != ?""",
        (app, workspace_id),
    ).fetchall()


def delete(db: sqlite3.Connection, workspace_id: str, app: str) -> None:
    db.execute(
        "DELETE FROM workspace_app_logins WHERE workspace_id = ? AND app = ?", (workspace_id, app)
    )


def delete_all(db: sqlite3.Connection, workspace_id: str) -> None:
    db.execute("DELETE FROM workspace_app_logins WHERE workspace_id = ?", (workspace_id,))
