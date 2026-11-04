"""Opening a chat reads Hermes's routing index of its workspace (engine.hermes_lanes:
the conversation's own /yolo, its Full access) from Hermes once, then again only
when what Hermes reads for it changed (the homes' gateway routing rows, their
sessions.json). Each workspace keeps its own answer, and the read-ahead asks it
after a start, so the first chat opened after a restart doesn't wait for Hermes."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from channels_rig import connect, env, fake_telegram  # noqa: F401 - fixtures

from agos_core.engine.hermes import EngineError, HermesEngine

# The real one (conftest puts a stand-in that reads the files itself in each test).
HERMES_LANES = HermesEngine.hermes_lanes


def _lanes_from_hermes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Hermes's runtime as far as the lanes script goes (no conversation on /yolo)."""
    asked: list[Path] = []

    def runtime(self: Any, home: Path, script: str, tag: str, **_kw: Any) -> str:
        if tag != "AGOS-LANES":
            raise EngineError("not in this test")
        asked.append(home)
        return json.dumps({})

    monkeypatch.setattr(HermesEngine, "hermes_lanes", HERMES_LANES)
    monkeypatch.setattr(HermesEngine, "_in_runtime", runtime)
    return asked


def _chat_on_telegram(client: Any, ws: str) -> int:
    """The workspace's first chat, with its own topic on the workspace's bot."""
    cid = connect(client)
    chat = int(client.get(f"/workspaces/{ws}/chats").json()[0]["id"])
    r = client.post(
        f"/workspaces/{ws}/chats/{chat}/addresses",
        json={"connectionId": cid, "createTopicIn": "-100"},
    )
    assert r.status_code == 201, r.text
    return chat


def _route(home: Path, key: str, entry: dict[str, Any]) -> None:
    """What Hermes's gateway writes when a conversation's routing changes
    (hermes_state_common.py gateway_routing)."""
    with contextlib.closing(sqlite3.connect(home / "state.db")) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS gateway_routing (scope TEXT NOT NULL DEFAULT '',"
            " session_key TEXT NOT NULL, entry_json TEXT NOT NULL, updated_at REAL NOT NULL,"
            " PRIMARY KEY (scope, session_key))"
        )
        db.execute(
            "INSERT OR REPLACE INTO gateway_routing VALUES (?, ?, ?, 0)",
            (str((home / "sessions").resolve()), key, json.dumps(entry)),
        )
        db.commit()


def test_a_chat_asks_hermess_routing_index_again_only_when_it_changed(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tg, ws = env
    chat = _chat_on_telegram(client, ws)
    asked = _lanes_from_hermes(monkeypatch)
    url = f"/workspaces/{ws}/chats/{chat}"
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    assert len(asked) == 1
    # Another workspace's index doesn't push this one's out.
    other = core.engine.profile_home(ws).parent / "agos-other"
    other.mkdir()
    core.engine.hermes_lanes(other, [other])
    assert len(asked) == 2
    client.get(url)
    assert len(asked) == 2
    # Hermes's sessions move on (state.db written) but no routing changed: nothing to ask.
    root = core.engine.profile_home(ws)
    _route(root, "agent:main:telegram:group:-100:41", {"session_key": "a", "yolo": False})
    client.get(url)
    assert len(asked) == 3
    with contextlib.closing(sqlite3.connect(root / "state.db")) as db:
        db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, body TEXT)")
        db.execute("INSERT INTO messages (body) VALUES ('hello')")
        db.commit()
    client.get(url)
    assert len(asked) == 3
    # Its conversation went on /yolo in Hermes: asked at once.
    _route(root, "agent:main:telegram:group:-100:41", {"session_key": "a", "yolo": True})
    client.get(url)
    assert len(asked) == 4


def test_the_read_ahead_asks_each_workspaces_routing_index_before_the_first_chat(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tg, ws = env
    chat = _chat_on_telegram(client, ws)
    asked = _lanes_from_hermes(monkeypatch)
    from agos_core.engine import read_ahead

    assert "agos_core.actions.access:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.access:read_ahead",))
    assert len(asked) == 1
    assert client.get(f"/workspaces/{ws}/chats/{chat}").status_code == 200
    assert len(asked) == 1
