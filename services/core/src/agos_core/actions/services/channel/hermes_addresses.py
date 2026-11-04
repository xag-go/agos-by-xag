"""AGOS's conversations as Hermes addresses: the "agos:<chat>" format, the AGOS chat
behind an address (an AGOS conversation, a linked Telegram chat), the member whose
profile answers it, its Hermes session, and the mark on AGOS's mirrored text.

Owns: address <-> chat/member resolution (read only).
Must not: write chats or messages, or talk to Hermes.

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from agos_core.actions.services.channel import gateway_platform
from agos_core.context import Core
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import chat_turns
from agos_core.db import chats as repo

__all__ = [
    "AGOS_PREFIX",
    "AGOS_TOOL_RULE",
    "MIRROR_MARK",
    "address_of",
    "chat_at",
    "chat_of_address",
    "chat_on_hermes",
    "owner_member",
    "split_agos",
]


# Every chat of a workspace on it is a conversation of the workspace's Hermes gateway,
# like a Telegram chat: Hermes's commands, busy steer/queue, approvals, voice notes…
# AGOS is only the window (the agos-guard plugin's platform adapter carries messages).

AGOS_PREFIX = "agos:"
# Hermes's pattern key on the Allow / Deny card of one of AGOS's own tools.
AGOS_TOOL_RULE = "plugin_rule:agos:agos_"


def _platform_chat(core: Core, workspace_id: str, chat_id: int) -> bool:
    """A chat that lives on the workspace's Hermes as an AGOS conversation (all of
    them: every AGOS chat is a conversation of the workspace's Hermes)."""
    return repo.chat_row(core.db, workspace_id, chat_id) is not None


# An AGOS conversation on the agos platform: "agos:<chat>" (a ".<member>" part, from
# the group chats before Hermes rooms, is still read).
_AGOS_ADDRESS = re.compile(r"agos:(\d{1,12})(?:\.([A-Za-z0-9_-]{1,64}))?")


def split_agos(address: str) -> tuple[int, str | None] | None:
    """(chat id, member or None for the Co-Founder / a plain chat) of an AGOS address."""
    m = _AGOS_ADDRESS.fullmatch(address)
    return (int(m.group(1)), m.group(2)) if m else None


def chat_at(core: Core, workspace_id: str, address: str) -> int | None:
    """The AGOS chat behind a Hermes address (an AGOS conversation or a Telegram chat)."""
    if address.startswith("room:"):  # a group's Hermes room (ADR 0020), this workspace's
        from agos_core.actions import rooms

        return rooms.chat_of(core, workspace_id, address)
    if address.startswith(AGOS_PREFIX):
        found = split_agos(address)
        if found is None or not _platform_chat(core, workspace_id, found[0]):
            return None
        return found[0]
    row = gateway_platform.connection(core, workspace_id)
    if row is None:
        return None
    target = _target(core, row, address)
    if target is None or str(target["workspace_id"]) != workspace_id:
        return None
    return int(target["chat_id"])


def address_of(chat: str) -> str:
    """ "<chat id>[:<topic id>]" from the plugin → AGOS's address (no topic = ":0")."""
    return chat if ":" in chat else f"{chat}:0"


def _target(core: Core, row: sqlite3.Row, address: str) -> sqlite3.Row | None:
    from agos_core.actions import channels

    address = address_of(address)

    target = addresses_repo.target(core.db, int(row["id"]), address)
    if target is None and address.startswith("-") and address.endswith(":1"):
        # A forum's General topic: Hermes calls it topic 1, a link without a topic is 0.
        general = address[:-2] + ":0"
        target = addresses_repo.target(core.db, int(row["id"]), general)
    if (
        target is None
        and address.endswith(":0")
        and not address.startswith("-")  # a private chat (groups have negative ids)
        and channels.link_cofounder_chat(core, int(row["id"]), address) is not None
    ):
        target = addresses_repo.target(core.db, int(row["id"]), address)
    return target


MIRROR_MARK = "🖥 From AGOS:"


def chat_of_address(core: Core, workspace_id: str, address: str) -> int | None:
    """The AGOS chat of a Hermes address (an AGOS conversation or a linked Telegram
    chat); read only."""
    if address.startswith(AGOS_PREFIX):
        return chat_at(core, workspace_id, address)
    row = gateway_platform.connection(core, workspace_id)
    found = (
        addresses_repo.chat_of(core.db, int(row["id"]), address_of(address))
        if row is not None
        else None
    )
    return found


def owner_member(core: Core, workspace_id: str, address: str) -> str | None:
    """The team member whose own Hermes profile answers this conversation (its DM, a
    Session given to it, its Kanban card's chat), when that profile is ready; None =
    the workspace's own Hermes (the Co-Founder). The member's role is in its SOUL.md."""
    if not address.startswith(AGOS_PREFIX):
        return None
    found = split_agos(address)
    if found is None:
        return None
    chat_id, member = found
    if member is None:
        dm = repo.in_workspace(core.db, workspace_id, chat_id)
        member = (
            str(dm["agent"]) if dm is not None and dm["kind"] != "group" and dm["agent"] else None
        )
    if member is None:
        return None
    from agos_core.actions import agent_profiles

    return member if agent_profiles.ready(core, workspace_id, member) else None


def _dm_member(core: Core, chat_id: int) -> bool:
    row = repo.any_row(core.db, chat_id)
    if row is None or row["kind"] == "group" or not row["agent"]:
        return False
    from agos_core.actions import agent_profiles

    return agent_profiles.ready(core, str(row["workspace_id"]), str(row["agent"]))


def _session_of(core: Core, address: str) -> str:
    """An AGOS conversation's own Hermes session, when it already has one (answers AGOS
    ran through Hermes's API server): kept when the chat moves onto the platform."""
    if not address.startswith(AGOS_PREFIX):
        return ""
    found = split_agos(address)
    if found is None or found[1] is not None:
        return ""  # a group member: its own new conversation
    if _dm_member(core, found[0]):
        return ""  # a member's DM on its own profile: its own conversation there
    chat_id = found[0]
    return repo.hermes_key(core.db, chat_id) if chat_turns.ran_on_hermes(core.db, chat_id) else ""


def chat_on_hermes(core: Core, chat_id: int) -> dict[str, Any] | None:
    """Where the chat's conversation lives in Hermes: its Telegram chat (a bot on
    Hermes), else the AGOS conversation itself when the workspace is on the agos
    platform. None: AGOS runs its answers itself. A member's DM linked to a topic
    is that topic: Hermes routes it to the member's profile (gateway.profile_routes,
    actions/member_topics.py), so the web and Telegram write into one session."""
    found = addresses_repo.hermes_place(core.db, chat_id, gateway_platform.ENGINE_HERMES)
    if found is not None:
        return {"address": str(found["address"]), "connection_id": int(found["connection_id"])}
    workspace_id = repo.workspace_of(core.db, chat_id)
    if workspace_id is not None and _platform_chat(core, workspace_id, chat_id):
        return {"address": f"{AGOS_PREFIX}{chat_id}", "connection_id": None}
    return None
