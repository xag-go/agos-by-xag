"""Repository of `channel_connections`: each bot AGOS knows (a workspace's Telegram
bot is Hermes's own platform; AGOS keeps its name, its @name and which engine runs
it, never its token).

Owns the Channel service's reads and writes of channel_connections. Must not:
import actions or engine.
"""

import sqlite3

__all__ = [
    "add",
    "all_bots",
    "delete",
    "get",
    "hermes_bot_workspaces",
    "hermes_telegram",
    "hermes_telegram_workspaces",
    "of_workspace",
    "run_by",
    "set_identity",
    "set_name",
]


def all_bots(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM channel_connections ORDER BY id").fetchall()


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM channel_connections WHERE workspace_id = ? ORDER BY id", (workspace_id,)
    ).fetchall()


def get(db: sqlite3.Connection, connection_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM channel_connections WHERE id = ?", (connection_id,)
    ).fetchone()
    return row


def add(
    db: sqlite3.Connection,
    kind: str,
    name: str,
    identity: str | None,
    created_at: str,
    workspace_id: str | None,
) -> int:
    cursor = db.execute(
        """INSERT INTO channel_connections (kind, name, identity, created_at, workspace_id)
           VALUES (?, ?, ?, ?, ?)""",
        (kind, name, identity, created_at, workspace_id),
    )
    return int(cursor.lastrowid or 0)


def run_by(db: sqlite3.Connection, connection_id: int, engine: str) -> None:
    """Which engine receives the bot's messages ('hermes': the workspace's gateway)."""
    db.execute("UPDATE channel_connections SET engine = ? WHERE id = ?", (engine, connection_id))


def set_name(db: sqlite3.Connection, connection_id: int, name: str) -> None:
    db.execute("UPDATE channel_connections SET name = ? WHERE id = ?", (name, connection_id))


def set_identity(db: sqlite3.Connection, connection_id: int, identity: str) -> None:
    db.execute(
        "UPDATE channel_connections SET identity = ? WHERE id = ?", (identity, connection_id)
    )


def delete(db: sqlite3.Connection, connection_id: int) -> None:
    db.execute("DELETE FROM channel_connections WHERE id = ?", (connection_id,))


def hermes_telegram(
    db: sqlite3.Connection, workspace_id: str, engine: str, *, only_on: bool
) -> sqlite3.Row | None:
    """The workspace's first Telegram bot run by `engine` (`only_on`: while its bot
    switch is on)."""
    if only_on:
        sql = """SELECT * FROM channel_connections WHERE workspace_id = ? AND kind = 'telegram'
             AND engine = ? AND agos_bot_on(workspace_id) ORDER BY id LIMIT 1"""
    else:
        sql = """SELECT * FROM channel_connections WHERE workspace_id = ? AND kind = 'telegram'
             AND engine = ? ORDER BY id LIMIT 1"""
    row: sqlite3.Row | None = db.execute(sql, (workspace_id, engine)).fetchone()
    return row


def hermes_bot_workspaces(db: sqlite3.Connection, engine: str) -> list[str]:
    """The workspaces with a bot run by `engine` whose switch is on."""
    return [
        str(r["workspace_id"] or "")
        for r in db.execute(
            "SELECT DISTINCT workspace_id FROM channel_connections WHERE engine = ? AND agos_bot_on(workspace_id)",
            (engine,),
        ).fetchall()
    ]


def hermes_telegram_workspaces(db: sqlite3.Connection) -> list[str]:
    """The workspaces with a Telegram bot run by Hermes whose switch is on."""
    return [
        str(r["workspace_id"])
        for r in db.execute(
            """SELECT DISTINCT workspace_id FROM channel_connections
                 WHERE engine = 'hermes' AND agos_bot_on(workspace_id) AND kind = 'telegram'
                   AND workspace_id IS NOT NULL"""
        ).fetchall()
    ]
