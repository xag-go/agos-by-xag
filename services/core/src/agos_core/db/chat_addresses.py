"""Repository of `chat_addresses`: where each AGOS chat lives on a workspace's bot
(a Telegram chat or topic: "<chat id>:<topic id>"), and which one gets the board's
notifications.

Owns every read and write of chat_addresses (with the joins that name a place's
chat, workspace or bot). The Channel service decides which address a chat gets.
Must not: import actions or engine.
"""

import sqlite3

from agos_core.db.rows import now

__all__ = [
    "add",
    "chat_of",
    "dm_has_place",
    "group_members_on_bots",
    "has_notify",
    "hermes_place",
    "linked_chats",
    "member_dm_places",
    "notify_off",
    "of_chat",
    "places_on_bots",
    "remove",
    "remove_place",
    "taken_by",
    "target",
    "visible_addresses",
    "workspaces_at",
]


def taken_by(db: sqlite3.Connection, connection_id: int, address: str) -> int | None:
    """The chat that has this address on this bot, if any."""
    row = db.execute(
        "SELECT chat_id FROM chat_addresses WHERE connection_id = ? AND address = ?",
        (connection_id, address),
    ).fetchone()
    return int(row["chat_id"]) if row is not None else None


def chat_of(db: sqlite3.Connection, connection_id: int, address: str) -> int | None:
    """The AGOS chat linked to this place of the bot (read only)."""
    return taken_by(db, connection_id, address)


def has_notify(db: sqlite3.Connection, workspace_id: str) -> bool:
    """One of the workspace's chats gets the board's notifications already."""
    return (
        db.execute(
            """SELECT 1 FROM chat_addresses WHERE notify = 1 AND chat_id IN
                 (SELECT id FROM chats WHERE workspace_id = ?)""",
            (workspace_id,),
        ).fetchone()
        is not None
    )


def notify_off(db: sqlite3.Connection, workspace_id: str) -> None:
    """No chat of the workspace gets the notifications (one is set right after)."""
    db.execute(
        """UPDATE chat_addresses SET notify = 0 WHERE chat_id IN
             (SELECT id FROM chats WHERE workspace_id = ?)""",
        (workspace_id,),
    )


def add(
    db: sqlite3.Connection, chat_id: int, connection_id: int, address: str, notify: bool
) -> int:
    cursor = db.execute(
        """INSERT INTO chat_addresses (chat_id, connection_id, address, notify, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (chat_id, connection_id, address, int(notify), now()),
    )
    return int(cursor.lastrowid or 0)


def remove(db: sqlite3.Connection, workspace_id: str, chat_id: int, address_id: int) -> int:
    """One of a chat's addresses goes (only the workspace's own); how many went."""
    return db.execute(
        """DELETE FROM chat_addresses WHERE id = ? AND chat_id = ? AND chat_id IN
             (SELECT id FROM chats WHERE workspace_id = ?)""",
        (address_id, chat_id, workspace_id),
    ).rowcount


def remove_place(db: sqlite3.Connection, connection_id: int, address: str) -> None:
    """The place goes from whichever chat had it (a person removed from the bot)."""
    db.execute(
        "DELETE FROM chat_addresses WHERE connection_id = ? AND address = ?",
        (connection_id, address),
    )


def of_chat(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """A chat's addresses with their bot (its name, kind, workspace, engine)."""
    return db.execute(
        """SELECT a.*, c.name AS cname, c.kind, c.workspace_id, c.engine
           FROM chat_addresses a JOIN channel_connections c ON c.id = a.connection_id
           WHERE a.chat_id = ? ORDER BY a.id""",
        (chat_id,),
    ).fetchall()


def places_on_bots(db: sqlite3.Connection, chat_id: int) -> list[tuple[int, str]]:
    """(bot, address) of a chat's places on bots that are on."""
    rows = db.execute(
        """SELECT DISTINCT a.connection_id, a.address FROM chat_addresses a
           JOIN channel_connections k ON k.id = a.connection_id AND agos_bot_on(k.workspace_id)
           WHERE a.chat_id = ?""",
        (chat_id,),
    ).fetchall()
    return [(int(r["connection_id"]), str(r["address"])) for r in rows]


def target(db: sqlite3.Connection, connection_id: int, address: str) -> sqlite3.Row | None:
    """The chat (and its workspace, archived or not) a bot's place is linked to; none
    for a hidden chat or a deleted workspace."""
    row: sqlite3.Row | None = db.execute(
        """SELECT a.chat_id, c.workspace_id, w.archived_at FROM chat_addresses a
    JOIN chats c ON c.id = a.chat_id JOIN workspaces w ON w.id = c.workspace_id
    WHERE a.connection_id = ? AND a.address = ? AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at)
      AND w.deleted_at IS NULL""",
        (connection_id, address),
    ).fetchone()
    return row


def workspaces_at(db: sqlite3.Connection, connection_id: int, address: str) -> set[str]:
    """The workspaces whose chats are linked to this place of the bot."""
    return {
        str(r["workspace_id"])
        for r in db.execute(
            """SELECT c.workspace_id FROM chat_addresses a JOIN chats c ON c.id = a.chat_id
               WHERE a.connection_id = ? AND a.address = ?""",
            (connection_id, address),
        )
    }


def linked_chats(db: sqlite3.Connection, connection_id: int) -> list[sqlite3.Row]:
    """Each place of the bot linked to a visible chat: the address and the chat's row."""
    return db.execute(
        """SELECT a.address, c.* FROM chat_addresses a JOIN chats c ON c.id = a.chat_id
           WHERE a.connection_id = ? AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at)""",
        (connection_id,),
    ).fetchall()


def hermes_place(db: sqlite3.Connection, chat_id: int, engine: str) -> sqlite3.Row | None:
    """The chat's first Telegram place on a bot run by Hermes (`engine`), bot on;
    never a group's (a Hermes room has no Telegram)."""
    row: sqlite3.Row | None = db.execute(
        """SELECT a.address, a.connection_id FROM chat_addresses a
             JOIN channel_connections c ON c.id = a.connection_id
             JOIN chats ch ON ch.id = a.chat_id
           WHERE a.chat_id = ? AND c.engine = ? AND agos_bot_on(c.workspace_id) AND c.kind = 'telegram'
             AND ch.kind != 'group'
           ORDER BY a.id LIMIT 1""",
        (chat_id, engine),
    ).fetchone()
    return row


def group_members_on_bots(db: sqlite3.Connection, workspace_id: str, engine: str) -> list[str]:
    """The members lists (JSON) of the workspace's visible groups linked to a
    Telegram group on a bot run by `engine`, bot on."""
    return [
        str(r["members"])
        for r in db.execute(
            """SELECT DISTINCT c.members FROM chat_addresses a
                 JOIN chats c ON c.id = a.chat_id
                 JOIN channel_connections k ON k.id = a.connection_id
               WHERE c.kind = 'group' AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at) AND agos_bot_on(k.workspace_id)
                 AND k.engine = ? AND a.address LIKE '-%' AND c.workspace_id = ?""",
            (engine, workspace_id),
        ).fetchall()
    ]


def member_dm_places(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """(address, id, agent) of the workspace's visible member chats (DMs and chats with
    an agent, not groups) linked to a Telegram place on a Hermes bot that is on."""
    return db.execute(
        """SELECT a.address, c.id, c.agent FROM chat_addresses a
             JOIN chats c ON c.id = a.chat_id
             JOIN channel_connections k ON k.id = a.connection_id
           WHERE c.workspace_id = ? AND c.kind != 'group' AND c.agent IS NOT NULL
             AND c.agent != '' AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at) AND k.engine = 'hermes'
             AND agos_bot_on(k.workspace_id) AND k.kind = 'telegram'
           ORDER BY a.id""",
        (workspace_id,),
    ).fetchall()


def visible_addresses(db: sqlite3.Connection, workspace_id: str) -> list[str]:
    """Every place of the workspace's visible chats."""
    return [
        str(r["address"])
        for r in db.execute(
            """SELECT a.address FROM chat_addresses a JOIN chats c ON c.id = a.chat_id
                 WHERE c.workspace_id = ? AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at)""",
            (workspace_id,),
        ).fetchall()
    ]


def dm_has_place(db: sqlite3.Connection, workspace_id: str, member: str) -> bool:
    """The member's DM has an address on a bot (its Telegram topic)."""
    row = db.execute(
        """SELECT 1 FROM chat_addresses a JOIN chats c ON c.id = a.chat_id
           WHERE c.workspace_id = ? AND c.kind = 'dm' AND c.agent = ? LIMIT 1""",
        (workspace_id, member),
    ).fetchone()
    return row is not None
