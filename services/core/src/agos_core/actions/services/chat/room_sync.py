"""AGOS to the room: the room-sync queue (create, rename, recreate after a membership change), waking the gateway, what was seen.
Must not: read the room's events (room_turns does).

Split out of agos_core.actions.rooms (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from agos_core.actions.services.chat.room_names import (
    _digest,
    _hermes_name,
    _room_row,
    address,
    is_room_chat,
    room_name,
    roster,
)
from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.db import group_rooms, hermes_inbox
from agos_core.db.connection import transaction
from agos_core.engine import doorbell

__all__ = [
    "ensure_room",
    "forget",
    "members_changed",
    "move_old_names",
    "renamed",
]


def renamed(core: Core, workspace_id: str, chat_id: int) -> None:
    """The owner renamed the group (AGOS holds the new name until Hermes does): a
    room Hermes already made is renamed with Hermes's own rename_room (H:
    gateway/hosted_rooms.py:913, its RPC `groups.rename`); a room still being made
    gets it when Hermes confirms it (done)."""
    row = _room_row(core, workspace_id, chat_id)
    if row is None or row["state"] != "ready" or not is_room_chat(core, workspace_id, chat_id):
        return
    name = room_name(core, chat_id)
    if _hermes_name(core, workspace_id, str(row["room_id"])) == name:
        _drop_own_title(core, chat_id, name)
        return
    import time

    _queue(
        core,
        workspace_id,
        chat_id,
        "room-rename",
        {
            "room_id": str(row["room_id"]),
            "name": name,
            "event_id": f"agos-name-c{chat_id}-{int(time.time() * 1000)}",
        },
    )
    _wake(core, workspace_id)


def _drop_own_title(core: Core, chat_id: int, held: str) -> None:
    """Hermes's room holds the group's name now: AGOS's copy goes (only when the
    room's name is exactly it, so nothing is lost)."""
    row = repo.any_row(core.db, chat_id)
    title = str(row["title"] or "") if row is not None else ""
    if title and repo.room_name_of(chat_id, title) == held and title == title.strip():
        tag = f" · #{int(chat_id)}"
        if held[: -len(tag)] == title:
            repo.drop_held_title(core.db, chat_id)


def move_old_names(core: Core) -> int:
    """Groups whose name AGOS kept while their Hermes room existed (before a group's
    name was its room's): AGOS's copy goes where the room has the same name, and the
    room is renamed where it doesn't (the old rooms never followed a rename). Once."""
    from agos_core.db import hermes_chats as hc

    if hc.store() is None:
        return 0
    moved = 0
    rows = group_rooms.named_ready(core.db)
    for r in rows:
        ws, chat_id, room_id = str(r["workspace_id"]), int(r["chat_id"]), str(r["room_id"])
        held = _hermes_name(core, ws, room_id)
        if held is None:
            continue  # Hermes holds no such room: the name stays AGOS's
        with transaction(core.db):
            if held == room_name(core, chat_id):
                _drop_own_title(core, chat_id, held)
                moved += 1
            else:
                renamed(core, ws, chat_id)
    return moved


def _queue(core: Core, workspace_id: str, chat_id: int, kind: str, job: dict[str, Any]) -> int:
    item = hermes_inbox.put(
        core.db, workspace_id, address(chat_id), json.dumps(job, sort_keys=True), kind
    )
    doorbell.ring(doorbell.INBOX, workspace_id)
    return item


def ensure_room(core: Core, workspace_id: str, chat_id: int) -> dict[str, Any] | None:
    """The chat's room exists with today's roster (`members`, from the group's
    members, AGOS's own): a new room the first time, a new generation (the old one
    disbanded, AGOS's history kept) when the room's members in Hermes (H:
    tui_gateway/hosted_room_service.py:440 create_room, its hosted-room row; the
    plugin reports them) are not today's. None when the group has no member who can
    take part yet. AGOS keeps no copy of the room's members: until the plugin has
    told them since this start, the room is taken as it is and checked once told."""
    members = roster(core, workspace_id, chat_id)
    if len(members) < 2:
        return None
    row = _room_row(core, workspace_id, chat_id)
    if row is not None:
        seen = _seen(core, workspace_id)
        room_id = str(row["room_id"])
        if room_id in seen["missing"]:
            # Hermes holds no such room: one not made yet is asked again (with today's
            # roster; its old job may still come first, then Hermes's room is checked).
            if row["state"] != "ready":
                _sync_item(core, workspace_id, chat_id, room_id, members, None)
            return {**dict(row), "members": members}
        held = seen["members"].get(room_id)
        if held is None:
            seen["check"].add(chat_id)  # not told yet since this start: checked once told
            return {**dict(row), "members": members}
        if _same(held, members) or seen["made"].get(room_id) == _digest(members):
            # Today's roster (or made with it here: Hermes's own spelling of it).
            return {**dict(row), "members": members}
    generation = int(row["generation"]) + 1 if row is not None else 1
    room_id = f"agos-c{chat_id}-g{generation}"
    old = str(row["room_id"]) if row is not None else None
    _seen(core, workspace_id)["made"][room_id] = _digest(members)
    shown = repo.title_of(core.db, chat_id)  # the old room's name, if Hermes held it
    # A new room starts as Hermes starts one (AGOS keeps the history).
    with transaction(core.db):
        # The name is AGOS's again until the new room holds it (done).
        repo.hold_title(core.db, chat_id, shown)
        group_rooms.want(core.db, chat_id, workspace_id, room_id, generation)
        _sync_item(core, workspace_id, chat_id, room_id, members, old)
    return {**dict(_room_row(core, workspace_id, chat_id)), "members": members}


def _same(held: list[dict[str, Any]], members: list[dict[str, str]]) -> bool:
    """Hermes's members of a room are these (as Hermes keeps them: H:
    gateway/hosted_room_discussion.py:233-252, display_name stripped)."""

    def key(m: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(m.get("member_id") or ""),
            str(m.get("profile") or ""),
            str(m.get("handle") or ""),
            str(m.get("display_name") or "").strip(),
        )

    return [key(m) for m in held] == [key(m) for m in members]


def _sync_item(
    core: Core,
    workspace_id: str,
    chat_id: int,
    room_id: str,
    members: list[dict[str, str]],
    old: str | None,
) -> None:
    _queue(
        core,
        workspace_id,
        chat_id,
        "room-sync",
        {
            "room_id": room_id,
            "name": room_name(core, chat_id),
            "members": members,
            "disband": old,
        },
    )
    _wake(core, workspace_id)


def members_changed(core: Core, workspace_id: str, chat_id: int) -> None:
    """The owner changed the group's members: the room follows now (Hermes rooms
    have a frozen roster, so it is disbanded and made again; the chat keeps all
    its history in AGOS, and the members get a recap with the next message)."""
    if is_room_chat(core, workspace_id, chat_id) and _room_row(core, workspace_id, chat_id):
        ensure_room(core, workspace_id, chat_id)


def _wake(core: Core, workspace_id: str) -> None:
    """The root's gateway carries the room. Hermes's service keeps it up
    (`Restart=always`); only the test-only "spawn" supervisor needs AGOS to bring a
    gateway it spawned back (in the background)."""
    if core.engine is None or core.engine.settings.gateway_supervisor != "spawn":
        return
    from agos_core.actions import idle

    threading.Thread(
        target=idle.spawned_up,
        args=(core, workspace_id),
        name=f"room-up-{workspace_id}",
        daemon=True,
    ).start()


# A member's waiting approval is Hermes's alone: its room service holds the pending set
# (H: tui_gateway/hosted_room_service.py:74 `_pending_actions`, set at :305-311, read
# by `status(room_id)["pending_actions"]` at :544-555 with member_id, task_id,
# execution_generation, request_id and the approval's command/description, cleared by
# `approve_room_task` at :498-533). The plugin reports it with every `room-next`
# (`pending`), and at once when Hermes opens one (`/room-approval`). AGOS keeps no
# copy: only what it was last told, in memory, and which ones he answered since.
_SEEN: dict[tuple[int, str], dict[str, Any]] = {}


def _seen(core: Core, workspace_id: str) -> dict[str, Any]:
    """What Hermes's rooms of the workspace hold, as the plugin last told it (memory):
    `heard` (told since this process started), `pending` (room → request id → ask),
    `answered` (request ids he answered, until Hermes drops them), `members`."""
    return _SEEN.setdefault(
        (id(core.db), workspace_id),
        {
            "heard": False,
            "pending": {},
            "answered": set(),
            "members": {},  # room → its members in Hermes (None: Hermes has no such room)
            "missing": set(),  # rooms Hermes holds no such room for (not made yet)
            "made": {},  # room → the roster digest AGOS made it with (this process)
            "check": set(),  # chats whose room is checked once Hermes's members are told
            "mark": "",  # which report of the plugin's this is (room-held's hash)
        },
    )


def forget(core: Core) -> None:
    """The core stops: what it was told goes with it (the plugin tells it again)."""
    for key in [k for k in _SEEN if k[0] == id(core.db)]:
        _SEEN.pop(key, None)
