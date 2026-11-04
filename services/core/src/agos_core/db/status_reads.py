"""The rows the System service's pages read from other services' tables.

Owns: the read-only queries of the workspace Log (newest first, before a time, a
page's worth per source: activity, cofounder_actions, capability_requests,
channel_outbox, channel_connections, system_log, automations, chat_turns) and of the
Dashboard (the workspace's bots).

Must not: write. Each of these tables has its own writer (db/ownership); this is the
read side of the Log and the Dashboard only.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    "activity",
    "automation_jobs",
    "automation_names",
    "bot_connections",
    "capability_results",
    "cofounder_actions",
    "day_ago",
    "failed_turns",
    "outbox",
    "system_log",
]

Rows = list[sqlite3.Row]


def activity(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    return db.execute(
        """SELECT a.id, a.kind, a.text, a.created_at FROM activity a
           WHERE a.workspace_id = ? AND a.created_at < ? ORDER BY a.id DESC LIMIT ?""",
        (ws, before, limit),
    ).fetchall()


def cofounder_actions(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    return db.execute(
        """SELECT id, chat_id, title, status, error, COALESCE(decided_at, created_at) AS at
           FROM cofounder_actions WHERE workspace_id = ? AND COALESCE(decided_at, created_at) < ?
           ORDER BY id DESC LIMIT ?""",
        (ws, before, limit),
    ).fetchall()


def capability_results(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    return db.execute(
        """SELECT id, title, kind, status, error, created_at FROM capability_requests
           WHERE workspace_id = ? AND created_at < ? AND status IN ('failed','done')
           ORDER BY id DESC LIMIT ?""",
        (ws, before, limit),
    ).fetchall()


def outbox(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    return db.execute(
        """SELECT o.id, o.body, o.error, o.attempts, o.sent_id, o.created_at,
                  k.name, k.kind
           FROM channel_outbox o JOIN channel_connections k ON k.id = o.connection_id
           WHERE k.workspace_id = ? AND o.created_at < ? ORDER BY o.id DESC LIMIT ?""",
        (ws, before, limit),
    ).fetchall()


def bot_connections(db: sqlite3.Connection, ws: str) -> Rows:
    """The workspace's channel connections whose AGOS bot is on, oldest first."""
    return db.execute(
        "SELECT * FROM channel_connections WHERE agos_bot_on(workspace_id) AND workspace_id = ?"
        " ORDER BY id",
        (ws,),
    ).fetchall()


def system_log(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    """AGOS's own errors: this workspace's and the whole app's."""
    return db.execute(
        """SELECT id, level, source, text, created_at, workspace_id FROM system_log
           WHERE (workspace_id = ? OR workspace_id IS NULL) AND created_at < ?
           ORDER BY id DESC LIMIT ?""",
        (ws, before, limit),
    ).fetchall()


def automation_names(db: sqlite3.Connection, ws: str) -> Rows:
    return db.execute("SELECT id, name FROM automations WHERE workspace_id = ?", (ws,)).fetchall()


def automation_jobs(db: sqlite3.Connection, ws: str) -> Rows:
    """The workspace's automations that have their Hermes cron job."""
    return db.execute(
        "SELECT id, name, hermes_job_id FROM automations "
        "WHERE workspace_id = ? AND hermes_job_id IS NOT NULL",
        (ws,),
    ).fetchall()


def failed_turns(db: sqlite3.Connection, ws: str, before: str, limit: int) -> Rows:
    """The workspace's chat turns Hermes ended without an answer, with their chat."""
    return db.execute(
        """SELECT t.id AS turn_id, t.error AS turn_error,
                  COALESCE(t.ended_at, t.started_at) AS turn_at, c.*
             FROM chat_turns t JOIN chats c ON c.id = t.chat_id
            WHERE t.workspace_id = ? AND c.workspace_id = ? AND t.status = 'failed'
              AND COALESCE(t.ended_at, t.started_at) < ?
            ORDER BY turn_at DESC, turn_id DESC LIMIT ?""",
        (ws, ws, before, limit),
    ).fetchall()


def day_ago(db: sqlite3.Connection) -> str:
    """This moment a day ago, in the database's own time format."""
    return str(db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')").fetchone()[0])
