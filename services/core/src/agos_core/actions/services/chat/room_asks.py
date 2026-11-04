"""Approvals asked inside a room: shown, held, waiting, answered by the owner.
Must not: decide for the owner.

Split out of agos_core.actions.rooms (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agos_core.actions.services.chat.room_names import (
    _room_row,
    _speaker,
    chat_of_room,
    is_room_chat,
)
from agos_core.actions.services.chat.room_sync import _queue, _seen, _wake, ensure_room
from agos_core.actions.services.chat.room_turns import _live
from agos_core.context import Core
from agos_core.db.connection import transaction

__all__ = [
    "answer",
    "approval",
    "held_mark",
    "still_asks",
    "told",
    "waiting_approval",
]


def _ask_of(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "member_id": str(raw.get("member_id") or ""),
        "task_id": str(raw.get("task_id") or ""),
        "execution_generation": int(raw.get("execution_generation") or 0),
        "request_id": str(raw.get("request_id") or ""),
        "command": str(raw.get("command") or "")[:4000],
        "description": str(raw.get("description") or "")[:1000],
    }


def approval(core: Core, workspace_id: str, room_id: str, ask: dict[str, Any]) -> int | None:
    """A member waits on his Allow once / Deny: the card in the chat and
    the group's Telegram place (or the Co-Founder's), answered with Hermes's
    approve_room_task (once / deny only). Returns the chat; None when it was told
    already (or the room isn't a chat's)."""
    chat_id = chat_of_room(core, workspace_id, room_id)
    found = _ask_of(ask)
    request_id = found["request_id"]
    if chat_id is None or not request_id:
        return None
    pending = _seen(core, workspace_id)["pending"].setdefault(room_id, {})
    if request_id in pending:
        return None  # the same request again: asked once
    pending[request_id] = found
    live_now = _live(core, chat_id)
    if live_now is not None:
        live_now[1].turn.apply(
            {
                "event": "approval.request",
                "command": found["command"],
                "description": found["description"],
                "pattern_key": "",
            }
        )
    from agos_core.actions.services.channel import owner_needs

    with transaction(core.db):
        # One card per Hermes request (the outbox takes a source once: never twice
        # after a restart either).
        owner_needs.chat_command(
            core,
            workspace_id,
            _speaker(found["member_id"]),
            found["command"] or found["description"],
            found["description"],
            f"chatcmd:{chat_id}",
            f"roomask:{hashlib.sha256(request_id.encode()).hexdigest()[:24]}",
            chat_id=chat_id,
        )
    return chat_id


def told(core: Core, workspace_id: str, rooms: dict[str, dict[str, Any]], mark: str = "") -> None:
    """The plugin's report of what each room holds in Hermes now: its members (a
    room whose members aren't today's roster is made again) and every approval its
    members wait on (new ones are asked; those Hermes no longer holds go). `mark`:
    which report it is (a newer plugin's room-held; room-next tells it back so the
    plugin tells it again only when it changed or this process hasn't got it)."""
    seen = _seen(core, workspace_id)
    seen["mark"] = ""  # until this report is all taken in
    seen["heard"] = True
    for room_id in set(seen["pending"]) - set(rooms):
        for gone in seen["pending"].pop(room_id):
            seen["answered"].discard(gone)
    for room_id in set(seen["members"]) - set(rooms):
        seen["members"].pop(room_id, None)
    seen["missing"] &= set(rooms)
    for room_id, info in rooms.items():
        now_ids = set()
        for raw in info.get("pending") or []:
            ask = _ask_of(raw)
            if ask["request_id"]:
                now_ids.add(ask["request_id"])
                approval(core, workspace_id, room_id, ask)
        held = seen["pending"].setdefault(room_id, {})
        for gone in set(held) - now_ids:
            held.pop(gone, None)
            seen["answered"].discard(gone)
        members = info.get("members")
        if members is None:  # Hermes holds no such room (its room-sync job makes it)
            seen["members"].pop(room_id, None)
            seen["missing"].add(room_id)
            continue
        before = seen["members"].get(room_id)
        seen["members"][room_id] = members
        seen["missing"].discard(room_id)
        chat_id = chat_of_room(core, workspace_id, room_id)
        if chat_id is not None and (before != members or chat_id in seen["check"]):
            seen["check"].discard(chat_id)
            if is_room_chat(core, workspace_id, chat_id):
                ensure_room(core, workspace_id, chat_id)
    seen["mark"] = mark


def held_mark(core: Core, workspace_id: str) -> str:
    """Which of the plugin's reports of what the rooms hold this process has taken
    in ("": none since it started, or an older plugin's)."""
    return str(_seen(core, workspace_id).get("mark") or "")


def waiting_approval(core: Core, workspace_id: str, chat_id: int) -> dict[str, Any] | None:
    """The first approval a member of the chat's room waits on, as Hermes holds it
    (and he hasn't answered yet)."""
    room = _room_row(core, workspace_id, chat_id)
    if room is None:
        return None
    seen = _seen(core, workspace_id)
    for ask in seen["pending"].get(str(room["room_id"]), {}).values():
        if ask["request_id"] not in seen["answered"]:
            return dict(ask)
    return None


def still_asks(core: Core, workspace_id: str, chat_id: int) -> bool | None:
    """Whether a member of the chat's room still waits on him; None when AGOS hasn't
    been told what Hermes's rooms hold since it started (a card stays as it is)."""
    if not _seen(core, workspace_id)["heard"]:
        return None
    return waiting_approval(core, workspace_id, chat_id) is not None


def answer(core: Core, workspace_id: str, chat_id: int, choice: str) -> bool:
    """His Allow once / Deny (AGOS or Telegram) for the member's waiting command."""
    if choice not in ("once", "deny"):
        return False
    ask = waiting_approval(core, workspace_id, chat_id)
    room = _room_row(core, workspace_id, chat_id)
    if ask is None or room is None:
        return False
    _seen(core, workspace_id)["answered"].add(ask["request_id"])
    with transaction(core.db):
        _queue(
            core,
            workspace_id,
            chat_id,
            "room-approve",
            {
                "room_id": str(room["room_id"]),
                "member_id": ask["member_id"],
                "task_id": ask["task_id"],
                "execution_generation": int(ask["execution_generation"]),
                "request_id": ask["request_id"],
                "choice": choice,
            },
        )
    found = _live(core, chat_id)
    if found is not None:
        found[1].turn.apply({"event": "approval.responded", "choice": choice})
    _wake(core, workspace_id)
    return True
