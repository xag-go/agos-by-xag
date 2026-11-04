"""The last copies AGOS kept from before Hermes held each thing, checked before they go.

Every one-time move into Hermes ran on the live install at core start (or in a
loop) and emptied its rows as it went:
- `workspace_connectors` rows and a workspace's own MCP definitions (with sealed
  keys) → the root's Hermes config and .env (hermes_config.move_all);
- an agent row with its title, summary and definition → its member's Hermes
  profile (team.move_rows);
- a bot token AGOS kept (`channel_connections.secret`) → the workspace's .env;
- old copies of chat messages (`message_rows.legacy = 1`, and rows linked to a
  Hermes message by hermes_profile/hermes_session/hermes_uid) → Hermes's sessions
  (chat_store.move);
- `chats.title_told.<chat>` (a chat's old name given to Hermes once) and
  `owner.timezone` (→ Hermes's `timezone`) in app_settings.

Those moves are gone, and migration 101 (marked `-- agos: leftovers`) drops what
held them. First it checks every move is complete: when nothing is left, it writes
nothing. Anything still there is written, per workspace, to
`files/archive/leftovers-<date>.json` (the workspace's own folder, like the old
board's history; `system/old-board/<workspace>/` when that folder is missing)
before the rows and columns go. Sealed values stay sealed (they are written as
AGOS stored them). Nothing is lost; nothing is copied twice.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

MARK = "-- agos: leftovers"


def _has(db: sqlite3.Connection, table: str, column: str | None = None) -> bool:
    if column is None:
        return (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            is not None
        )
    return any(str(r[1]) == column for r in db.execute(f"PRAGMA table_info({table})"))


def _rows(db: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, args)
    names = [d[0] for d in cursor.description or []]
    return [dict(zip(names, row, strict=False)) for row in cursor.fetchall()]


def left(db: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """What the moves left behind (empty lists: every move is complete)."""
    found: dict[str, list[dict[str, Any]]] = {
        "connectors": [],
        "mcp_definitions": [],
        "agent_rows": [],
        "bot_tokens": [],
        "messages": [],
        "settings": [],
    }
    if _has(db, "workspace_connectors"):
        found["connectors"] = _rows(
            db,
            """SELECT c.*, l.kind AS item_kind, l.name AS item_name FROM workspace_connectors c
                 LEFT JOIN library_items l ON l.id = c.item_id ORDER BY c.workspace_id, c.item_id""",
        )
    found["mcp_definitions"] = _rows(
        db,
        """SELECT id, workspace_id, name, title, definition FROM library_items
            WHERE kind = 'mcp' AND workspace_id IS NOT NULL AND definition NOT IN ('{}', '')
            ORDER BY id""",
    )
    found["agent_rows"] = _rows(
        db,
        """SELECT id, workspace_id, name, title, summary, definition FROM library_items
            WHERE kind = 'agent' AND (title != '' OR definition NOT IN ('{}', ''))
            ORDER BY id""",
    )
    if _has(db, "channel_connections", "secret"):
        found["bot_tokens"] = _rows(
            db,
            """SELECT id, workspace_id, kind, name, secret AS sealed_token
                 FROM channel_connections WHERE secret != '' ORDER BY id""",
        )
    if _has(db, "message_rows", "legacy"):
        found["messages"] = _rows(
            db,
            """SELECT m.id, c.workspace_id, m.chat_id, m.author, m.body, m.created_at, m.speaker,
                      m.kind, m.hermes_profile, m.hermes_session, m.hermes_uid, m.legacy
                 FROM message_rows m LEFT JOIN chats c ON c.id = m.chat_id
                WHERE m.legacy = 1 OR m.hermes_uid IS NOT NULL ORDER BY m.id""",
        )
    # `chats.title_told.*` only marked a name as given (no data): it just goes.
    found["settings"] = _rows(
        db,
        "SELECT key, value, updated_at FROM app_settings WHERE key = 'owner.timezone'",
    )
    return found


def archive(db: sqlite3.Connection, data_root: Path | None) -> list[Path]:
    """Writes what is left per workspace before it goes; returns the files written
    (none when every move is complete). Raises OSError when a file can't be
    written: the migration then stops and nothing is dropped."""
    from agos_core.db import old_board

    found = left(db)
    if not any(found.values()):
        return []
    by_workspace: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for part, rows in found.items():
        for row in rows:
            ws = str(row.get("workspace_id") or "_owner")
            by_workspace.setdefault(ws, {k: [] for k in found})[part].append(row)
    written = []
    for ws, data in sorted(by_workspace.items()):
        data_out: dict[str, Any] = {
            "about": (
                "What AGOS still held from before Hermes kept it (connectors, agent rows, "
                "bot tokens, old message copies, old settings) when those copies went. "
                "Sealed values are as AGOS stored them."
            ),
            **data,
        }
        written.append(old_board._write(data_root, ws, "leftovers", data_out))
    return written
