"""Step 40 (E2): core data reads that cost nothing while nothing changed."""

from __future__ import annotations

import copy
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.actions import hermes_channel
from agos_core.db.app_settings import set_setting
from agos_core.db.connection import open_database
from agos_core.engine import config_file


def _core(home: Path) -> Any:
    db = open_database(":memory:")
    return SimpleNamespace(db=db, engine=SimpleNamespace(profile_home=lambda _ws: home))


def _statements(db: sqlite3.Connection) -> list[str]:
    ran: list[str] = []
    db.set_trace_callback(ran.append)
    return ran


# ---- F8: a bot's on/off without a deep copy and a query on every call ----------------


def test_config_value_reads_one_leaf_without_copying_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: false\n")
    assert config_file.value(tmp_path, "platforms.telegram.enabled") is False

    def no_copy(_value: Any, _memo: Any = None) -> Any:
        raise AssertionError("copied the whole config")

    monkeypatch.setattr(copy, "deepcopy", no_copy)
    assert config_file.value(tmp_path, "platforms.telegram.enabled") is False
    assert config_file.value(tmp_path, "platforms.slack.enabled", "x") == "x"
    # A change Hermes writes is read at once (its stamp moved).
    (tmp_path / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: true\n")
    assert config_file.value(tmp_path, "platforms.telegram.enabled") is True
    assert config_file.value(tmp_path / "missing", "platforms.telegram.enabled") is None


def test_bot_on_is_read_again_only_when_hermes_or_agos_changed_something(
    tmp_path: Path,
) -> None:
    core = _core(tmp_path)
    assert hermes_channel.bot_on(core, "ws") is True  # no config: Hermes's default is on
    ran = _statements(core.db)
    assert hermes_channel.bot_on(core, "ws") is True
    assert ran == []  # nothing changed: no query, no file parse
    # Hermes's own switch turned off: seen on the next call.
    (tmp_path / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: false\n")
    assert hermes_channel.bot_on(core, "ws") is False
    (tmp_path / "config.yaml").write_text("platforms:\n  telegram:\n    enabled: true\n")
    assert hermes_channel.bot_on(core, "ws") is True
    # An old AGOS "off" (AGOS's own row) counts at once too.
    set_setting(core.db, hermes_channel.MOVE_OFF + "ws", True)
    assert hermes_channel.bot_on(core, "ws") is False
    core.db.execute("DELETE FROM app_settings WHERE key = ?", (hermes_channel.MOVE_OFF + "ws",))
    assert hermes_channel.bot_on(core, "ws") is True
    assert hermes_channel.bot_on(core, "other") is True


# ---- F11: the live poll asks which chat is the Co-Founder's once -------------------------


def test_live_poll_asks_for_the_cofounder_chat_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.actions import kanban_asks, kanban_board, token_watch, work_hours
    from agos_core.actions.services.channel import owner_needs
    from agos_core.api import chats as chats_api

    asked: list[str] = []

    def cofounder_chat(_core: Any, workspace_id: str) -> int:
        asked.append(workspace_id)
        return 7

    monkeypatch.setattr(owner_needs, "cofounder_chat", cofounder_chat)
    monkeypatch.setattr(chats_api, "_pending", lambda _core, _chat: False)
    monkeypatch.setattr(kanban_asks, "waiting", lambda _core, _ws: [{"ask": 1}])
    monkeypatch.setattr(kanban_board, "questions", lambda _core, _ws: [{"q": 1}])
    monkeypatch.setattr(token_watch, "waiting", lambda _core, _ws: [{"t": 1}])
    monkeypatch.setattr(work_hours, "off_line", lambda _core, _ws, _chat: None)  # no hours
    around = chats_api._around(None, "ws", 7)
    assert asked == ["ws"]
    assert around == {
        "off": None,
        "pending": False,
        "asks": [{"ask": 1}],
        "questions": [{"q": 1}],
        "tokens": [{"t": 1}],
    }
    asked.clear()
    other = chats_api._around(None, "ws", 8)  # not the Co-Founder's chat: nothing around it
    assert asked == ["ws"]
    assert other == {"off": None, "pending": False, "asks": [], "questions": [], "tokens": []}


# ---- F12: his decisions through Hermes's indexes, never a walk of every message ------


def test_decisions_read_the_learning_sessions_first_then_their_messages(
    tmp_path: Path,
) -> None:
    from agos_core.actions import learning

    db = sqlite3.connect(tmp_path / "state.db")
    # Hermes's own tables and indexes (hermes_state_common.py), the columns read here.
    db.executescript(
        """CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL,
             session_key TEXT, started_at REAL);
           CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
             session_id TEXT NOT NULL REFERENCES sessions(id), role TEXT NOT NULL,
             content TEXT, timestamp REAL NOT NULL);
           CREATE INDEX idx_messages_session ON messages(session_id, timestamp);
           CREATE INDEX idx_messages_session_id ON messages(session_id, id);
           CREATE INDEX idx_sessions_session_key ON sessions(session_key, started_at DESC);"""
    )
    db.execute("INSERT INTO sessions VALUES ('a', 'agos', 'agent:main:agos:dm:l1', 1)")
    db.execute("INSERT INTO sessions VALUES ('b', 'agos', 'agent:main:agos:dm:9', 2)")
    db.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        [
            ("a", "user", "The owner approved: the plan", 10.0),
            ("a", "assistant", "The owner approved: not his", 11.0),
            ("b", "user", "The owner denied: another chat", 12.0),
            ("a", "user", "The owner denied (Sam): the post\nHe said: too long", 13.0),
        ],
    )
    db.commit()
    plan = " ".join(
        str(r[3]) for r in db.execute("EXPLAIN QUERY PLAN " + learning._DECISIONS_SQL, ("%", 1))
    )
    assert "SCAN m" not in plan
    db.close()
    core = SimpleNamespace(engine=SimpleNamespace(profile_home=lambda _ws: tmp_path))
    got = learning.decisions(core, "ws")  # type: ignore[arg-type]
    assert [(d["kind"], d["subject"], d["agent"], d["detail"]) for d in got] == [
        ("denied", "the post", "Sam", "too long"),
        ("approved", "the plan", None, ""),
    ]


# ---- F5: who holds the shared connection is told; open_dm runs Hermes outside it ------


def test_a_long_wait_for_the_shared_connection_names_its_holder(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    from agos_core.db import connection

    monkeypatch.setattr(connection, "TELL_EVERY_S", 0.0)
    db = open_database(":memory:")
    holding = threading.Event()

    def slow_holder() -> None:
        with connection.transaction(db):
            holding.set()
            time.sleep(0.5)

    worker = threading.Thread(target=slow_holder, name="slow-one")
    worker.start()
    holding.wait(5)
    with caplog.at_level("WARNING", logger="agos_core.db.connection"):
        db.execute("SELECT 1").fetchone()
    worker.join()
    said = "\n".join(r.getMessage() for r in caplog.records)
    assert "waited" in said and "slow-one" in said and "slow_holder" in said
    caplog.clear()
    with caplog.at_level("WARNING", logger="agos_core.db.connection"):
        db.execute("SELECT 1").fetchone()  # nobody holds it: nothing said
    assert caplog.records == []


def test_open_dm_brings_a_hidden_dm_back_outside_the_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agos_core.actions import chat_store, workers
    from agos_core.db import chats as repo
    from agos_core.db import hermes_switches

    db = open_database(":memory:")
    core = SimpleNamespace(db=db, engine=None)
    row = {"id": 5, "workspace_id": "ws", "kind": "dm", "deleted_at": None}
    seen: list[bool] = []
    monkeypatch.setattr(workers, "require_workspace", lambda _core, _ws: None)
    monkeypatch.setattr(repo, "dm_row", lambda _db, _ws, _agent: row)
    monkeypatch.setattr(hermes_switches, "hidden", lambda *_a: 1)
    monkeypatch.setattr(chat_store, "unhide", lambda c, _row: seen.append(c.db.in_transaction))
    assert workers.open_dm(core, "ws", None) == 5  # type: ignore[arg-type]
    assert seen == [False]


# ---- F7: the channels send round runs when rung, not every 0.5 s ----------------------


def test_the_send_round_waits_for_its_doorbell(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from agos_core.actions import channels
    from agos_core.engine import doorbell

    rounds: list[float] = []

    def send_round(_core: Any) -> int:
        rounds.append(1.0)
        return 0

    monkeypatch.setattr(channels, "send_round", send_round)
    monkeypatch.setattr(doorbell, "FALLBACK_S", 30.0)

    async def run() -> None:
        task = asyncio.create_task(channels.run_forever(None))  # type: ignore[arg-type]
        await asyncio.sleep(0.8)
        assert len(rounds) == 1  # one round at start, then it waits (was: every 0.5 s)
        await asyncio.to_thread(doorbell.ring, doorbell.SEND)  # rung from a thread
        await asyncio.sleep(0.2)
        assert len(rounds) == 2
        task.cancel()

    asyncio.run(run())


def test_turns_that_never_ended_are_looked_for_once_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agos_core.actions import channels, hermes_channel

    looked: list[int] = []

    def close_stale(_core: Any) -> int:
        looked.append(1)
        return 0

    monkeypatch.setattr(channels, "queue_replies", lambda _core: 0)
    monkeypatch.setattr(channels, "close_answered", lambda _core: 0)
    monkeypatch.setattr(hermes_channel, "close_stale", close_stale)
    monkeypatch.setattr(channels, "_stale_at", 0.0)
    real: Any = getattr(channels.send_round, "real", channels.send_round)
    real(None)
    real(None)
    assert looked == [1]


def test_an_agent_line_or_a_turn_end_rings_the_send_round(tmp_path: Path) -> None:
    from agos_core.actions.services.chat import chat_writes
    from agos_core.db import chats as repo
    from agos_core.engine import doorbell

    rung: list[str] = []
    real_ring = doorbell.ring

    def ring(queue: str, workspace_id: str | None = None) -> None:
        # The send round's own queue only: the same writers also ring the open
        # chat's /live wait (doorbell.LIVE, F10, test_chat_live_waits.py).
        if queue == doorbell.SEND:
            rung.append(queue)
        real_ring(queue, workspace_id)

    db = open_database(":memory:")
    db.execute("INSERT INTO workspaces (id, created_at, updated_at) VALUES ('ws', '', '')")
    chat = repo.insert_chat(db, workspace_id="ws", title="", channel="web", kind="group")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(doorbell, "ring", ring)
        # The Chat service's writes ring (a repository rings no engine doorbell).
        chat_writes.add_chat_message(db, "ws", chat, "owner", "hi")
        assert rung == []
        chat_writes.add_chat_message(db, "ws", chat, "agent", "hello")
        assert rung == [doorbell.SEND]
        turn = chat_writes.insert_turn(db, chat_id=chat, workspace_id="ws", asked_up_to=0)
        chat_writes.set_turn(db, turn, status="completed")
        assert rung == [doorbell.SEND, doorbell.SEND]


# ---- F13: a write Hermes refused is retried with a growing pause ----------------------


def test_a_refused_hermes_write_is_retried_with_a_growing_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    from agos_core.actions.services.automation import sync_loop as automations

    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(automations, "_retries", {})
    asked = ("refused", ("0 9 * * *", True))
    assert automations._retry_due("ws", 1, asked) is True  # at once the first time
    clock[0] += 20
    assert automations._retry_due("ws", 1, asked) is False  # not every 20 s pass
    clock[0] += 41
    assert automations._retry_due("ws", 1, asked) is True  # after 1 min
    clock[0] += 61
    assert automations._retry_due("ws", 1, asked) is False  # then 2 min
    clock[0] += 60
    assert automations._retry_due("ws", 1, asked) is True
    # The owner changed it: tried at once.
    assert automations._retry_due("ws", 1, ("refused", ("0 10 * * *", True))) is True
    for _ in range(12):
        clock[0] += automations.RETRY_MAX_S
        automations._retry_due("ws", 1, asked)
    assert automations._retries[("ws", 1)][2] == automations.RETRY_MAX_S
