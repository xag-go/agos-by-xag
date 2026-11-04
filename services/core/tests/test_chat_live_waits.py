"""An open chat's live view (`/live?wait=`) waits on a doorbell rung by whatever changes
what it shows (a turn opened in the chat, the live answer moved or ended), not on a
look at the database every 0.15 s; with no answer live it waits for one to start, so
the web asks again at once instead of sleeping 4 s (F10)."""

from __future__ import annotations

import threading
import time
from typing import Any

from test_hermes_roots import _new, roots_env  # noqa: F401 - fixture
from test_rooms import _bridge, _say, group  # noqa: F401 - fixture

from agos_core.actions.services.chat import live_turns as chat_live_turns
from agos_core.api import chats as chats_api
from agos_core.engine import doorbell
from agos_core.engine.chat import live_key


def _live_in_thread(
    client: Any, ws: str, chat: int, after: int, out: list[tuple[float, Any]], wait: float = 5
) -> threading.Thread:
    """/live asked from another thread (the web), its answer and when."""

    def ask() -> None:
        got = client.get(f"/workspaces/{ws}/chats/{chat}/live?after={after}&wait={wait}")
        out.append((time.monotonic(), got.json()))

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not _listening(chat) and time.monotonic() < deadline and thread.is_alive():
        time.sleep(0.01)
    return thread


def _listening(chat: int) -> bool:
    return (doorbell.LIVE, live_key(chat)) in doorbell._waiting


def _room_live(client: Any, core: Any, ws: str, chat: int, preview: str) -> None:
    items = [
        {
            "member_id": "writer",
            "kind": "tool.started",
            "payload": {"tool": "terminal", "preview": preview},
        }
    ]
    _bridge(client, core, ws, "room-live", {"roomId": f"agos-c{chat}-g1", "items": items})


def test_an_idle_view_waits_for_an_answer_to_start(group: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)  # only the bell can answer in time
    out: list[tuple[float, Any]] = []
    thread = _live_in_thread(client, ws, chat, -1, out)
    assert _listening(chat), "the idle view answered at once instead of waiting"
    time.sleep(0.2)
    opened = time.monotonic()
    _say(core, ws, chat, "write it")  # the room's turn opens: it rings
    thread.join(5)
    assert out, "the view didn't wake"
    answered, got = out[0]
    assert got["live"] is not None and got["held"] is True
    assert answered - opened < 1.0


def test_a_live_answer_wakes_the_view_on_its_change_not_a_poll(
    group: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, core, ws, chat = group
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)
    _say(core, ws, chat, "write it")
    first = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["live"]
    assert first is not None
    looks: list[str] = []
    live_sql = "FROM chat_turns WHERE chat_id = ? AND status IN".replace("?", str(chat))
    core.db.set_trace_callback(lambda sql: looks.append(sql) if live_sql in sql else None)
    out: list[tuple[float, Any]] = []
    try:
        thread = _live_in_thread(client, ws, chat, int(first["version"]), out)
        time.sleep(1.0)  # nothing moves: it waits without asking the database
        quiet = len(looks)
        moved = time.monotonic()
        _room_live(client, core, ws, chat, "cat x")  # the answer moves: it rings
        thread.join(5)
    finally:
        core.db.set_trace_callback(None)
    assert out, "the view didn't wake"
    answered, got = out[0]
    assert got["live"]["version"] > first["version"]
    assert answered - moved < 1.0
    # It was a look every 0.15 s (~7 in that second); now the first look only (and
    # once more when it starts hearing that answer's own bell).
    assert quiet <= 2, looks


def test_an_ended_answer_ends_the_wait(group: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)
    _say(core, ws, chat, "write it")
    first = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["live"]
    out: list[tuple[float, Any]] = []
    thread = _live_in_thread(client, ws, chat, int(first["version"]), out)
    time.sleep(0.2)
    ended = time.monotonic()
    stopped = client.post(f"/workspaces/{ws}/chats/{chat}/stop")
    assert stopped.status_code in (200, 204), stopped.text
    thread.join(5)
    assert out and out[0][1]["live"] is None
    assert out[0][0] - ended < 1.0


def test_what_waits_beside_the_answer_still_shows_as_fast(
    group: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """With no answer live, what the view shows beside it (his unanswered message,
    the Co-Founder chat's asks) is looked at as often as the web asked before."""
    client, _core, ws, chat = group
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)
    monkeypatch.setattr(chat_live_turns, "AROUND_LOOK_S", 0.2)  # read by wait_live there
    around = {"pending": False, "asks": [], "questions": [], "tokens": []}
    monkeypatch.setattr(chats_api, "_around", lambda *_a: dict(around))
    out: list[tuple[float, Any]] = []
    thread = _live_in_thread(client, ws, chat, -1, out)
    time.sleep(0.3)
    changed = time.monotonic()
    around["pending"] = True
    thread.join(5)
    assert out and out[0][1]["pending"] is True and out[0][1]["live"] is None
    assert out[0][0] - changed < 1.0


def test_without_wait_the_view_answers_at_once(group: Any) -> None:  # noqa: F811
    client, _core, ws, chat = group
    got = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()
    assert got["live"] is None and got["held"] is False
