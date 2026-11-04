"""A room member's waiting approval is Hermes's own (its room service's pending set,
reported by the plugin with every room-next): AGOS keeps no copy (step 26, audit B-2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from split_parts import whole_text
from test_hermes_roots import roots_env  # noqa: F401 - fixture
from test_rooms import _bridge, _jobs, _say, group  # noqa: F401 - fixture

from agos_core.actions import channels, rooms

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _ask(request_id: str = "req-1", command: str = "rm -rf /tmp/x") -> dict[str, Any]:
    return {
        "member_id": "writer",
        "task_id": "dtask:1",
        "execution_generation": 1,
        "request_id": request_id,
        "command": command,
        "description": "dangerous",
    }


def _next(client: Any, core: Any, ws: str, held: dict[str, list[dict[str, Any]]]) -> Any:
    body = {"rooms": {room: {"pending": asks} for room, asks in held.items()}}
    return _bridge(client, core, ws, "room-next", body)


def _waiting_in_live(core: Any, chat: int) -> bool:
    from agos_core.actions import chat as chat_actions

    snap = chat_actions.live_snapshot(core, chat) or {}
    return any(
        a["kind"] == "approval" and a["status"] == "waiting" for a in snap.get("activity") or []
    )


def test_what_hermes_holds_is_shown_and_answered(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "danger")
    room = f"agos-c{chat}-g1"
    _jobs(core, ws)
    assert rooms.still_asks(core, ws, chat) is None  # not told yet: a card stays as it is
    assert _next(client, core, ws, {room: [_ask()]}).status_code == 200
    assert _waiting_in_live(core, chat)
    assert (rooms.waiting_approval(core, ws, chat) or {}).get("command") == "rm -rf /tmp/x"
    # Told again (every round, and at once on request.opened): asked once.
    _next(client, core, ws, {room: [_ask()]})
    assert (
        _bridge(
            client,
            core,
            ws,
            "room-approval",
            {
                "roomId": room,
                "memberId": "writer",
                "taskId": "dtask:1",
                "executionGeneration": 1,
                "requestId": "req-1",
                "command": "rm -rf /tmp/x",
            },
        ).json()["id"]
        is None
    )
    cards = core.db.execute(
        "SELECT count(*) FROM channel_outbox WHERE source LIKE 'roomask:%'"
    ).fetchone()[0]
    assert cards <= 1
    r = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "deny"})
    assert r.status_code in (200, 204), r.text
    job = next(j for j in _jobs(core, ws) if j["kind"] == "room-approve")["job"]
    assert job == {
        "room_id": room,
        "member_id": "writer",
        "task_id": "dtask:1",
        "execution_generation": 1,
        "request_id": "req-1",
        "choice": "deny",
    }
    # Answered: no longer waiting, even while Hermes still lists it.
    _next(client, core, ws, {room: [_ask()]})
    assert rooms.waiting_approval(core, ws, chat) is None
    assert rooms.still_asks(core, ws, chat) is False
    assert channels._answered(core, f"chatcmd:once:{chat}") == "Answered."


def test_one_hermes_dropped_is_no_longer_asked(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "danger")
    room = f"agos-c{chat}-g1"
    _jobs(core, ws)
    _next(client, core, ws, {room: [_ask()]})
    assert channels._answered(core, f"chatcmd:once:{chat}") is None  # still waits
    _next(client, core, ws, {room: []})
    assert rooms.waiting_approval(core, ws, chat) is None
    r = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "once"})
    assert r.status_code == 409
    # A new one later is asked again (a new request of Hermes's).
    _next(client, core, ws, {room: [_ask("req-2", "rm -rf /tmp/y")]})
    assert (rooms.waiting_approval(core, ws, chat) or {}).get("request_id") == "req-2"


def test_after_a_restart_hermess_set_is_told_again(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "danger")
    room = f"agos-c{chat}-g1"
    _jobs(core, ws)
    _next(client, core, ws, {room: [_ask()]})
    cards = "SELECT count(*) FROM channel_outbox WHERE source LIKE 'roomask:%'"
    before = core.db.execute(cards).fetchone()[0]
    rooms.forget(core)  # what the core was told goes with it
    assert rooms.waiting_approval(core, ws, chat) is None
    assert rooms.still_asks(core, ws, chat) is None
    _next(client, core, ws, {room: [_ask()]})
    assert (rooms.waiting_approval(core, ws, chat) or {}).get("request_id") == "req-1"
    assert core.db.execute(cards).fetchone()[0] == before  # the phone gets no second card


def test_no_copy_of_hermess_approvals_comes_back(tmp_path: Path) -> None:
    """Guard: no table for room approvals, and nothing outside the migrations names one."""
    from agos_core.db.connection import open_database

    db = open_database(tmp_path / "agos.db")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not {t for t in tables if "approval" in t}, tables
    for path in SRC.rglob("*.py"):
        if path.name == "migrations.py":
            continue
        assert not re.search(r"\broom_approvals\b", path.read_text()), path
    text = whole_text("actions/rooms.py")  # the facade and its parts (services/chat/room_*)
    assert "INSERT" not in text.split("def approval(", 1)[1].split("\ndef ", 1)[0]
