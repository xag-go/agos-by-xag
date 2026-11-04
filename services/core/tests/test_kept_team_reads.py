"""Step 41: the Team, the Office and the Dashboard read each member's profile.yaml
and each chat's Hermes conversation for every list they show. Both are kept in
memory while Hermes's own files are unchanged (engine/read_cache.py stamps), so a
page opened again reads neither; a change Hermes makes shows on the next call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chat_rig
import hermes_store
import pytest
from chat_rig import Env
from conftest import hermes_write_profile_meta
from test_workers import agent

from agos_core.engine import profile_meta

env = chat_rig.env  # the chat tests' fixture (fake Hermes)


def _count_profile_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every read of a profile.yaml (each one is a YAML parse)."""
    reads: list[str] = []
    real = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self.name == profile_meta.PROFILE_YAML:
            reads.append(str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    return reads


def test_profile_yaml_is_parsed_once_while_hermes_leaves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "writer"
    home.mkdir()
    (home / "profile.yaml").write_text("display_name: Writer\nui_meta:\n  agos:\n    tags: [a]\n")
    reads = _count_profile_reads(monkeypatch)
    first = profile_meta.read(home)
    assert first == {"display_name": "Writer", "ui_meta": {"agos": {"tags": ["a"]}}}
    assert profile_meta.read(home) == first
    assert len(reads) == 1
    # A caller changing what it got never changes what the next caller gets.
    first["ui_meta"]["agos"]["tags"].append("b")
    first["display_name"] = "changed"
    assert profile_meta.read(home) == {
        "display_name": "Writer",
        "ui_meta": {"agos": {"tags": ["a"]}},
    }
    assert len(reads) == 1
    # Hermes renames it (its write_profile_meta, same length): read again at once.
    hermes_write_profile_meta(home, "Editor")
    reads.clear()
    assert profile_meta.display_name(profile_meta.read(home)) == "Editor"
    assert len(reads) == 1
    (home / "profile.yaml").unlink()
    assert profile_meta.read(home) == {}
    (home / "profile.yaml").write_text("display_name: Back\n")
    assert profile_meta.display_name(profile_meta.read(home)) == "Back"


def _team(client: Any, ws: str) -> dict[str, Any]:
    found: dict[str, Any] = client.get(f"/workspaces/{ws}/workers").json()
    return found


def _with_members(env: Env) -> int:
    """Two members with their DMs open, and the Co-Founder's chat with an answer in its
    Hermes session (the root's state.db). Returns the Co-Founder's chat id."""
    client, _fake, core, ws = env
    agent(client, ws, "designer", "Designer")
    agent(client, ws, "writer", "Writer")
    for name in ("designer", "writer"):
        r = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": name})
        assert r.status_code in (200, 201), r.text
    cofounder = int(next(c["id"] for c in _team(client, ws)["dms"] if not c["agent"]))
    root = core.engine.profile_home(ws)
    hermes_store.say(root, str(cofounder), "user", "Hello")
    hermes_store.say(root, str(cofounder), "assistant", "First words")
    return cofounder


def test_the_team_page_parses_no_profile_yaml_when_hermes_changed_none(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.actions import team

    client, _fake, core, ws = env
    _with_members(env)
    reads = _count_profile_reads(monkeypatch)
    first = _team(client, ws)
    assert _team(client, ws) == first
    assert reads == []  # every profile.yaml kept: Hermes changed none
    # Hermes renames a member (its write_profile_meta): its DM's name follows at once.
    where = team.home(core, ws, "designer")
    assert where is not None
    core.engine.set_display_name(where, "Brand designer")
    reads.clear()
    renamed = _team(client, ws)
    assert "Brand designer" in [c["title"] for c in renamed["dms"]]
    assert reads == [str(where / "profile.yaml")]  # only the changed file, once


def test_the_lists_read_no_state_db_when_hermes_wrote_nothing(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Team's DMs (and every list of chats) show each chat's last words from its
    Hermes session: kept while each of its profiles' state.db is unchanged."""
    from agos_core.db import hermes_chats as hc

    client, _fake, core, ws = env
    cofounder = _with_members(env)
    chat = int(client.post(f"/workspaces/{ws}/chats", json={"title": "Research"}).json()["id"])
    root = core.engine.profile_home(ws)
    hermes_store.say(root, str(chat), "user", "Look it up")
    hermes_store.say(root, str(chat), "assistant", "Found it")
    hermes_store.title(root, str(chat), "Hermes's own title")
    store = hc.store()
    assert store is not None
    queries: list[str] = []
    real_query = store.query

    def query(profile: str, sql: str, args: Any = ()) -> list[Any]:
        queries.append(profile)
        return real_query(profile, sql, args)

    monkeypatch.setattr(store, "query", query)
    first = _team(client, ws)
    assert next(c for c in first["dms"] if not c["agent"])["preview"] == "First words"
    chats = client.get(f"/workspaces/{ws}/chats").json()
    assert [(c["title"], c["preview"]) for c in chats if c["id"] == chat] == [
        ("Hermes's own title", "Found it")
    ]
    queries.clear()
    assert _team(client, ws) == first
    assert client.get(f"/workspaces/{ws}/chats").json() == chats
    assert queries == []  # every conversation kept: Hermes wrote nothing
    # Hermes answers in the Co-Founder's chat: the lists show it on the next call.
    hermes_store.say(root, str(cofounder), "assistant", "Newer words")
    after = _team(client, ws)
    assert next(c for c in after["dms"] if not c["agent"])["preview"] == "Newer words"
    assert queries  # read again from Hermes
    # An open chat reads its whole conversation (steps included) as before.
    hermes_store.tool(root, str(chat), "web_search", '{"q": "x"}', "a result")
    hermes_store.say(root, str(chat), "assistant", "Done looking")
    opened = chat_rig.get(client, ws, chat)
    assert opened["messages"][-1]["body"] == "Done looking"
    assert opened["turns"]  # its steps come from the full transcript


def test_a_list_keeps_no_answer_read_while_hermes_store_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that met an error of Hermes's store (busy, changed under it) is used
    once and never kept: the next call reads Hermes again."""
    import sqlite3

    from agos_core.db import hermes_chats as hc
    from agos_core.hermes_gateway import chat_sessions

    home = tmp_path / "agos-alpha"
    hermes_store.say(home, "7", "user", "Hi")
    hermes_store.say(home, "7", "assistant", "Hello")
    store = chat_sessions.Store(
        lambda p: home if p == "agos-alpha" else None,
        lambda ws: "agos-alpha",
        lambda ws: ["agos-alpha"],
    )
    where = hc.Where(workspace_id="alpha", chat_id=7, profiles=("agos-alpha",), own="agos-alpha")
    broken = {"on": True}
    real_open = store._open

    def flaky(profile: str) -> Any:
        found = real_open(profile)
        if broken["on"] and found is not None:

            class Busy:
                def execute(self, *_a: Any) -> Any:
                    raise sqlite3.OperationalError("database is locked")

            return (Busy(), found[1])
        return found

    monkeypatch.setattr(store, "_open", flaky)
    assert store.summary(where).rows == []  # the failed read: nothing shown this once
    broken["on"] = False
    assert [r.content for r in store.summary(where).rows] == ["Hi", "Hello"]  # read again
