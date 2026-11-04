"""A group chat as a Hermes room: is it one, its address and Hermes name, its roster, who speaks, the event ids.
Must not: send anything to the room.

Split out of agos_core.actions.rooms (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db import group_rooms

__all__ = [
    "COFOUNDER",
    "MAX_MEMBERS",
    "RECAP_CHARS",
    "ROOM_KINDS",
    "ROOM_PREFIX",
    "SPEAKER_AGOS",
    "THREAD",
    "VIA",
    "address",
    "chat_of",
    "chat_of_room",
    "hermes_event_id",
    "is_room_chat",
    "mentions",
    "on",
    "room_name",
    "roster",
]

log = logging.getLogger("agos.rooms")

ROOM_PREFIX = "room:"
COFOUNDER = "cofounder"  # the Co-Founder's handle and member id in every room
THREAD = "main"
RECAP_CHARS = 6000
MAX_MEMBERS = 5  # Hermes rooms hold 2-6: the Co-Founder and up to five members
ROOM_KINDS = ("room-sync", "room-send", "room-stop", "room-approve", "room-rename")
VIA = "room"
SPEAKER_AGOS = "AGOS"  # AGOS's own notes in the chat (a failed turn, a member picked)


# ---- which chats are rooms ------------------------------------------------------------


def on(core: Core, workspace_id: str) -> bool:
    """The workspace's group chats are Hermes rooms (every workspace runs on its own
    root, ADR 0020): whenever there is an engine."""
    del workspace_id
    return core.engine is not None


def is_room_chat(core: Core, workspace_id: str, chat_id: int) -> bool:
    row = chats_repo.chat_row(core.db, workspace_id, chat_id)
    return row is not None and row["kind"] == "group" and on(core, workspace_id)


def address(chat_id: int) -> str:
    return f"{ROOM_PREFIX}{int(chat_id)}"


def chat_of(core: Core, workspace_id: str, value: str) -> int | None:
    """The group chat behind "room:<chat>" — only one of THIS workspace's."""
    found = re.fullmatch(r"room:(\d{1,12})", value or "")
    if found is None:
        return None
    chat_id = int(found.group(1))
    return chat_id if is_room_chat(core, workspace_id, chat_id) else None


def _room_row(core: Core, workspace_id: str, chat_id: int) -> Any:
    return group_rooms.get(core.db, workspace_id, chat_id)


def chat_of_room(core: Core, workspace_id: str, room_id: str) -> int | None:
    return group_rooms.chat_of_room(core.db, workspace_id, room_id)


# ---- the roster ------------------------------------------------------------------------


def roster(core: Core, workspace_id: str, chat_id: int) -> list[dict[str, str]]:
    """The room's members: the Co-Founder first, then the group's members that have
    their own profile in the workspace's root (never anyone else's)."""
    from agos_core.actions import agent_profiles, voice

    assert core.engine is not None
    row = chats_repo.in_workspace(core.db, workspace_id, chat_id)
    names = json.loads(row["members"] or "[]") if row is not None else []
    out = [
        {
            "member_id": COFOUNDER,
            "profile": "default",
            "handle": COFOUNDER,
            "display_name": "Co-Founder",
        }
    ]
    for name in names:
        name = str(name)
        if name == COFOUNDER or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name):
            continue
        if not agent_profiles.ready(core, workspace_id, name):
            continue
        key = agent_profiles.key(workspace_id, name)
        out.append(
            {
                "member_id": name,
                "profile": core.engine.hermes_name(key),
                "handle": name,
                "display_name": voice.name_of(core, workspace_id, name)[:120],
            }
        )
        if len(out) > MAX_MEMBERS:
            break
    return out


def _digest(members: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()


def room_name(core: Core, chat_id: int) -> str:
    """The name the group's room should have: its name as shown (Hermes's room's own,
    or AGOS's until the room holds it) and AGOS's tag."""
    from agos_core.db import chats as repo

    return repo.room_name_of(chat_id, repo.title_of(core.db, chat_id))


def _hermes_name(core: Core, workspace_id: str, room_id: str) -> str | None:
    """The room's name as Hermes holds it now (None: no such room in Hermes)."""
    from agos_core.db import hermes_chats as hc

    store = hc.store()
    return store.room_names(workspace_id).get(room_id) if store is not None else None


def hermes_event_id(client_event_id: str) -> str:
    """The id Hermes gives an owner message sent with this client id (Hermes's
    hosted_rooms.user_event_id); the plugin reports the real one when it is sent."""
    return f"user:{hashlib.sha256(client_event_id.encode('utf-8')).hexdigest()}"


# ---- his message → the room --------------------------------------------------------------


def mentions(text: str, handles: list[str]) -> bool:
    """The text @mentions one of these members (or everyone)."""
    named = {h.lower() for h in re.findall(r"@([A-Za-z0-9][A-Za-z0-9._:-]*)", text)}
    return bool(named & ({h.lower() for h in handles} | {"all", "everyone"}))


def _speaker(member_id: str) -> str | None:
    # "manager": the handle before step 44 (a room made before it, until remade)
    return None if member_id in ("", COFOUNDER, "manager") else member_id
