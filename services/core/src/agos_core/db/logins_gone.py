"""The logins AGOS had before it became single-user, gone once (migration 141).

AGOS opens with no login: it listens only on this machine, and another device
reaches it only through the owner's Tailscale (apps/web/src/server/access.ts). The
owner's password, the browser sessions, the failed sign-ins and the people he
shared workspaces with (members, invite links, their workspaces) had no reader
left. Before those tables go, the one thing worth keeping is copied: the owner's
name, into the plain `owner.name` setting (Settings → General), unless he already
set one there. Member chats (a member's own conversations, in his own Hermes
profile) go to the trash like a deleted chat; the `chats` table loses its two
member columns. A second run finds no `owner` table and writes nothing.
"""

from __future__ import annotations

import sqlite3

from agos_core.db.rows import dump_json, now

MARK = "-- agos: logins-gone"
NAME_KEY = "owner.name"  # actions/founder.py NAME_KEY


def keep_owner_name(db: sqlite3.Connection) -> None:
    has_owner = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'owner'"
    ).fetchone()
    if has_owner is None:
        return
    row = db.execute("SELECT name FROM owner WHERE id = 1").fetchone()
    name = " ".join(str(row[0] or "").split())[:64] if row else ""
    if not name:
        return
    # An empty saved name meant "my account's name": it becomes that name too.
    db.execute(
        """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
           WHERE app_settings.value IN ('""', 'null')""",
        (NAME_KEY, dump_json(name), now()),
    )
