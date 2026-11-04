"""What the agos-guard plugin takes from AGOS: the inbox of a workspace's Hermes (and
its tidy-up), the live events of a Hermes turn, and approvals asked and answered
in the channel.

Owns: the hermes_inbox queue and the live-event feed to the chat.
Must not: decide approvals (owner_gate) or write chat turns (chat_turns).

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.actions.services.channel import gateway_messages, gateway_platform, hermes_addresses
from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.db import hermes_inbox
from agos_core.db.connection import transaction
from agos_core.db.rows import load_json
from agos_core.engine import doorbell

__all__ = [
    "LIVE_EVENTS",
    "answer_approval",
    "approval_answered",
    "approval_asked",
    "channel_prompt",
    "inbox_done",
    "live_events",
    "take_inbox",
    "tidy_inbox",
]


def _live_hermes_turn(core: Core, workspace_id: str, address: str) -> tuple[int, Any] | None:
    """(chat id, live state) of the chat's Hermes answer working now."""
    chat_id = hermes_addresses.chat_of_address(core, workspace_id, address)
    if chat_id is None:
        return None
    from agos_core.actions import chat as chat_actions
    from agos_core.db import chats as repo
    from agos_core.engine.chat import LiveTurn

    turn = repo.live_turn(core.db, chat_id)
    if turn is None or turn.via != gateway_platform.ENGINE_HERMES:
        return None
    registry = chat_actions._registry(core)
    live = registry.get(turn.id)
    if live is None:
        live = registry[turn.id] = chat_actions._Live(turn=LiveTurn(turn_id=turn.id))
    return chat_id, live


LIVE_EVENTS = {"message.delta", "tool.started", "tool.completed", "reasoning.available"}


def live_events(core: Core, workspace_id: str, turn_id: int, events: list[dict[str, Any]]) -> None:
    """Hermes's answer as it is written: the AGOS chat shows it live."""
    from agos_core.actions import chat as chat_actions
    from agos_core.db import chats as repo

    turn = repo.get_turn(core.db, turn_id)
    if (
        turn is None
        or turn.workspace_id != workspace_id
        or turn.via != gateway_platform.ENGINE_HERMES
    ):
        return
    live = chat_actions._registry(core).get(turn_id)
    if live is None:
        return
    for event in events:
        if str(event.get("event")) in LIVE_EVENTS:
            live.turn.apply(event)
    live.turn.version += 1


def approval_asked(
    core: Core, workspace_id: str, address: str, command: str, description: str, pattern: str
) -> dict[str, str] | None:
    """Hermes asks Allow / Deny: the same card shows in the AGOS chat. In an AGOS
    conversation, also where Hermes shows its own Telegram card for it (the chat's
    own Telegram place, else the Co-Founder's): returned for the plugin, None = none.
    A Telegram conversation already has Hermes's card in its own chat."""
    from agos_core.actions import learning

    if address == learning.ADDRESS:
        answer_approval(core, workspace_id, address, "deny")  # it runs nothing
        return None
    found = _live_hermes_turn(core, workspace_id, address)
    if found is None:
        return None
    chat_id, live = found
    if pattern.startswith(hermes_addresses.AGOS_TOOL_RULE):
        # One of AGOS's own tools (Add to To do, the Co-Founder's actions…): the card
        # says what it does, not Hermes's "<tool> (plugin approval rule)".
        command, description = description, ""
    asked = {"command": command, "description": description, "pattern_key": pattern}
    live.turn.apply({"event": "approval.request", **asked})
    live.turn.version += 1
    if not address.startswith(hermes_addresses.AGOS_PREFIX):
        return None
    from agos_core.actions.services.channel import owner_needs

    return owner_needs.phone_place(core, workspace_id, chat_id, command)


def approval_answered(core: Core, workspace_id: str, address: str, choice: str) -> None:
    """Answered (in Telegram or in AGOS): the card closes in both."""
    found = _live_hermes_turn(core, workspace_id, address)
    if found is None:
        return
    _chat_id, live = found
    live.turn.apply({"event": "approval.responded", "choice": choice})
    live.turn.version += 1


def answer_approval(core: Core, workspace_id: str, address: str, choice: str) -> None:
    """His Allow once / Deny from AGOS, for the approval Hermes waits on."""
    hermes_inbox.put(core.db, workspace_id, address, choice, "approval")
    doorbell.ring(doorbell.INBOX, workspace_id)


def take_inbox(
    core: Core,
    workspace_id: str,
    *,
    agos: bool = False,
    member: str = "",
    members: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The next things to hand to this workspace's Hermes (each handed once; one not
    confirmed within a minute is handed again). `agos`: those for AGOS's own
    conversations (taken by the plugin's agos platform), else Telegram's.
    `member`: asked by that team member's own gateway (only its conversations);
    the workspace's gateway never takes those. `members`: one ask for several
    profiles of one gateway ("": the workspace's own); each item says whose it is."""
    from datetime import UTC, datetime, timedelta

    if member and not agos:
        return []  # a member has no Telegram of its own: the Co-Founder's bot carries it
    retry = (datetime.now(UTC) - timedelta(seconds=60)).isoformat(timespec="milliseconds")
    retry = retry.replace("+00:00", "Z")
    rows = hermes_inbox.for_gateway(core.db, workspace_id, retry, agos=agos)
    from agos_core.actions import work_hours

    if rows and work_hours.enabled(core, workspace_id):
        # A message to an agent that is off-hours waits here until its check-in.
        rows = [
            r
            for r in rows
            if str(r["kind"]) not in ("message", "reply")
            or not gateway_messages.waits_for_check_in(core, workspace_id, str(r["chat_ref"]))
        ]
    owners: dict[int, str] = {}
    if agos:
        wanted = {member} if members is None else set(members)
        for r in rows:
            owners[int(r["id"])] = (
                hermes_addresses.owner_member(core, workspace_id, str(r["chat_ref"])) or ""
            )
        rows = [r for r in rows if owners[int(r["id"])] in wanted][:20]
    if not rows:
        return []
    taken = []
    with transaction(core.db):
        for r in rows:
            # Taken once, even with several gateways asking (the Co-Founder's, members').
            if hermes_inbox.claim(core.db, int(r["id"]), retry):
                taken.append(r)
    rows = taken
    return [
        {
            "id": int(r["id"]),
            "chat": str(r["chat_ref"]),
            **_said(r),
            "media": load_json(r["media"]) or [],
            # When he sent it (Hermes's message time, not when its gateway took it).
            "createdAt": str(r["created_at"] or ""),
            "session": hermes_addresses._session_of(core, str(r["chat_ref"])),
            # The AGOS chat's name (and a Kanban card's chat: its card): Hermes's own
            # topic of the conversation, in its session context.
            "topic": _topic_of(core, workspace_id, str(r["chat_ref"])),
            # What only this conversation is told (the learning conversation: what
            # it is for): Hermes's channel prompt.
            "channelPrompt": channel_prompt(str(r["chat_ref"])),
            # Whose it is, for a gateway's one ask for all its profiles.
            **({"member": owners[int(r["id"])]} if members is not None else {}),
        }
        for r in rows
    ]


def _said(row: sqlite3.Row) -> dict[str, Any]:
    """The item's words and kind; a reply also carries what it replies to (for
    Hermes's reply context: `replyTo`, and `replyOwn` when it is the agent's)."""
    if row["kind"] != "reply":
        return {"text": str(row["text"]), "kind": row["kind"]}
    found = load_json(row["text"]) or {}
    return {
        "text": str(found.get("text") or ""),
        "kind": "message",
        "replyTo": str(found.get("replyTo") or ""),
        "replyOwn": bool(found.get("own")),
    }


def _topic_of(core: Core, workspace_id: str, address: str) -> str:
    found = (
        hermes_addresses.split_agos(address)
        if address.startswith(hermes_addresses.AGOS_PREFIX)
        else None
    )
    if found is None:
        return ""
    row = repo.in_workspace(core.db, workspace_id, found[0])
    if row is None:
        return ""
    title = " ".join(repo.chat_title(core.db, row).split())[:200]
    if row["kanban_card"]:
        # The member reads the card itself (Hermes's kanban_show).
        title = f"{title} (Kanban card {row['kanban_card']})"
    return title


def channel_prompt(address: str) -> str:
    """Hermes's per-conversation channel prompt for an AGOS conversation ("" = none):
    only the learning conversation has one."""
    from agos_core.actions import learning

    return learning.INSTRUCTIONS if address == learning.ADDRESS else ""


def tidy_inbox(core: Core) -> int:
    """What Hermes took more than a day ago leaves the inbox (a restarted gateway
    is only ever sent its last two minutes again). A message with files stays: its
    time is how the chat finds his files on Hermes's message (db/chats.py)."""
    return int(hermes_inbox.purge_done(core.db))


def inbox_done(core: Core, workspace_id: str, item_id: int, ok: bool) -> None:
    hermes_inbox.done(core.db, workspace_id, item_id, ok)
