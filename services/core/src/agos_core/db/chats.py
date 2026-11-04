"""Workspace chats: which workspace (and member) each belongs to, and what is shown.

A chat or a DM is a Hermes conversation (db/hermes_chats.py): its messages, their
order, each answer's steps, its title and model are Hermes's, read from the
workspace's own Hermes. AGOS keeps only what Hermes has no place for:

- the chat itself: its workspace, kind, agent, members, the member who owns it,
  its Kanban card (Hermes has no owner or workspace mapping);
- its attachments index (db/chat_attachments.py; the files are in the workspace's
  files);
- AGOS's own lines in it (its notices, Hermes's /command answers, which Hermes
  keeps in no transcript) and the owner's edits of older messages (Hermes has no
  edit in the middle of a conversation);
- the turn record of what Hermes has no place for: the answer working now, the
  approvals and notes in it, the owner's stop, an end Hermes never reported, its
  cards (actions/hermes_channel.py), and how it ended as Hermes's own
  `on_session_end` hook said (its turn_exit_reason, actions/hermes_channel.py
  `turn_ended`). Its model and tokens are Hermes's (its sessions, read by
  Hermes's usage analytics: engine.hermes_usage).

A group chat is a Hermes room: its lines are AGOS's room bridge (actions/rooms.py).

This module is the chats' repository (their rows) and a chat's name; AGOS's own
lines are db/chat_lines.py and the turn records db/chat_turns.py (both re-exported
here); what the owner sees of a chat, built from
these and Hermes's conversation, is actions/services/chat/view.py.
"""

import secrets
import sqlite3
from collections.abc import Callable
from typing import Any, Literal

from agos_core.db import chat_lines, group_rooms, hermes_inbox, sql
from agos_core.db import hermes_chats as hc
from agos_core.db.chat_lines import delete_message as delete_message
from agos_core.db.chat_lines import edit_owner_message as edit_owner_message
from agos_core.db.chat_lines import excerpt_in as excerpt_in
from agos_core.db.chat_lines import last_owner_line as last_owner_line
from agos_core.db.chat_lines import letters_of as letters_of
from agos_core.db.chat_lines import owner_line as owner_line
from agos_core.db.chat_lines import owner_messages as owner_messages
from agos_core.db.chat_lines import recent_agent_lines as recent_agent_lines
from agos_core.db.chat_lines import unanswered as unanswered
from agos_core.db.chat_lines import with_quote as with_quote
from agos_core.db.chat_turns import LIVE as LIVE
from agos_core.db.chat_turns import LIVE_SQL as LIVE_SQL
from agos_core.db.chat_turns import TurnRow as TurnRow
from agos_core.db.chat_turns import TurnStatus as TurnStatus
from agos_core.db.chat_turns import answered_up_to as answered_up_to
from agos_core.db.chat_turns import get_turn as get_turn
from agos_core.db.chat_turns import insert_turn as insert_turn
from agos_core.db.chat_turns import live_turn as live_turn
from agos_core.db.chat_turns import live_turns as live_turns
from agos_core.db.chat_turns import set_turn as set_turn
from agos_core.db.rows import dump_json, now

_LIVE_SQL = LIVE_SQL  # its old name (actions/hermes_channel.py reads it)
DEFAULT_TITLES = ("New session", "New chat")
AGOS_PREFIX = "agos:"


Author = Literal["owner", "agent"]


def is_hermes(row: sqlite3.Row) -> bool:
    """A chat whose conversation is Hermes's (every one but a group: a Hermes room)."""
    return str(row["kind"]) != "group"


# ---- where a chat lives in Hermes ---------------------------------------------------


def _telegram_places(db: sqlite3.Connection, row: sqlite3.Row) -> list[tuple[str, str]]:
    """(chat, thread) of the Telegram place Hermes answers this chat in itself: the
    Co-Founder's, or a member's topic that Hermes routes to the member's own profile
    (gateway.profile_routes, actions/member_topics.py)."""
    out = []
    for r in db.execute(
        """SELECT a.address FROM chat_addresses a JOIN channel_connections c
             ON c.id = a.connection_id
           WHERE a.chat_id = ? AND c.engine = 'hermes' AND agos_bot_on(c.workspace_id)
             AND c.kind = 'telegram' ORDER BY a.id""",
        (row["id"],),
    ):
        chat, _, thread = str(r["address"]).partition(":")
        out.append((chat, thread or "0"))
    return out


def where_of(db: sqlite3.Connection, row: sqlite3.Row) -> hc.Where | None:
    store = hc.store()
    if store is None or not is_hermes(row):
        return None
    workspace_id = str(row["workspace_id"])
    own = store.profile_of(workspace_id)
    profiles = [own]
    if row["agent"]:
        profiles.append(store.profile_of(f"{workspace_id}--a-{row['agent']}"))
    keys = [hc.archive_id(workspace_id, int(row["id"]))]
    if row["hermes_key"]:
        keys.append(str(row["hermes_key"]))
    return hc.Where(
        workspace_id=workspace_id,
        chat_id=int(row["id"]),
        profiles=tuple(profiles),
        own=own,
        keys=tuple(keys),
        telegram=tuple(_telegram_places(db, row)),
    )


def addresses(db: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
    """The agos platform's names of the chat's conversation (its queue items)."""
    out = [f"{AGOS_PREFIX}{row['id']}"]
    out += [f"{c}:{t}" for c, t in _telegram_places(db, row)]
    return out


# ---- a chat's name (the rest of what the owner sees: actions/services/chat/view.py) ---------


def command_mark(r: sqlite3.Row) -> bool:
    """A /command's turn record from before (it had no answer and nothing in it)."""
    return (
        r["status"] == "completed"
        and str(r["activity"] or "[]") in ("[]", '{"kept": []}', '{"kept":[]}')
        and r["reply_id"] is None
        and not r["error"]
        and str(r["via"] or "") == "hermes"
        and str(r["ended_at"] or "") == str(r["started_at"] or "")
    )


def pending_command(db: sqlite3.Connection, row: sqlite3.Row, command: str) -> str | None:
    """The words of a /command for this chat still in the queue (not in Hermes yet)."""
    found = hermes_inbox.pending_command_text(
        db, str(row["workspace_id"]), f"{AGOS_PREFIX}{row['id']}", command
    )
    return found[len(command) + 1 :].strip() if found else None


ROOM_NAME_CHARS = 200  # H: gateway/hosted_rooms.py:26 MAX_ROOM_NAME_CHARS


def room_name_of(chat_id: int, title: str) -> str:
    """The name a group's Hermes room has: its title and AGOS's own "· #<chat>" tag
    (one room per chat, so a room member's turn finds its chat by the name)."""
    tag = f" · #{int(chat_id)}"
    return f"{(title.strip() or 'Group')[: ROOM_NAME_CHARS - len(tag)]}{tag}"


def room_title(db: sqlite3.Connection, row: sqlite3.Row) -> str | None:
    """A group's name as its Hermes room holds it (H: gateway/hosted_rooms.py:88-91
    `name`, renamed by :913 rename_room), without AGOS's tag; None when Hermes holds
    no room for it."""
    store = hc.store()
    if store is None:
        return None
    room = group_rooms.room_of(db, int(row["id"]))
    if room is None:
        return None
    name = store.room_names(str(row["workspace_id"])).get(room)
    tag = f" · #{int(row['id'])}"
    if not name or not name.endswith(tag):
        return None
    return name[: -len(tag)]


# A DM's name is its partner's Hermes display name (the member profile's
# profile.yaml, H: hermes_cli/profiles.py:916 read_profile_meta); a card chat's is
# its Hermes Kanban card's title. agos-core sets these readers when it opens.
member_title_reader: Callable[[str, str], str] | None = None
card_title_reader: Callable[[str, str], str | None] | None = None
COFOUNDER_DM = "Co-Founder"


def dm_title(row: sqlite3.Row) -> str:
    """A DM's name: "Co-Founder", or its member's Hermes display name (a name AGOS
    still holds only for a member whose profile is gone, actions/team.py
    move_dm_titles)."""
    agent = str(row["agent"] or "")
    if not agent:
        return COFOUNDER_DM
    held = str(row["title"] or "")
    if held:
        return held
    if member_title_reader is not None:
        return member_title_reader(str(row["workspace_id"]), agent)
    return agent


def card_title(row: sqlite3.Row) -> str:
    """A card chat's name before its Hermes session has one: its card's Hermes title."""
    card = str(row["kanban_card"])
    found = card_title_reader(str(row["workspace_id"]), card) if card_title_reader else None
    return f"Card: {found}"[:200] if found else f"Card {card}"


def title_from(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    where: hc.Where | None,
    sessions: list[hc.Session] | None = None,
) -> str:
    """A chat's title is its Hermes session's title, a group's its Hermes room's name
    (AGOS holds either only until Hermes does); a DM's is its partner's Hermes
    display name; a card chat's its Hermes card's title until its session has one.
    `sessions`: the chat's Hermes sessions when the caller has read them already."""
    if row["kind"] == "group":
        return str(row["title"] or "") or room_title(db, row) or "Group"
    if row["kind"] == "dm":
        return dm_title(row)
    if row["kind"] != "chat":
        return str(row["title"])
    pending = pending_command(db, row, "/title")
    if pending:
        return pending
    store = hc.store()
    if store is not None and where is not None:
        found = store.title(where, sessions)
        if found:
            return found
    if row["kanban_card"]:
        return str(row["title"] or "") or card_title(row)
    return str(row["title"] or "") or DEFAULT_TITLES[0]


# A chat's own Full access is Hermes's /yolo of its conversation (actions/access.py):
# agos-core sets this reader when it opens.
access_reader: Callable[[str, int], bool] | None = None


ChatKind = Literal["chat", "dm", "group"]


def dm_row(db: sqlite3.Connection, workspace_id: str, agent: str | None) -> sqlite3.Row | None:
    """The DM with this agent (None = the Co-Founder), hidden or not."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM chats WHERE workspace_id = ? AND kind = 'dm' AND COALESCE(agent, '') = ?",
        (workspace_id, agent or ""),
    ).fetchone()
    return row


def unhide(db: sqlite3.Connection, chat_id: int) -> None:
    db.execute("UPDATE chats SET deleted_at = NULL WHERE id = ?", (chat_id,))


def set_members(
    db: sqlite3.Connection, workspace_id: str, chat_id: int, members: list[str]
) -> bool:
    return (
        db.execute(
            "UPDATE chats SET members = ? WHERE id = ? AND workspace_id = ? AND kind = 'group'",
            (dump_json(members), chat_id, workspace_id),
        ).rowcount
        > 0
    )


def chat_title(db: sqlite3.Connection, row: sqlite3.Row) -> str:
    """The name the owner sees (Hermes's session title for a chat)."""
    return title_from(db, row, where_of(db, row))


def title_of(db: sqlite3.Connection, chat_id: int) -> str:
    row = any_row(db, chat_id)
    return chat_title(db, row) if row is not None else ""


def hermes_key(db: sqlite3.Connection, chat_id: int) -> str:
    """The chat's Hermes session id from before the agos platform (kept: Hermes
    takes the conversation on in it)."""
    row = db.execute("SELECT hermes_key FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return str(row["hermes_key"]) if row and row["hermes_key"] else f"agos-chat-{chat_id}"


def any_row(db: sqlite3.Connection, chat_id: int) -> sqlite3.Row | None:
    """The chat's row, hidden or not, in any workspace (callers check the workspace)."""
    row: sqlite3.Row | None = db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return row


def in_workspace(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> sqlite3.Row | None:
    """The chat's row when it is this workspace's, hidden or not."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM chats WHERE id = ? AND workspace_id = ?", (chat_id, workspace_id)
    ).fetchone()
    return row


def visible_workspace_of(db: sqlite3.Connection, chat_id: int) -> str | None:
    """The workspace of a chat that is not hidden; None otherwise."""
    row = db.execute(
        "SELECT workspace_id FROM chats WHERE id = ? AND NOT agos_hidden(id, workspace_id, kind, deleted_at)",
        (chat_id,),
    ).fetchone()
    return str(row["workspace_id"]) if row is not None else None


def cofounder_chat_id(
    db: sqlite3.Connection, workspace_id: str, *, hidden: bool = False
) -> int | None:
    """The workspace's Co-Founder DM (the oldest; `hidden`: a hidden one counts too)."""
    if hidden:
        row = db.execute(
            "SELECT id FROM chats WHERE workspace_id = ? AND kind = 'dm' AND agent IS NULL",
            (workspace_id,),
        ).fetchone()
    else:
        row = db.execute(
            """SELECT id FROM chats WHERE workspace_id = ? AND kind = 'dm' AND agent IS NULL
                 AND NOT agos_hidden(id, workspace_id, kind, deleted_at) ORDER BY id LIMIT 1""",
            (workspace_id,),
        ).fetchone()
    return int(row["id"]) if row is not None else None


def visible_row(db: sqlite3.Connection, chat_id: int) -> sqlite3.Row | None:
    """The chat's row in any workspace, when it is not hidden."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM chats WHERE id = ? AND NOT agos_hidden(id, workspace_id, kind, deleted_at)",
        (chat_id,),
    ).fetchone()
    return row


def drop_held_title(db: sqlite3.Connection, chat_id: int) -> None:
    """AGOS's copy of a group's name goes (its Hermes room holds it)."""
    db.execute("UPDATE chats SET title = '' WHERE id = ?", (chat_id,))


def hold_title(db: sqlite3.Connection, chat_id: int, title: str) -> None:
    """A group's name is AGOS's again until its new room holds it (unless it has one)."""
    db.execute("UPDATE chats SET title = ? WHERE id = ? AND title = ''", (title, chat_id))


def of_workspace(
    db: sqlite3.Connection, workspace_id: str, chat_id: int | None = None
) -> list[sqlite3.Row]:
    """The workspace's chats but its groups (hidden ones too); `chat_id`: only that one."""
    if chat_id is None:
        return db.execute(
            "SELECT * FROM chats WHERE workspace_id = ? AND kind != 'group'", (workspace_id,)
        ).fetchall()
    return db.execute(
        "SELECT * FROM chats WHERE workspace_id = ? AND kind != 'group' AND id = ?",
        (workspace_id, chat_id),
    ).fetchall()


def hidden_by_agos(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Chats (not groups) AGOS's own mark hides (deleted_at set)."""
    return db.execute(
        "SELECT * FROM chats WHERE deleted_at IS NOT NULL AND kind != 'group'"
    ).fetchall()


def drop_title_copy(db: sqlite3.Connection, chat_id: int, title: str | None) -> None:
    """AGOS's copy of a chat's title goes (unless it changed meanwhile)."""
    db.execute("UPDATE chats SET title = '' WHERE id = ? AND title = ?", (chat_id, title))


def listed(db: sqlite3.Connection, workspace_id: str, kinds: tuple[str, ...]) -> list[sqlite3.Row]:
    """The workspace's visible chats of these kinds, newest first; a Kanban card's own
    chat lives inside its card, not in the lists."""
    return db.execute(
        sql.text(
            """SELECT * FROM chats WHERE workspace_id = ? AND NOT agos_hidden(id, workspace_id, kind, deleted_at)
            AND kanban_card IS NULL
            AND kind IN ({kinds}) ORDER BY id DESC""",
            kinds=sql.marks(len(kinds)),
        ),
        (workspace_id, *kinds),
    ).fetchall()


def workspace_of(db: sqlite3.Connection, chat_id: int) -> str | None:
    """The workspace a chat is in (hidden or not); None when there is no such chat."""
    row = db.execute("SELECT workspace_id FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return str(row["workspace_id"]) if row is not None else None


def chat_row(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM chats WHERE id = ? AND workspace_id = ? AND NOT agos_hidden(id, workspace_id, kind, deleted_at)",
        (chat_id, workspace_id),
    ).fetchone()
    return row


def insert_chat(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    title: str,
    channel: Literal["web", "telegram"],
    kind: ChatKind = "chat",
    agent: str | None = None,
    members: list[str] | None = None,
) -> int:
    """A new chat. A chat's name is kept here only until its Hermes session has it
    (Hermes's /title goes with his first message, actions/hermes_channel.py); its
    model is the workspace's until he picks one (Hermes's /model). A DM has no name
    of its own (its partner's Hermes display name, dm_title); a group's is held
    until its Hermes room has it."""
    at = now()
    cursor = db.execute(
        """INSERT INTO chats (workspace_id, title, channel, created_at, updated_at,
                              hermes_key, kind, agent, members)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            title,
            channel,
            at,
            at,
            f"agos-chat-{secrets.token_hex(8)}",
            kind,
            agent,
            dump_json(members or []),
        ),
    )
    return int(cursor.lastrowid or 0)


def update_chat(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_id: int,
    *,
    title: str | None = None,
    agent: str | None = None,
) -> bool:
    """AGOS's own fields of a chat (a chat's title is Hermes's once its session has
    it; a DM's or a group's title is AGOS's). Its model is Hermes's own /model for
    its conversation (actions/chat.py set_model)."""
    sets: list[str] = []
    values: list[str | None] = []
    if agent is not None:
        # "" clears it (back to the workspace's own agent).
        sets.append("agent = ?")
        values.append(agent or None)
    if title is not None:
        sets.append("title = ?")
        values.append(title)
    if not sets:
        return chat_row(db, workspace_id, chat_id) is not None
    return (
        db.execute(
            f"UPDATE chats SET {', '.join(sets)} WHERE id = ? AND workspace_id = ?",
            (*values, chat_id, workspace_id),
        ).rowcount
        > 0
    )


def delete_chat(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> bool:
    return (
        db.execute(
            "UPDATE chats SET deleted_at = ? WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (now(), chat_id, workspace_id),
        ).rowcount
        > 0
    )


def add_chat_message(
    db: sqlite3.Connection,
    workspace_id: str,
    chat_id: int,
    author: Author,
    body: str,
    speaker: str | None = None,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int | None:
    """One of AGOS's own lines (a room's, or AGOS's notice in a chat): the new row's
    id, or None when the chat isn't in this workspace. Written through the Chat
    service (actions/services/chat/chat_writes.py), which rings the send round.
    `reply_excerpt`: the part of the replied message the owner selected; kept only
    when it really is a piece of that message (db/chat_lines.py add_line)."""
    at = now()
    if (
        db.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ? AND workspace_id = ?",
            (at, chat_id, workspace_id),
        ).rowcount
        == 0
    ):
        return None
    return chat_lines.add_line(db, chat_id, author, body, at, speaker, reply_to, reply_excerpt)


def search_chats(db: sqlite3.Connection, workspace_id: str, query: str) -> list[dict[str, Any]]:
    """Messages matching every word, newest first: Hermes's own full-text index of
    the workspace's conversations (a chat's AGOS-own lines are not searched)."""
    store = hc.store()
    if store is None:
        return []
    chats = {
        int(r["id"]): r
        for r in db.execute(
            """SELECT * FROM chats WHERE workspace_id = ? AND NOT agos_hidden(id, workspace_id, kind, deleted_at)
                 AND kind = 'chat' AND kanban_card IS NULL""",
            (workspace_id,),
        )
    }
    by_key = {str(r["hermes_key"]): i for i, r in chats.items() if r["hermes_key"]}
    by_key.update({hc.archive_id(workspace_id, i): i for i in chats})
    by_place: dict[tuple[str, str], int] = {}
    for i, r in chats.items():
        for place in _telegram_places(db, r):
            by_place[place] = i
    out: list[dict[str, Any]] = []
    for chat_ref, session, line in store.search(workspace_id, query):
        chat_id = by_key.get(session)
        if chat_id is None and chat_ref.isdigit():
            chat_id = int(chat_ref) if int(chat_ref) in chats else None
        if chat_id is None:
            chat_id = next((i for (c, _t), i in by_place.items() if c == chat_ref), None)
        if chat_id is None:
            continue
        body = line.content
        if line.role == "user":
            said = hc.owner_words(line)
            if said is None:
                continue
            body = said.body or said.voice or ""
        out.append(
            {
                "chatId": chat_id,
                "chatTitle": chat_title(db, chats[chat_id]),
                "messageId": line.id,
                "from": "owner" if line.role == "user" else "agent",
                "body": body,
            }
        )
        if len(out) >= 30:
            break
    return out


def queued(db: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """He sent something Hermes hasn't taken yet (the agos platform's queue)."""
    names = addresses(db, row)
    return hermes_inbox.waiting_message(db, str(row["workspace_id"]), names)


# ---- a room's turns (AGOS's room bridge: its own messages: db/chat_lines.py) ----------


def chats_waiting(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rooms with owner lines newer than their last turn, and no live turn."""
    return list(
        db.execute(
            sql.text(
                """SELECT c.* FROM chats c
                WHERE NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at) AND c.kind = 'group' AND EXISTS (
                  SELECT 1 FROM messages m WHERE m.chat_id = c.id AND m.author = 'owner'
                    AND m.id > COALESCE((SELECT MAX(asked_up_to) FROM chat_turns t
                                         WHERE t.chat_id = c.id), 0))
                  AND NOT EXISTS (
                  SELECT 1 FROM chat_turns t WHERE t.chat_id = c.id AND t.status IN ({live}))
                ORDER BY c.id""",
                live=LIVE_SQL,
            ),
            LIVE,
        )
    )


# ---- a Kanban card's own chat (actions/services/board/card_chats.py) -----------------


def member_card_chat(
    db: sqlite3.Connection, workspace_id: str, card_id: str, who: str
) -> int | None:
    """A member's own (visible) chat about one Kanban card."""
    row = db.execute(
        """SELECT id FROM chats WHERE workspace_id = ? AND kanban_card = ? AND agent = ?
             AND NOT agos_hidden(id, workspace_id, kind, deleted_at) ORDER BY id LIMIT 1""",
        (workspace_id, card_id, who),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def add_member_card_chat(db: sqlite3.Connection, workspace_id: str, card_id: str, who: str) -> int:
    """A member's new web chat about one Kanban card."""
    return int(
        db.execute(
            """INSERT INTO chats (workspace_id, title, kind, agent, channel, kanban_card,
                 created_at, updated_at) VALUES (?, '', 'chat', ?, 'web', ?, ?, ?)""",
            (workspace_id, who, card_id, now(), now()),
        ).lastrowid
        or 0
    )


def card_chat_id(db: sqlite3.Connection, workspace_id: str, card: str, agent: str) -> int | None:
    """The card's chat with this member (not hidden); None when not made yet."""
    row = db.execute(
        """SELECT id FROM chats WHERE workspace_id = ? AND kanban_card = ?
             AND COALESCE(agent, '') = ?
             AND NOT agos_hidden(id, workspace_id, kind, deleted_at)""",
        (workspace_id, card, agent),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def insert_card_chat(db: sqlite3.Connection, workspace_id: str, agent: str, card: str) -> int:
    """A card's chat with its member: no name of its own (the Hermes card's title,
    card_title)."""
    at = now()
    return int(
        db.execute(
            """INSERT INTO chats (workspace_id, title, kind, agent, channel,
                 kanban_card, created_at, updated_at)
               VALUES (?, ?, 'chat', ?, 'web', ?, ?, ?)""",
            (workspace_id, "", agent, card, at, at),
        ).lastrowid
        or 0
    )


def card_chats_titled(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Card chats that still hold a copy of their card's title."""
    return db.execute(
        "SELECT id, workspace_id, kanban_card, title FROM chats "
        "WHERE kanban_card IS NOT NULL AND title != ''"
    ).fetchall()


def clear_copied_title(db: sqlite3.Connection, chat_id: int, title: str) -> None:
    """The copy goes (unless the title changed meanwhile)."""
    db.execute("UPDATE chats SET title = '' WHERE id = ? AND title = ?", (chat_id, title))


def groups_of(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """(id, title) of the workspace's group chats, hidden ones too."""
    return db.execute(
        "SELECT id, title FROM chats WHERE workspace_id = ? AND kind = 'group'", (workspace_id,)
    ).fetchall()


def titled_dms(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """DMs (every workspace) that still hold a name of their own."""
    return db.execute(
        "SELECT id, workspace_id, agent, title FROM chats WHERE kind = 'dm' AND title != ''"
    ).fetchall()
