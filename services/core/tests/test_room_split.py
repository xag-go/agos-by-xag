"""The plugin's room work, split (F4): room jobs come by a true long ask on room-next,
and the room logs are read in the gateway (Hermes's room service) every second, sent
to AGOS only when something is new; what the rooms hold (members, waiting approvals)
is told on its own ask, only when it changed or when AGOS hasn't got it (a core that
restarted). An older core (no `held` in its answer) still hears it with every ask;
an older plugin (no `wait`, `rooms` with each ask) is answered as before.

The gateway side is played with stand-ins for Hermes's room service and its
gateway.hosted_rooms module (as in test_hermes_channel); the core side through the
bridge, as in test_rooms."""

from __future__ import annotations

import sys
import time
import types
from typing import Any

import pytest
from test_hermes_roots import roots_env  # noqa: F401 - fixture
from test_room_members_in_hermes import _as_hermes_keeps
from test_rooms import _bridge, _jobs, _say, group  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, rooms
from agos_core.api import bridge_rooms
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction
from agos_core.hermes_plugin.agos_guard import bridge as plugin_bridge
from agos_core.hermes_plugin.agos_guard import rooms as plugin_rooms

ROOM = "agos-c7-g1"


# ---- the gateway side, against stand-ins -------------------------------------------------


class HostedRoomError(Exception):
    pass


class Service:
    """Hermes's hosted-room service, as the plugin calls it."""

    db_path = "rooms.db"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.pending: dict[str, list[dict[str, Any]]] = {}

    def create_room(self, *, room_id: str, name: str, members: list[dict[str, Any]]) -> None:
        self.calls.append(("create", room_id, [m["handle"] for m in members]))

    def send(self, *, room_id: str, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("send", room_id, payload["text"]))
        return {"event_id": event_id}

    def stop_room(self, room_id: str, cancel_id: str = "") -> None:
        self.calls.append(("stop", room_id))

    def revoke_room_routes(self, room_id: str) -> None:
        self.calls.append(("revoke", room_id))

    def approve_room_task(self, room_id: str, **job: Any) -> None:
        self.calls.append(("approve", room_id, job["choice"]))

    def status(self, room_id: str) -> dict[str, Any]:
        return {"pending_actions": self.pending.get(room_id, [])}


class Gateway:
    """The stand-ins, the room logs and members Hermes holds, and what AGOS was sent."""

    def __init__(self) -> None:
        self.service = Service()
        self.log: dict[str, list[dict[str, Any]]] = {}
        self.members: dict[str, list[dict[str, Any]]] = {}
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.next_answer: dict[str, Any] = {"items": [], "rooms": {}, "held": ""}

    def event(self, room_id: str, seq: int, text: str) -> None:
        self.log.setdefault(room_id, []).append(
            {
                "seq": seq,
                "event_id": f"e{seq}",
                "kind": "message.member",
                "actor": {"kind": "member", "id": "writer"},
                "payload": {"text": text},
                "created_at": "2026-10-24T00:00:00Z",
            }
        )

    def post(self, path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any] | None:
        self.sent.append((path, body))
        if path == "room-next":
            answer, self.next_answer = self.next_answer, {**self.next_answer, "items": []}
            return answer
        if path == "room-events":
            return {"cursor": max(int(e["seq"]) for e in body["events"])}
        if path == "room-held":
            return {"held": body["hash"]}
        return {"ok": True}

    def paths(self) -> list[str]:
        out = [p for p, _b in self.sent]
        self.sent.clear()
        return out


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    hr = types.ModuleType("gateway.hosted_rooms")
    hr.HostedRoomError = HostedRoomError  # type: ignore[attr-defined]
    hr.user_event_id = lambda client_id: f"user:{client_id}"  # type: ignore[attr-defined]
    hr.default_db_path = lambda: "rooms.db"  # type: ignore[attr-defined]

    def read_events(
        db: str, *, room_id: str, since_seq: int, limit: int, include_disbanded: bool
    ) -> dict[str, Any]:
        return {"events": [e for e in g.log.get(room_id, []) if e["seq"] > since_seq][:limit]}

    def room_state(db: str, *, room_id: str, include_disbanded: bool = False) -> dict[str, Any]:
        if room_id not in g.members:
            raise HostedRoomError(room_id)
        return {
            "members": g.members[room_id],
            "disbanded_at": None,
            "authority_gateway_id": "gw",
            "authority_epoch": 1,
        }

    def disband_room(
        db: str, *, room_id: str, expected_gateway_id: str, expected_epoch: int
    ) -> None:
        g.service.calls.append(("disband", room_id))
        g.members.pop(room_id, None)

    hr.read_events = read_events  # type: ignore[attr-defined]
    hr.room_state = room_state  # type: ignore[attr-defined]
    hr.disband_room = disband_room  # type: ignore[attr-defined]
    package = types.ModuleType("gateway")
    package.hosted_rooms = hr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", package)
    monkeypatch.setitem(sys.modules, "gateway.hosted_rooms", hr)
    monkeypatch.setattr(plugin_rooms, "_service", lambda: g.service)
    monkeypatch.setattr(plugin_bridge, "post", g.post)
    monkeypatch.setattr(
        plugin_bridge,
        "bridge",
        lambda: {"core": "http://127.0.0.1:1", "workspace": "w", "key": "k"},
    )
    monkeypatch.setattr(plugin_rooms, "_state", plugin_rooms._fresh_state())
    plugin_rooms._live.clear()
    return g


def _room(cursor: int = 0) -> dict[str, Any]:
    return {ROOM: {"cursor": cursor, "chat": 7, "name": "Launch"}}


def test_his_message_comes_by_a_long_ask_and_the_reply_by_the_local_log(
    gateway: Gateway,
) -> None:
    job = {"room_id": ROOM, "event_id": "c1", "text": "write the post"}
    gateway.next_answer = {
        "items": [{"id": 1, "kind": "room-send", "job": job}],
        "rooms": _room(),
        "held": "",
    }
    assert plugin_rooms._round() is True
    ask = gateway.sent[0]
    # A true long ask: the core waits for a job; nothing of the rooms rides on it.
    assert ask == ("room-next", {"wait": plugin_rooms.JOBS_WAIT_S})
    assert gateway.service.calls == [("send", ROOM, "write the post")]
    assert gateway.sent[1] == ("room-done", {"id": 1, "ok": True, "error": "", "event": "user:c1"})
    assert [p for p, _b in gateway.sent] == ["room-next", "room-done"]  # no log reading here
    gateway.sent.clear()
    # After jobs, the next ask doesn't wait: it brings the rooms as the jobs left them.
    plugin_rooms._round()
    assert gateway.sent[0] == ("room-next", {"wait": 0.0})
    gateway.sent.clear()
    plugin_rooms._round()
    assert gateway.sent[0] == ("room-next", {"wait": plugin_rooms.JOBS_WAIT_S})
    gateway.sent.clear()
    # The member's reply: read from Hermes's room log here, sent once.
    gateway.event(ROOM, 1, "here is a draft")
    gateway.event(ROOM, 2, "and a title")
    plugin_rooms._read_once()
    events = [b for p, b in gateway.sent if p == "room-events"]
    assert [[e["seq"] for e in b["events"]] for b in events] == [[1, 2]]
    gateway.sent.clear()
    plugin_rooms._read_once()
    assert "room-events" not in gateway.paths()  # nothing new: nothing sent
    gateway.event(ROOM, 3, "done")
    plugin_rooms._read_once()
    events = [b for p, b in gateway.sent if p == "room-events"]
    assert [[e["seq"] for e in b["events"]] for b in events] == [[3]]


def test_what_the_rooms_hold_is_told_only_when_it_changed(gateway: Gateway) -> None:
    gateway.next_answer = {"items": [], "rooms": _room(), "held": ""}
    plugin_rooms._round()
    gateway.members[ROOM] = [{"member_id": "writer", "profile": "w-writer", "handle": "writer"}]
    gateway.sent.clear()
    plugin_rooms._read_once(held=True)
    told = [b for p, b in gateway.sent if p == "room-held"]
    assert len(told) == 1 and told[0]["rooms"][ROOM]["pending"] == []
    assert told[0]["rooms"][ROOM]["members"] == gateway.members[ROOM]
    gateway.sent.clear()
    plugin_rooms._read_once(held=True)
    assert "room-held" not in gateway.paths()  # the same: not told again
    # A member waits on his approval (Hermes's pending set): told.
    gateway.service.pending[ROOM] = [
        {
            "kind": "approval",
            "request_id": "req-1",
            "member_id": "writer",
            "task_id": "t1",
            "execution_generation": 1,
            "approval": {"command": "rm -rf /tmp/x", "description": "dangerous"},
        }
    ]
    plugin_rooms._read_once(held=True)
    told = [b for p, b in gateway.sent if p == "room-held"]
    assert [a["request_id"] for a in told[0]["rooms"][ROOM]["pending"]] == ["req-1"]
    gateway.sent.clear()
    # His answer, a room job here: Hermes's approve_room_task.
    approve = {
        "room_id": ROOM,
        "member_id": "writer",
        "task_id": "t1",
        "execution_generation": 1,
        "request_id": "req-1",
        "choice": "deny",
    }
    gateway.next_answer = {
        "items": [{"id": 2, "kind": "room-approve", "job": approve}],
        "rooms": _room(),
        "held": told[0]["hash"],
    }
    plugin_rooms._round()
    assert gateway.service.calls[-1] == ("approve", ROOM, "deny")
    gateway.service.pending[ROOM] = []
    gateway.sent.clear()
    plugin_rooms._read_once(held=True)
    assert "room-held" in gateway.paths()  # gone from Hermes's set: told
    # The core restarted (its answer says it has no report): told again.
    plugin_rooms._read_once(held=True)
    assert "room-held" not in gateway.paths()
    gateway.next_answer = {"items": [], "rooms": _room(), "held": ""}
    plugin_rooms._round()
    gateway.sent.clear()
    plugin_rooms._read_once(held=True)
    assert "room-held" in gateway.paths()


def test_a_roster_change_disbands_the_old_room_and_makes_the_new_one(gateway: Gateway) -> None:
    old, new = ROOM, "agos-c7-g2"
    gateway.members[old] = [{"member_id": "writer", "handle": "writer"}]
    members = [
        {"member_id": "cofounder", "handle": "cofounder"},
        {"member_id": "editor", "handle": "editor"},
    ]
    gateway.next_answer = {
        "items": [
            {
                "id": 3,
                "kind": "room-sync",
                "job": {"room_id": new, "name": "Launch", "members": members, "disband": old},
            }
        ],
        "rooms": {new: {"cursor": 0, "chat": 7, "name": "Launch"}},
        "held": "x",
    }
    plugin_rooms._round()
    assert gateway.service.calls == [
        ("stop", old),
        ("revoke", old),
        ("disband", old),
        ("create", new, ["cofounder", "editor"]),
    ]
    assert ("room-done", {"id": 3, "ok": True, "error": "", "event": ""}) in gateway.sent
    gateway.members[new] = members
    gateway.sent.clear()
    plugin_rooms._read_once(held=True)
    told = [b for p, b in gateway.sent if p == "room-held"]
    assert list(told[0]["rooms"]) == [new] and told[0]["rooms"][new]["members"] == members


def test_an_older_core_hears_what_the_rooms_hold_with_every_ask(gateway: Gateway) -> None:
    gateway.next_answer = {"items": [], "rooms": _room()}  # no "held": an older core
    gateway.members[ROOM] = [{"member_id": "writer", "handle": "writer"}]
    plugin_rooms._round()
    gateway.sent.clear()
    plugin_rooms._round()
    path, body = gateway.sent[0]
    assert path == "room-next" and body["rooms"][ROOM]["members"] == gateway.members[ROOM]
    gateway.sent.clear()
    gateway.event(ROOM, 1, "hi")
    plugin_rooms._read_once(held=True)
    # Its log still goes by room-events; nothing on an ask it doesn't have.
    assert gateway.paths() == ["room-events"]


def test_live_work_goes_from_the_log_reader(gateway: Gateway) -> None:
    gateway.next_answer = {"items": [], "rooms": _room(), "held": ""}
    plugin_rooms._round()
    gateway.sent.clear()
    plugin_rooms._live.append(
        (ROOM, {"member_id": "writer", "kind": "tool.started", "payload": {}})
    )
    plugin_rooms._read_once()
    assert [p for p, _b in gateway.sent] == ["room-live"]


# ---- the core side ---------------------------------------------------------------------------


def _ask_of(request_id: str = "req-1") -> dict[str, Any]:
    return {
        "member_id": "writer",
        "task_id": "dtask:1",
        "execution_generation": 1,
        "request_id": request_id,
        "command": "rm -rf /tmp/x",
        "description": "dangerous",
    }


def test_the_core_hears_what_the_rooms_hold_on_its_own_ask(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "danger")
    room = f"agos-c{chat}-g1"
    _jobs(core, ws)
    assert _bridge(client, core, ws, "room-next", {"wait": 0}).json()["held"] == ""
    body = {"rooms": {room: {"pending": [_ask_of()]}}, "hash": "h1"}
    got = _bridge(client, core, ws, "room-held", body)
    assert got.status_code == 200, got.text
    assert (rooms.waiting_approval(core, ws, chat) or {}).get("request_id") == "req-1"
    assert rooms.still_asks(core, ws, chat) is True
    # Each room-next says which report AGOS has; none after a restart.
    assert _bridge(client, core, ws, "room-next", {"wait": 0}).json()["held"] == "h1"
    rooms.forget(core)
    assert _bridge(client, core, ws, "room-next", {"wait": 0}).json()["held"] == ""
    # An older plugin's report with its ask: AGOS takes it, and has no report mark.
    _bridge(client, core, ws, "room-held", body)
    old = {"rooms": {room: {"pending": [_ask_of("req-2")]}}}
    assert _bridge(client, core, ws, "room-next", old).json()["held"] == ""
    assert (rooms.waiting_approval(core, ws, chat) or {}).get("request_id") == "req-2"


def test_a_roster_hermes_holds_on_the_held_ask_makes_the_room_again(
    group: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    made = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")["job"]
    room = made["room_id"]
    held = {"rooms": {room: {"pending": [], "members": _as_hermes_keeps(made["members"])}}}
    _bridge(client, core, ws, "room-held", {**held, "hash": "a"})
    assert [j for j in _jobs(core, ws) if j["kind"] == "room-sync"] == []
    monkeypatch.setattr(agent_profiles, "ready", lambda _c, w, a: w == ws and a == "writer")
    with transaction(core.db):
        chats_repo.set_members(core.db, ws, chat, ["writer"])
    rooms.members_changed(core, ws, chat)
    sync = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")["job"]
    assert (sync["room_id"], sync["disband"]) == (f"agos-c{chat}-g2", room)


def test_room_next_waits_as_long_as_the_plugin_asks(
    roots_env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    from test_hermes_roots import _new

    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    monkeypatch.setattr(bridge_rooms, "ROOM_WAIT_S", 0.4)
    began = time.monotonic()
    assert _bridge(client, core, ws, "room-next", {"wait": 0}).json()["items"] == []
    assert time.monotonic() - began < 0.35
    began = time.monotonic()
    _bridge(client, core, ws, "room-next", {"wait": 0.8})
    assert time.monotonic() - began >= 0.8
    began = time.monotonic()
    _bridge(client, core, ws, "room-next", {})  # an older plugin: the 2 s of before
    assert 0.4 <= time.monotonic() - began < 0.8
    assert _bridge(client, core, ws, "room-next", {"wait": 99}).status_code == 422
