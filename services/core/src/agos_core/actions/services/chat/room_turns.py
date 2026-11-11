"""The room to AGOS: its events taken, each turn's live view, handing over, stopping, done.
Must not: answer an approval (room_asks does).

Split out of agos_core.actions.rooms (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.services.chat import chat_writes
from agos_core.actions.services.chat.room_names import (
    COFOUNDER,
    ROOM_KINDS,
    SPEAKER_AGOS,
    VIA,
    _hermes_name,
    _room_row,
    _speaker,
    chat_of,
    chat_of_room,
    hermes_event_id,
    mentions,
    room_name,
)
from agos_core.actions.services.chat.room_sync import (
    _drop_own_title,
    _queue,
    _wake,
    ensure_room,
    renamed,
)
from agos_core.context import Core
from agos_core.db import chat_turns, group_rooms, hermes_inbox
from agos_core.db.connection import transaction
from agos_core.engine import doorbell

__all__ = [
    "done",
    "events",
    "hand_over",
    "live",
    "stop",
    "take",
]

log = logging.getLogger("agos.rooms")  # the old module's logger (one name)


@doorbell.together()
def hand_over(core: Core, workspace_id: str, chat_id: int, pending: list[tuple[int, str]]) -> bool:
    """His messages (already text, files as their sandbox paths) → the chat's room.
    One room turn is the chat's live answer until it settles; sync + message ring once."""
    if not pending:
        return False
    room = ensure_room(core, workspace_id, chat_id)
    if room is None:
        with transaction(core.db):
            chat_writes.add_chat_message(
                core.db,
                workspace_id,
                chat_id,
                "agent",
                "This group has no member who can take part yet: add a team member to the "
                "group (its profile must be ready), then write again.",
                speaker=SPEAKER_AGOS,
            )
        return False
    members = room["members"]
    text = "\n\n".join(t for _, t in pending if t.strip()) or "(no text)"
    from agos_core.actions.hermes_channel import chosen_member

    picked = chosen_member(core, chat_id)  # picked in Telegram's "/" menu just before
    if picked and not mentions(text, [m["handle"] for m in members] + [COFOUNDER]):
        text = f"@{picked} {text}"
    # Who answers is Hermes's own rule: the members he @mentions, or everyone.
    up_to = max(i for i, _ in pending)
    event_id = f"agos-m{up_to}"
    with transaction(core.db):
        _queue(
            core,
            workspace_id,
            chat_id,
            "room-send",
            {"room_id": room["room_id"], "event_id": event_id, "text": text[:60_000]},
        )
        group_rooms.set_discussion(core.db, chat_id, hermes_event_id(event_id))
        _open_turn(core, workspace_id, chat_id, up_to)
    _wake(core, workspace_id)
    return True


def _open_turn(core: Core, workspace_id: str, chat_id: int, asked_up_to: int) -> int:
    from agos_core.actions import chat as chat_actions
    from agos_core.db import chats as repo
    from agos_core.engine.chat import LiveTurn

    live = repo.live_turn(core.db, chat_id)
    if live is not None and live.via == VIA:
        chat_turns.raise_asked_up_to(core.db, live.id, asked_up_to)
        return int(live.id)
    turn_id = chat_writes.insert_turn(
        core.db, chat_id=chat_id, workspace_id=workspace_id, asked_up_to=asked_up_to
    )
    chat_turns.run_via(core.db, turn_id, VIA)
    chat_actions._registry(core)[turn_id] = chat_actions._Live(turn=LiveTurn(turn_id=turn_id))
    return turn_id


def _live(core: Core, chat_id: int) -> tuple[int, Any] | None:
    from agos_core.actions import chat as chat_actions
    from agos_core.db import chats as repo
    from agos_core.engine.chat import LiveTurn

    turn = repo.live_turn(core.db, chat_id)
    if turn is None or turn.via != VIA:
        return None
    registry = chat_actions._registry(core)
    live = registry.get(turn.id)
    if live is None:
        live = registry[turn.id] = chat_actions._Live(turn=LiveTurn(turn_id=turn.id))
    return int(turn.id), live


def _close_turn(core: Core, chat_id: int, status: str, error: str | None = None) -> None:
    from agos_core.actions import chat as chat_actions

    found = _live(core, chat_id)
    if found is not None:
        chat_actions._close(core, found[0], status, reply=None, error=error)


def stop(core: Core, workspace_id: str, chat_id: int) -> bool:
    """His Stop: Hermes's own stop_room (queued and running work is cancelled; the
    room answers again when he writes)."""
    room = _room_row(core, workspace_id, chat_id)
    if room is None:
        return False
    _queue(core, workspace_id, chat_id, "room-stop", {"room_id": room["room_id"]})
    _wake(core, workspace_id)
    _close_turn(core, chat_id, "stopped")
    return True


# ---- the plugin takes what is for the room --------------------------------------------


def take(core: Core, workspace_id: str) -> dict[str, Any]:
    """The next room jobs for the workspace's gateway (each handed once; one not
    confirmed within a minute is handed again) and AGOS's cursors."""
    from datetime import UTC, datetime, timedelta

    retry = (datetime.now(UTC) - timedelta(seconds=60)).isoformat(timespec="milliseconds")
    retry = retry.replace("+00:00", "Z")
    rows = hermes_inbox.for_rooms(core.db, workspace_id, retry, tuple(ROOM_KINDS))
    items = []
    if rows:  # most asks find nothing: then no write transaction (no write lock waited on)
        with transaction(core.db):
            for r in rows:
                if hermes_inbox.claim(core.db, int(r["id"]), retry):
                    items.append(
                        {"id": int(r["id"]), "kind": r["kind"], "job": json.loads(r["text"])}
                    )
    rooms = {
        str(r["room_id"]): {
            "cursor": int(r["cursor"]),
            "chat": int(r["chat_id"]),
            "name": _hermes_name(core, workspace_id, str(r["room_id"]))
            or room_name(core, int(r["chat_id"])),
        }
        for r in group_rooms.cursors(core.db, workspace_id)
    }
    return {"items": items, "rooms": rooms}


def done(
    core: Core, workspace_id: str, item_id: int, ok: bool, error: str = "", event: str = ""
) -> None:
    row = hermes_inbox.get(core.db, workspace_id, item_id)
    if row is None:
        return
    chat_id = chat_of(core, workspace_id, str(row["chat_ref"]))
    follow = False
    with transaction(core.db):
        if ok:
            hermes_inbox.finished(core.db, item_id)
        elif error:
            # Hermes refused it (a roster it doesn't accept, a gone room): no retry.
            hermes_inbox.finished(core.db, item_id)
        if chat_id is None:
            return
        job = json.loads(row["text"])
        if row["kind"] == "room-send" and ok and event:
            # The id Hermes really gave his message (the discussion the room answers).
            group_rooms.replace_discussion(
                core.db, chat_id, event, hermes_event_id(str(job.get("event_id") or ""))
            )
        if row["kind"] in ("room-sync", "room-rename") and ok:
            # The room holds the group's name now; a newer one (renamed meanwhile)
            # goes to it in turn.
            _drop_own_title(core, chat_id, str(job.get("name") or ""))
            follow = str(job.get("name") or "") != room_name(core, chat_id)
        if row["kind"] == "room-sync":
            group_rooms.synced(core.db, chat_id, job.get("room_id"), None if ok else error[:500])
        if not ok and error:
            from agos_core.db.activity import add_activity

            add_activity(
                core.db,
                workspace_id,
                kind="room.refused",
                text=f"The group's room refused {row['kind']}: {error[:300]}",
            )
            if row["kind"] in ("room-send", "room-sync"):
                _close_turn(core, chat_id, "failed", f"The group's room refused it: {error[:300]}")
    if not ok and error and chat_id is not None:
        # Logged outside the transaction: AGOS's log handler writes to the database,
        # and another thread logging while it waits for the database would hold it.
        log.warning("room job %s of chat %s refused: %s", row["kind"], chat_id, error)
    if follow and chat_id is not None:
        with transaction(core.db):
            renamed(core, workspace_id, chat_id)


# ---- the room's log → the chat -------------------------------------------------------------


def events(core: Core, workspace_id: str, room_id: str, items: list[dict[str, Any]]) -> int:
    """The room's new log events, in order. Each is taken once (room_events), so a
    restarted gateway reading the log again changes nothing. Returns AGOS's cursor."""
    chat_id = chat_of_room(core, workspace_id, room_id)
    if chat_id is None:
        return 0
    cursor = int(_room_row(core, workspace_id, chat_id)["cursor"])
    for event in sorted(items, key=lambda e: int(e.get("seq") or 0)):
        seq = int(event.get("seq") or 0)
        event_id = str(event.get("event_id") or "")
        kind = str(event.get("kind") or "")
        if not event_id or seq <= 0:
            continue
        with transaction(core.db):
            if group_rooms.take_event(core.db, workspace_id, room_id, event_id, seq, kind):
                _take_event(core, workspace_id, chat_id, room_id, event)
            cursor = max(cursor, seq)
            group_rooms.advance(core.db, chat_id, seq)
    return cursor


def _take_event(
    core: Core, workspace_id: str, chat_id: int, room_id: str, event: dict[str, Any]
) -> None:

    kind = str(event.get("kind") or "")
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return
    room = _room_row(core, workspace_id, chat_id)
    current = str(room["discussion"] or "") if room is not None else ""
    if kind == "message.member":
        member = str(payload.get("member_id") or "")
        text = str(payload.get("text") or "").strip()
        if not text:
            return
        message_id = chat_writes.add_chat_message(
            core.db, workspace_id, chat_id, "agent", text, speaker=_speaker(member)
        )

        group_rooms.event_line(
            core.db, workspace_id, room_id, str(event.get("event_id")), message_id
        )
        found = _live(core, chat_id)
        if found is not None:
            found[1].turn.text = ""  # the live preview of that member's words is now a message
            found[1].turn.version += 1
        return
    if kind == "turn.started":
        member = str(payload.get("member_id") or "")
        found = _live(core, chat_id)
        if found is not None:
            chat_turns.set_speaker(core.db, found[0], _speaker(member))
            found[1].speaker = _speaker(member)
            found[1].turn.version += 1
        return
    if kind == "turn.failed":
        member = str(payload.get("member_id") or "")
        from agos_core.actions import voice

        error = str(payload.get("error") or "failed")[:300]
        chat_writes.add_chat_message(
            core.db,
            workspace_id,
            chat_id,
            "agent",
            f"⚠️ {voice.name_of(core, workspace_id, _speaker(member))} couldn't answer: {error}",
            speaker=SPEAKER_AGOS,
        )
        return
    if kind == "room.activity":
        discussion = str(payload.get("discussion_event_id") or "")
        if room is None or discussion != current:
            return  # an older message's discussion: a newer one is on its way
        # Hermes ended the discussion (settled, or its own round/message limit).
        _close_turn(core, chat_id, "completed")
        return
    if kind == "room.stop_requested":
        _close_turn(core, chat_id, "stopped")


# ---- live work and approvals (Hermes's on_room_member_activity hook) ------------------------

_TOOL_KEYS = ("tool", "name", "tool_name")


def live(core: Core, workspace_id: str, room_id: str, items: list[dict[str, Any]]) -> None:
    """A member's work as it happens: the chat's live view shows it."""
    chat_id = chat_of_room(core, workspace_id, room_id)
    if chat_id is None:
        return
    found = _live(core, chat_id)
    if found is None:
        return
    turn_id, state = found
    for item in items:
        kind = str(item.get("kind") or "")
        payload = item.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        member = str(item.get("member_id") or "")
        if state.speaker != _speaker(member):
            state.speaker = _speaker(member)
            chat_turns.set_speaker(core.db, turn_id, _speaker(member))
        tool = next((str(payload[k]) for k in _TOOL_KEYS if payload.get(k)), "tool")
        preview = str(
            payload.get("preview") or payload.get("context") or payload.get("summary") or ""
        )
        if kind == "tool.started":
            state.turn.apply({"event": "tool.started", "tool": tool, "preview": preview})
        elif kind == "tool.completed":
            state.turn.apply(
                {
                    "event": "tool.completed",
                    "tool": tool,
                    "preview": preview,
                    "error": payload.get("error"),
                    "duration": payload.get("duration"),
                }
            )
        elif kind == "message.delta":
            state.turn.apply(
                {
                    "event": "message.delta",
                    "delta": str(payload.get("text") or payload.get("delta") or ""),
                }
            )
        elif kind == "reasoning.delta":
            state.turn.apply(
                {"event": "reasoning.available", "text": str(payload.get("text") or "")}
            )
    state.turn.version += 1
