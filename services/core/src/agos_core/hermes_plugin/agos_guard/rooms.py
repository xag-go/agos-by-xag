"""AGOS ↔ this root's Hermes rooms, inside the workspace's gateway (ADR 0020).

A workspace on its own Hermes root runs its group chats as Hermes hosted rooms. The
room service lives in this gateway process (Hermes starts it with the gateway), so
the bridge runs here too and calls it directly — no `hermes serve`, no JSON-RPC.
Two threads:

- the jobs thread asks AGOS for room jobs (`room-next`, a long ask: AGOS answers the
  moment one is queued): make a room (or disband the old one and make the new one
  after a membership change), send his message (the service's own `send`), stop the
  room, answer a member's approval (`approve_room_task`, once / deny only);
- the log thread reads Hermes's room logs here every second and sends what is new
  after AGOS's cursor (`room-events`, AGOS takes each event once), the live work
  Hermes's `on_room_member_activity` hook gave (`room-live`), and what each room
  holds in Hermes now — its members and their waiting approvals — when it changed
  (`room-held`; AGOS keeps no copy of it, and each room-next answer says which report
  AGOS has, so a restarted core is told again). Approvals also go at once from the
  hook (`room-approval`).

An older core has no room-held and waits 2 s on room-next whatever it is asked (its
answer carries no `held`): it is told what the rooms hold with each ask, as before.

Only the root's own (Co-Founder's) plugin runs it: a member tenant's bridge file names
its member, and a member never drives the workspace's rooms.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from typing import Any

log = logging.getLogger("agos.rooms")

THREAD = "main"
# How long a room-next ask waits at the core for a job (a newer core; AGOS rings
# when one is queued).
JOBS_WAIT_S = 20.0
READ_EVERY_S = 1.0  # the room logs and live work → AGOS
HELD_EVERY_S = 3.0  # what the rooms hold → AGOS, when it changed


def _fresh_state() -> dict[str, Any]:
    return {
        "thread": None,
        "reader": None,
        "names": {},
        "rooms": {},  # room → {cursor, chat, name}, as AGOS last said
        "cursors": {},  # room → how far AGOS has taken its log
        "core": None,  # None: not heard yet; "new": has room-held; "old": doesn't
        "told": None,  # which report of what the rooms hold AGOS has
        "fresh": False,  # jobs were done: the next ask brings the rooms at once
        "held_due": False,  # tell what the rooms hold at the next read
    }


_state: dict[str, Any] = _fresh_state()
_live: deque[tuple[str, dict[str, Any]]] = deque(maxlen=2000)
_lock = threading.Lock()
_poke = threading.Event()  # the log thread reads now (jobs done, new rooms)
LIVE_KINDS = {"tool.started", "tool.completed", "message.delta", "reasoning.delta", "turn.error"}


def _bridge() -> Any:
    from . import bridge

    return bridge


def _mine() -> bool:
    """This gateway drives the workspace's rooms: its bridge is the root's own."""
    b = _bridge().bridge()
    return b is not None and not b.get("member")


def _service() -> Any:
    from tui_gateway import methods_groups  # type: ignore[import-not-found, unused-ignore]

    return methods_groups.get_hosted_room_service()


def start() -> None:
    if not _bridge()._in_gateway():
        return
    for key, target, name in (
        ("thread", _forever, "agos-rooms"),
        ("reader", _read_forever, "agos-rooms-log"),
    ):
        running = _state.get(key)
        if running is not None and running.is_alive():
            continue
        thread = threading.Thread(target=target, name=name, daemon=True)
        _state[key] = thread
        thread.start()


def _forever() -> None:
    while True:
        try:
            if not _mine():
                time.sleep(10)
                continue
            if not _round() and _state["core"] == "old":
                time.sleep(1.0)  # an older core answers after 2 s: asked as before
        except Exception as error:  # keep bridging
            log.exception("AGOS rooms: round failed")
            _bridge()._broken(
                _bridge()._name_of(error, "tui_gateway.methods_groups.get_hosted_room_service"),
                error,
            )
            time.sleep(5)


def _round() -> bool:
    """One ask for room jobs (AGOS answers when one is queued, or after JOBS_WAIT_S),
    and the jobs it handed done. True when there were jobs."""
    post = _bridge().post
    body: dict[str, Any] = {"wait": 0.0 if _state["fresh"] else JOBS_WAIT_S}
    _state["fresh"] = False
    if _state["core"] == "old":
        body = {"rooms": _held()}  # an older core hears it only with each ask
    answer = post("room-next", body, JOBS_WAIT_S + 15)
    if answer is None:
        time.sleep(3)
        return False
    _heard(answer)
    items = answer.get("items") or []
    for item in items:
        ok, error, event = _do(item)
        if ok is None:
            continue  # the room service isn't up yet: AGOS hands it again
        post("room-done", {"id": int(item["id"]), "ok": ok, "error": error, "event": event}, 15)
    if items:
        # The rooms as these jobs left them (a new room, a new name) come with an
        # ask that doesn't wait, and what they hold is told at once.
        _state["fresh"] = True
        _state["held_due"] = True
        _poke.set()
    return bool(items)


def _heard(answer: dict[str, Any]) -> None:
    """AGOS's rooms (names, cursors) and which report of what they hold it has."""
    rooms = answer.get("rooms") or {}
    with _lock:
        _state["rooms"] = {str(k): v for k, v in rooms.items() if isinstance(v, dict)}
        _state["names"] = {
            str(v.get("name")): f"room:{v.get('chat')}" for v in _state["rooms"].values()
        }
        cursors: dict[str, int] = _state["cursors"]
        for room_id, info in _state["rooms"].items():
            cursors[room_id] = max(cursors.get(room_id, 0), int(info.get("cursor") or 0))
        for gone in set(cursors) - set(_state["rooms"]):
            cursors.pop(gone, None)
        if "held" in answer:
            _state["core"] = "new"
            _state["told"] = str(answer.get("held") or "")
        else:
            _state["core"] = "old"
    _poke.set()


def _read_forever() -> None:
    last_held = 0.0
    while True:
        _poke.wait(READ_EVERY_S)
        _poke.clear()
        try:
            if not _mine():
                time.sleep(10)
                continue
            due = time.monotonic() - last_held >= HELD_EVERY_S
            if _read_once(held=due) and due:
                last_held = time.monotonic()
        except Exception as error:  # keep bridging
            log.exception("AGOS rooms: reading the room logs failed")
            _bridge()._broken(_bridge()._name_of(error, "gateway.hosted_rooms.read_events"), error)
            time.sleep(5)


def _read_once(held: bool = False) -> bool:
    """The rooms' new log events and live work → AGOS; what they hold too when
    `held` (or jobs were just done) and it isn't the report AGOS has. False while
    AGOS hasn't answered a room-next yet (its rooms aren't known)."""
    if _state["core"] is None:
        return False
    _flush_live()
    with _lock:
        cursors = dict(_state["cursors"])
    for room_id, cursor in cursors.items():
        _push(room_id, cursor)
    _flush_live()
    if (held or _state["held_due"]) and _state["core"] == "new":
        _state["held_due"] = False
        _tell_held()
    return True


def _tell_held() -> None:
    held = _held()
    mark = hashlib.sha256(json.dumps(held, sort_keys=True, default=str).encode()).hexdigest()[:32]
    if mark == _state["told"]:
        return
    if _bridge().post("room-held", {"rooms": held, "hash": mark}, 15) is not None:
        _state["told"] = mark


def _do(item: dict[str, Any]) -> tuple[bool | None, str, str]:
    """(done?, Hermes's refusal, Hermes's event id). None: try again later."""
    service = _service()
    if service is None:
        return None, "", ""
    kind, job = str(item.get("kind") or ""), item.get("job") or {}
    room_id = str(job.get("room_id") or "")
    try:
        if kind == "room-sync":
            if job.get("disband"):
                _disband(service, str(job["disband"]))
            # Hermes checks the roster itself: only profiles of THIS root (the wall
            # between workspaces), 2-6 members.
            service.create_room(
                room_id=room_id,
                name=str(job.get("name") or room_id),
                members=list(job.get("members") or []),
            )
            return True, "", ""
        if kind == "room-rename":
            # Hermes's own rename (its RPC groups.rename runs the same function).
            from gateway import hosted_rooms as hr  # type: ignore[import-not-found, unused-ignore]

            hr.rename_room(
                service.db_path,
                room_id=room_id,
                event_id=str(job["event_id"]),
                name=str(job["name"]),
            )
            return True, "", ""
        if kind == "room-send":
            return True, "", _send(service, room_id, str(job["event_id"]), str(job["text"]))
        if kind == "room-stop":
            service.stop_room(room_id, cancel_id=f"agos-stop-{int(time.time() * 1000)}")
            return True, "", ""
        if kind == "room-approve":
            service.approve_room_task(
                room_id,
                member_id=str(job["member_id"]),
                task_id=str(job["task_id"]),
                execution_generation=int(job["execution_generation"]),
                choice=str(job["choice"]),
                request_id=str(job["request_id"]),
            )
            return True, "", ""
    except Exception as error:  # noqa: BLE001 — told to AGOS (shown, not retried)
        log.warning("AGOS rooms: %s refused: %s", kind, error)
        _bridge()._broken(
            _bridge()._name_of(error, f"tui_gateway.hosted_room_service.HostedRoomService.{kind}"),
            error,
        )
        return False, (str(error) or type(error).__name__)[:1500], ""
    return False, f"unknown room job {kind}", ""


def _disband(service: Any, room_id: str) -> None:
    """The old room of a group whose members changed: stopped, then disbanded (the
    same steps as Hermes's own groups.disband)."""
    from gateway import hosted_rooms as hr  # type: ignore[import-not-found, unused-ignore]

    try:
        state = hr.room_state(service.db_path, room_id=room_id, include_disbanded=True)
    except hr.HostedRoomError:
        return  # never made, or long gone
    if state.get("disbanded_at") is not None:
        return
    with _bridge()._guard("tui_gateway.hosted_room_service.HostedRoomService.stop_room"):
        service.stop_room(room_id, cancel_id="agos-members-changed")
    with _bridge()._guard("tui_gateway.hosted_room_service.HostedRoomService.revoke_room_routes"):
        service.revoke_room_routes(room_id)
    hr.disband_room(
        service.db_path,
        room_id=room_id,
        expected_gateway_id=str(state["authority_gateway_id"]),
        expected_epoch=int(state["authority_epoch"]),
    )


def _send(service: Any, room_id: str, client_id: str, text: str) -> str:
    """His message into the room: the room service's own public send (Hermes logs it
    as a user message from "desktop"; the members read it as "User" either way)."""
    from gateway import hosted_rooms as hr  # type: ignore[import-not-found, unused-ignore]

    event_id = hr.user_event_id(client_id)
    event = service.send(
        room_id=room_id, event_id=event_id, payload={"text": text, "thread_id": THREAD}
    )
    return str(event.get("event_id") or event_id)


def _push(room_id: str, cursor: int) -> None:
    """The room's log after AGOS's cursor → AGOS (it takes each event once); its
    answer moves the cursor, so the same events aren't read out again."""
    from gateway import hosted_rooms as hr  # type: ignore[import-not-found, unused-ignore]

    service = _service()
    db = service.db_path if service is not None else hr.default_db_path()
    try:
        page = hr.read_events(
            db, room_id=room_id, since_seq=cursor, limit=200, include_disbanded=True
        )
    except hr.HostedRoomError:
        return
    events = [
        {k: e.get(k) for k in ("seq", "event_id", "kind", "actor", "payload", "created_at")}
        for e in page.get("events") or []
        if isinstance(e, dict)
    ]
    if not events:
        return
    answer = _bridge().post("room-events", {"roomId": room_id, "events": events}, 30)
    if answer is None:
        return  # read and sent again at the next read
    # AGOS took what it takes of these (it skips an event it can't place): past them.
    top = max(int(e.get("seq") or 0) for e in events)
    with _lock:
        if room_id in _state["cursors"]:
            _state["cursors"][room_id] = max(
                int(_state["cursors"][room_id]), int(answer.get("cursor") or 0), top
            )


# ---- Hermes's on_room_member_activity hook (fires in this process only) ---------------


def member_activity(
    room_id: str = "",
    member_id: str = "",
    kind: str = "",
    payload: Any = None,
    task_id: str = "",
    execution_generation: Any = None,
    **_: Any,
) -> None:
    if not room_id.startswith("agos-") or not _mine():
        return
    data = payload if isinstance(payload, dict) else {}
    if kind == "request.opened":
        threading.Thread(
            target=_approval,
            args=(room_id, member_id, task_id, execution_generation, data),
            name="agos-room-approval",
            daemon=True,
        ).start()
        return
    if kind in LIVE_KINDS:
        small = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))}
        for k in ("text", "delta", "preview", "context"):
            if isinstance(small.get(k), str):
                small[k] = str(small[k])[:2000]
        with _lock:
            _live.append((room_id, {"member_id": member_id, "kind": kind, "payload": small}))


def _flush_live() -> None:
    with _lock:
        batch = list(_live)
        _live.clear()
    by_room: dict[str, list[dict[str, Any]]] = {}
    for room_id, item in batch:
        by_room.setdefault(room_id, []).append(item)
    for room_id, items in by_room.items():
        _bridge().post("room-live", {"roomId": room_id, "items": items[-200:]}, 15)


_told: set[str] = set()  # approval request ids already sent to AGOS at once


def _asks(room_id: str, data: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
    """Every approval a member of this room waits on (Hermes's own room status:
    HostedRoomService.status(room_id)["pending_actions"]); None when the service
    can't say."""
    service = _service()
    if service is None:
        return None
    try:
        pending = service.status(room_id).get("pending_actions") or []
    except Exception as error:  # noqa: BLE001 - a room the service doesn't hold (yet)
        _bridge()._broken("tui_gateway.hosted_room_service.HostedRoomService.status", error)
        return None
    out = []
    for action in pending:
        if not isinstance(action, dict) or action.get("kind") != "approval":
            continue
        request_id = str(action.get("request_id") or "")
        if not request_id:
            continue
        raw = action.get("approval")
        approval: dict[str, Any] = raw if isinstance(raw, dict) else {}
        extra = data or {}
        out.append(
            {
                "member_id": str(action.get("member_id") or ""),
                "task_id": str(action.get("task_id") or ""),
                "execution_generation": int(action.get("execution_generation") or 0),
                "request_id": request_id,
                "command": str(approval.get("command") or extra.get("command") or "")[:8000],
                "description": str(approval.get("description") or extra.get("description") or "")[
                    :2000
                ],
            }
        )
    return out


def _members(room_id: str) -> list[dict[str, Any]] | None:
    """The room's members as Hermes keeps them (its hosted-room row, made by
    create_room); None while Hermes has no such room (not made yet, or disbanded)."""
    from gateway import hosted_rooms as hr  # type: ignore[import-not-found, unused-ignore]

    service = _service()
    db = service.db_path if service is not None else hr.default_db_path()
    try:
        state = hr.room_state(db, room_id=room_id)
    except hr.HostedRoomError:  # no such room (not made yet, or disbanded)
        return None
    except Exception as error:  # noqa: BLE001 - the room is taken as it is meanwhile
        _bridge()._broken("gateway.hosted_rooms.room_state", error)
        return None
    members = state.get("members")
    if not isinstance(members, list):
        return None
    return [m for m in members if isinstance(m, dict)][
        :128
    ]  # H: gateway/hosted_rooms.py:30 MAX_MEMBERS


def _held() -> dict[str, dict[str, Any]]:
    """What each of AGOS's rooms holds in Hermes now, for AGOS (it keeps no copy):
    its members and the approvals they wait on."""
    with _lock:
        known = list(_state["rooms"])
    out: dict[str, dict[str, Any]] = {}
    for room_id in known:
        asks = _asks(room_id)
        members = _members(room_id)
        if asks is None and members is None:
            continue
        out[room_id] = {"pending": (asks or [])[:50], "members": members}
    return out


def _pending(room_id: str, data: dict[str, Any] | None = None) -> bool:
    """A new approval → AGOS at once (each request once here; the log thread tells
    the whole set anyway)."""
    asks = _asks(room_id, data)
    for ask in asks or []:
        if ask["request_id"] in _told:
            continue
        body = {
            "roomId": room_id,
            "memberId": ask["member_id"],
            "taskId": ask["task_id"],
            "executionGeneration": ask["execution_generation"],
            "requestId": ask["request_id"],
            "command": ask["command"],
            "description": ask["description"],
        }
        if _bridge().post("room-approval", body, 15) is not None:
            _told.add(ask["request_id"])
    return bool(asks)


def _approval(
    room_id: str, member_id: str, task_id: str, generation: Any, data: dict[str, Any]
) -> None:
    """Hermes's request.opened: tell AGOS as soon as the room's status holds it (the
    log thread also checks every room, so nothing waits on this)."""
    del member_id, task_id, generation
    for _ in range(50):
        if _pending(room_id, data):
            return
        time.sleep(0.2)


# ---- a room member's AGOS tools know their group chat ------------------------------------


def room_address(user_message: Any) -> tuple[str, str] | None:
    """("room:<chat>", handle) of a room turn, from Hermes's own room prompt
    ('[Discussion: "<room name>"] You are @<handle>, …')."""
    import re

    text = _bridge()._text_of(user_message)
    found = re.search(r'\[Discussion: "(.+?)"\] You are @([A-Za-z0-9][A-Za-z0-9._:-]*)', text)
    if found is None:
        return None
    with _lock:
        where = _state["names"].get(found.group(1))
    return (str(where), found.group(2)) if where else None
