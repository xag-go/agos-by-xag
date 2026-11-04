"""How the gateways' long asks wait (api/bridge_waits.py): on a doorbell rung by
whatever queues something for them (with a look every few seconds for what nothing
rang for), and a team member's copy of the plugin doesn't ask for what never comes
to it."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from channels_rig import env, fake_telegram  # noqa: F401 - fixtures
from hermes_channel_rig import _hermes_bot
from test_hermes_roots import _new, roots_env  # noqa: F401 - fixture
from test_rooms import _say, group  # noqa: F401 - fixture

from agos_core.actions import channels, hermes_channel
from agos_core.actions.services.channel import bridge_waits as waits
from agos_core.api import bridge_rooms, bridge_turns, hermes_bridge
from agos_core.db.rows import now
from agos_core.engine import doorbell
from agos_core.hermes_plugin.agos_guard import bridge as plugin


def _ask(client: Any, core: Any, ws: str, path: str, body: dict[str, Any]) -> Any:
    key = hermes_channel.bridge_key(core, ws)
    return client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )


def test_a_members_next_is_held_without_a_query(roots_env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """An older plugin's member copy still asks: it gets nothing, after a wait (so it
    doesn't spin), and AGOS runs no query for it."""
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    taken: list[str] = []
    monkeypatch.setattr(bridge_turns, "MEMBER_HOLD_S", 0.3)

    def take(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        taken.append("x")
        return []

    monkeypatch.setattr(hermes_channel, "take_inbox", take)
    began = time.monotonic()
    got = _ask(client, core, ws, "next", {"member": "writer"})
    assert got.status_code == 200 and got.json()["items"] == []
    assert time.monotonic() - began >= 0.3 and taken == []


def test_a_members_copy_of_the_plugin_does_not_ask_next(monkeypatch: Any) -> None:
    asked: list[str] = []
    slept: list[float] = []
    monkeypatch.setattr(
        plugin,
        "bridge",
        lambda: {"core": "http://127.0.0.1:1", "workspace": "w", "key": "k", "member": "writer"},
    )
    monkeypatch.setattr(plugin, "post", lambda path, *_a, **_k: asked.append(path))
    monkeypatch.setattr(plugin, "_serving", lambda: True)
    monkeypatch.setattr(time, "sleep", slept.append)
    plugin._poll_once()
    assert asked == [] and slept == [10]
    # The workspace's own copy (no member) still asks.
    monkeypatch.setattr(
        plugin, "bridge", lambda: {"core": "http://127.0.0.1:1", "workspace": "w", "key": "k"}
    )
    plugin._poll_once()
    assert asked == ["next"]


# ---- the doorbell (F1): a long ask wakes when something is queued for it ---------------


def _room_next(client: Any, core: Any, ws: str, out: list[tuple[float, Any]]) -> threading.Thread:
    """/room-next asked from another thread (the gateway), its answer and when."""

    def ask() -> None:
        got = _ask(client, core, ws, "room-next", {})
        out.append((time.monotonic(), got.json()))

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while (doorbell.INBOX, ws) not in doorbell._waiting and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (doorbell.INBOX, ws) in doorbell._waiting
    return thread


def _inbox_sql(said: list[str]) -> list[str]:
    return [s for s in said if "hermes_inbox" in s]


def test_a_queued_room_job_wakes_the_waiting_ask_at_once(group: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    monkeypatch.setattr(bridge_rooms, "ROOM_WAIT_S", 10.0)
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)  # only the bell can answer in time
    out: list[tuple[float, Any]] = []
    thread = _room_next(client, core, ws, out)
    time.sleep(0.2)
    queued = time.monotonic()
    _say(core, ws, chat, "write a launch post")  # rooms._queue rings
    thread.join(5)
    assert out, "the ask didn't wake"
    answered, got = out[0]
    assert answered - queued < 1.0
    # The room's sync and the message ring together (doorbell.together): one answer.
    assert [j["kind"] for j in got["items"]] == ["room-sync", "room-send"]


def test_room_jobs_queued_before_the_ask_come_in_one_answer(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "write a launch post")
    got = _ask(client, core, ws, "room-next", {"wait": 2}).json()
    assert [j["kind"] for j in got["items"]] == ["room-sync", "room-send"]


def test_a_hand_over_rings_once_both_room_jobs_are_in(group: Any) -> None:  # noqa: F811
    """Each ring is heard with every job of the step already queued: an ask that wakes
    on it can't take the room's sync without the message."""
    _client, core, ws, chat = group
    seen: list[list[str]] = []

    class Heard:
        def ring(self) -> None:
            rows = core.db.execute(
                "SELECT kind FROM hermes_inbox WHERE workspace_id = ? ORDER BY id", (ws,)
            ).fetchall()
            seen.append([str(r["kind"]) for r in rows])

    key = (doorbell.INBOX, ws)
    doorbell._waiting.setdefault(key, set()).add(Heard())  # type: ignore[arg-type]
    try:
        _say(core, ws, chat, "write a launch post")
    finally:
        doorbell._waiting.pop(key, None)
    assert seen and all(s[-2:] == ["room-sync", "room-send"] for s in seen), seen


def test_together_holds_this_threads_rings_until_its_block_ends() -> None:
    rung: list[str] = []

    class Heard:
        def __init__(self, name: str) -> None:
            self.name = name

        def ring(self) -> None:
            rung.append(self.name)

    for name in ("a", "b"):
        doorbell._waiting[(doorbell.INBOX, name)] = {Heard(name)}  # type: ignore[arg-type]
    try:
        with doorbell.together():
            doorbell.ring(doorbell.INBOX, "a")
            with doorbell.together():  # nested: the outer block rings
                doorbell.ring(doorbell.INBOX, "b")
                doorbell.ring(doorbell.INBOX, "a")
            assert rung == []
            # Another thread's ring is not held.
            other = threading.Thread(target=doorbell.ring, args=(doorbell.INBOX, "b"))
            other.start()
            other.join()
            assert rung == ["b"]
        assert rung == ["b", "a", "b"]  # once each, in order
        try:
            with doorbell.together():
                doorbell.ring(doorbell.INBOX, "a")
                raise RuntimeError("the step failed")
        except RuntimeError:
            pass
        assert rung[-1] == "a"  # what got queued before the failure still rings
        doorbell.ring(doorbell.INBOX, "b")
        assert rung[-1] == "b"  # nothing held after the block
    finally:
        for name in ("a", "b"):
            doorbell._waiting.pop((doorbell.INBOX, name), None)


def test_an_idle_ask_runs_no_query_while_it_waits(roots_env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    monkeypatch.setattr(bridge_rooms, "ROOM_WAIT_S", 1.5)
    said: list[str] = []
    core.db.set_trace_callback(said.append)
    try:
        got = _ask(client, core, ws, "room-next", {})
    finally:
        core.db.set_trace_callback(None)
    assert got.json()["items"] == []
    # One look when asked, one when the wait ends (it was 9 looks per 2 s).
    assert len(_inbox_sql(said)) == 2


def test_the_fallback_finds_a_row_another_process_wrote(
    roots_env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Nothing rings for a row written outside this process: the ask still finds it
    at its next look (doorbell.FALLBACK_S)."""
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    monkeypatch.setattr(bridge_rooms, "ROOM_WAIT_S", 10.0)
    monkeypatch.setattr(doorbell, "FALLBACK_S", 0.3)
    path = str(core.db.execute("PRAGMA database_list").fetchone()[2])
    out: list[tuple[float, Any]] = []
    thread = _room_next(client, core, ws, out)
    other = sqlite3.connect(path, isolation_level=None)
    try:
        other.execute(
            """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)
               VALUES (?, 'room:1', '{}', 'room-send', ?)""",
            (ws, now()),
        )
    finally:
        other.close()
    written = time.monotonic()
    thread.join(5)
    assert out, "the fallback look didn't come"
    answered, got = out[0]
    assert [j["kind"] for j in got["items"]] == ["room-send"]
    assert answered - written < 2.0


def test_every_writer_of_the_inbox_rings() -> None:
    """A writer that doesn't ring is only found by the fallback look (5 s later)."""
    root = Path(hermes_bridge.__file__).resolve().parents[1]
    # The inbox's repository (db/hermes_inbox.py) rings nothing (a db module imports no
    # engine): every module that writes through it, or still by hand, rings itself.
    repository = root / "db" / "hermes_inbox.py"
    assert "INTO hermes_inbox" in repository.read_text()
    silent = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p != repository
        and ("INTO hermes_inbox" in (text := p.read_text()) or "hermes_inbox.put(" in text)
        and "doorbell.ring(doorbell.INBOX" not in text
    ]
    assert silent == []


def test_a_queued_reply_wakes_the_waiting_outbox_at_once(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """AGOS's reply for Telegram goes to the gateway's waiting ask when it is queued
    (it was looked for every 0.5 s); with no 👀 waiting the ask runs no query between."""
    client, core, _fake, _tg, ws = env
    cid, _key = _hermes_bot(client, core, ws)
    monkeypatch.setattr(waits, "OUTBOX_WAIT_S", 0.1)
    _ask(client, core, ws, "outbox", {})  # what connecting queued
    monkeypatch.setattr(waits, "OUTBOX_WAIT_S", 10.0)
    monkeypatch.setattr(doorbell, "FALLBACK_S", 10.0)  # only the bell can answer in time
    out: list[tuple[float, Any]] = []

    def ask() -> None:
        got = _ask(client, core, ws, "outbox", {})
        out.append((time.monotonic(), got.json()))

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while (doorbell.OUTBOX, ws) not in doorbell._waiting and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)
    queued = time.monotonic()
    channels._queue(core, cid, "42:0", "hello from AGOS", "test:1")
    thread.join(5)
    assert out, "the outbox didn't wake"
    answered, got = out[0]
    assert [s["text"] for s in got["send"]] == ["hello from AGOS"]
    assert answered - queued < 0.4


# ---- the plugin's live events (F6): the agent never waits for AGOS ---------------------


def test_a_tool_call_does_not_wait_for_agos_and_its_end_comes_after_its_text(
    monkeypatch: Any,
) -> None:
    busy = threading.Event()
    posted: list[str] = []

    def post(path: str, _body: dict[str, Any], _timeout: float = 30) -> dict[str, Any]:
        if path == "events":
            busy.wait(5)  # AGOS's core busy for a while
        posted.append(path)
        return {}

    monkeypatch.setattr(plugin, "post", post)
    key = ("s9", "u9")
    plugin._turns[key] = 9
    plugin._busy[key] = "agos:3"
    began = time.monotonic()
    plugin.tool_started("terminal", {"command": "ls"}, "s9", "u9")
    assert time.monotonic() - began < 0.5  # the tool runs now, AGOS hears it after
    threading.Timer(0.3, busy.set).start()
    plugin._finish("s9", "u9", "done")
    assert posted == ["events", "turn-finish"]  # the end only after its live text
    plugin._closed.pop(key, None)
