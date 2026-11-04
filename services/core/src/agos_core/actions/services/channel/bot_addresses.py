"""Where each chat is sent: a bot's addresses (chats and topics), adding and removing them, the Co-Founder's own chat.
Must not: send a message.

Split out of agos_core.actions.channels (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import re

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.channel.connections import (
    AddressView,
    channel_state,
    connection_row,
)
from agos_core.actions.services.channel.topics import make_topic
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction

__all__ = [
    "add_address",
    "addresses_of",
    "link_cofounder_chat",
    "remove_address",
]


def link_cofounder_chat(core: Core, connection_id: int, address: str) -> int | None:
    """The bot's private chat with the owner → its workspace's Co-Founder chat, with
    board notifications. Nothing if the bot has no workspace or the address is taken."""
    row = connection_row(core, connection_id)
    workspace_id = row["workspace_id"]
    if not workspace_id:
        return None
    if addresses_repo.taken_by(core.db, connection_id, address) is not None:
        return None
    from agos_core.actions.workers import open_dm

    chat_id = open_dm(core, workspace_id, None)
    has_notify = addresses_repo.has_notify(core.db, workspace_id)
    added = add_address(
        core,
        workspace_id,
        chat_id,
        connection_id=connection_id,
        address=address,
        create_topic=None,
        notify=not has_notify,
    )
    from agos_core.actions import hermes_channel

    hermes_channel.refresh_bridge(core, workspace_id)  # Kanban news: now his Telegram
    return added


# ---- where each chat lives ----------------------------------------------------------------


def addresses_of(core: Core, chat_id: int) -> list[AddressView]:
    from agos_core.actions import hermes_channel

    rows = addresses_repo.of_chat(core.db, chat_id)
    lamps = {int(r["connection_id"]): channel_state(core, r) for r in rows}
    names = {
        ws: hermes_channel.place_names(core, ws) for ws in {str(r["workspace_id"]) for r in rows}
    }
    return [
        AddressView(
            id=r["id"],
            connection_id=r["connection_id"],
            connection_name=r["cname"],
            kind=r["kind"],
            address=r["address"],
            # The place's name as Hermes's channel directory has it now ("" = unknown).
            label=names[str(r["workspace_id"])].get(str(r["address"]), ""),
            notify=r["notify"] == 1,
            status=lamps[int(r["connection_id"])][0],  # type: ignore[arg-type]
            status_reason=lamps[int(r["connection_id"])][1],
        )
        for r in rows
    ]


def _check_address(kind: str, address: str) -> str:
    address = address.strip()
    if not re.fullmatch(r"-?\d{1,20}(:\d{1,12})?", address):
        raise ActionError(
            "A Telegram address is the group id, optionally :topic id (e.g. -1001234567890:42)."
        )
    return address if ":" in address else f"{address}:0"


def add_address(
    core: Core,
    workspace_id: str,
    chat_id: int,
    *,
    connection_id: int,
    address: str | None,
    create_topic: str | None,
    notify: bool,
) -> int:
    chat = chats_repo.chat_row(core.db, workspace_id, chat_id)
    if chat is None:
        raise NotFoundError("This chat")

    title = chats_repo.chat_title(core.db, chat)
    conn = connection_row(core, connection_id)
    if create_topic:
        base = _check_address(conn["kind"], create_topic)
        addr = make_topic(workspace_id, base.split(":")[0], title)
    else:
        addr = _check_address(conn["kind"], address or "")
    if addresses_repo.taken_by(core.db, connection_id, addr) is not None:
        raise ActionError(
            "That address already belongs to another chat (one address = one chat).", 409
        )
    with transaction(core.db):
        if notify:
            addresses_repo.notify_off(core.db, workspace_id)
        added = addresses_repo.add(core.db, chat_id, connection_id, addr, notify)
        # Messages already in the chat are not re-sent to the new address.
        outbox.seen_all_agent_lines(core.db, connection_id, addr, chat_id)
    if chat["agent"]:
        _member_topics_follow(core, workspace_id)
    return added


def _member_topics_follow(core: Core, workspace_id: str) -> None:
    """A member's DM got (or lost) a Telegram place: Hermes's routes follow
    (actions/member_topics.py)."""
    from agos_core.actions import member_topics

    member_topics.follow(core, workspace_id)


def remove_address(core: Core, workspace_id: str, chat_id: int, address_id: int) -> None:
    gone = addresses_repo.remove(core.db, workspace_id, chat_id, address_id)
    chat = chats_repo.any_row(core.db, chat_id)
    if gone and chat is not None and chat["agent"]:
        _member_topics_follow(core, workspace_id)
