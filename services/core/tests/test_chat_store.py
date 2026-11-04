"""Hermes keeps the chats' sessions: each session holding a chat's words is pinned
(actions/chat_store.py, Hermes's `hermes sessions pin`)."""

import contextlib
import sqlite3
from pathlib import Path

import hermes_store
from chat_rig import Env, new_chat, settle
from chat_rig import env as env

from agos_core.actions import chat_store

PINS: list[list[str]] = []


def _pin(home: Path, session_ids: list[str]) -> None:
    """`hermes sessions pin <ids>` (hermes_cli/sessions_cmd.py _cmd_pin)."""
    PINS.append(list(session_ids))
    with contextlib.closing(sqlite3.connect(home / "state.db", isolation_level=None)) as db:
        for sid in session_ids:
            db.execute("UPDATE sessions SET pinned = 1 WHERE id = ?", (sid,))


def test_a_chats_sessions_are_pinned_once(env: Env) -> None:
    client, fake, core, ws = env
    core.engine.pin_sessions = _pin
    chat = new_chat(client, ws)
    home = core.engine.profile_home(ws)
    hermes_store.say(home, str(chat), "user", "what about cats?")
    hermes_store.say(home, str(chat), "assistant", "Cats are great.")
    assert chat_store.keep(core, ws) == 1  # the chat's live session
    assert chat_store.keep(core, ws) == 0
    assert chat_store.tick(core)[ws] == {"pinned": 0}
    settle(core, lambda: True)
    del fake


def test_a_chats_name_leaves_agos_once_its_hermes_session_has_one(env: Env) -> None:
    """C3 (925047d area 2): a plain chat's name AGOS held before its session existed
    goes as soon as Hermes's session holds a title (at Hermes's turn end and at
    start), so no copy stays hidden behind Hermes's."""
    client, fake, core, ws = env
    core.engine.pin_sessions = _pin
    chat = new_chat(client, ws)
    core.db.execute("UPDATE chats SET title = 'zz-media-check' WHERE id = ?", (chat,))
    home = core.engine.profile_home(ws)
    hermes_store.say(home, str(chat), "user", "hello")
    chat_store.keep(core, ws, chat)  # no Hermes title yet: AGOS keeps the name
    assert core.db.execute("SELECT title FROM chats WHERE id = ?", (chat,)).fetchone()[0]
    assert hermes_store.title(home, str(chat), "zz-media-check")
    chat_store.tick(core)
    assert core.db.execute("SELECT title FROM chats WHERE id = ?", (chat,)).fetchone()[0] == ""
    shown = client.get(f"/workspaces/{ws}/chats/{chat}").json()["title"]
    assert shown == "zz-media-check"  # Hermes's
    settle(core, lambda: True)
    del fake


def test_the_old_copies_moves_are_gone() -> None:
    """Guard: the old message copies were moved into Hermes (and the names and
    models given) on the live install; those moves are gone and nothing writes
    a chat's history into Hermes's session store any more."""
    from agos_core.engine.hermes import HermesEngine

    for name in ("move", "names_and_models", "TOLD"):
        assert not hasattr(chat_store, name), name
    assert not hasattr(HermesEngine, "run_session_job")


def test_hermess_session_end_pins_that_chat_no_loop(env: Env, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Hermes's on_session_end (the plugin's /turn-end) pins that chat's sessions;
    one chat only; no AGOS loop re-reads every chat's sessions."""
    import inspect
    import threading

    from agos_core.actions import automations, hermes_channel
    from agos_core.db import chats as repo

    client, _fake, core, ws = env
    core.engine.pin_sessions = _pin
    chat = new_chat(client, ws)
    other = new_chat(client, ws)
    home = core.engine.profile_home(ws)
    hermes_store.say(home, str(chat), "user", "what about dogs?")
    hermes_store.say(home, str(other), "user", "and birds?")
    with core.db:
        turn = repo.insert_turn(core.db, workspace_id=ws, chat_id=chat, asked_up_to=0)
    PINS.clear()
    done = threading.Event()
    real = chat_store.keep

    def keep(*a, **k):  # type: ignore[no-untyped-def]
        try:
            return real(*a, **k)
        finally:
            done.set()

    monkeypatch.setattr(chat_store, "keep", keep)
    hermes_channel.turn_ended(core, ws, turn, "completed")
    assert done.wait(10)
    assert len(PINS) == 1 and len(PINS[0]) == 1  # that chat's session only
    assert "chat_store" not in inspect.getsource(automations.run_forever)


def test_one_bad_chat_never_keeps_the_others_unpinned(env: Env) -> None:
    """A card chat whose member is a long old profile name raised in where_of and
    left every chat of the workspace unpinned: it is skipped, the others are kept."""
    client, fake, core, ws = env
    core.engine.pin_sessions = _pin
    chat = new_chat(client, ws)
    home = core.engine.profile_home(ws)
    hermes_store.say(home, str(chat), "user", "what about cats?")
    bad = new_chat(client, ws)
    core.db.execute(
        "UPDATE chats SET agent = ? WHERE id = ?",
        ("agos-" + ws + "--a-" + "m" * 60, bad),
    )
    assert chat_store.keep(core, ws) == 1
    settle(core, lambda: True)
    del fake


def test_a_card_on_a_members_old_profile_name_is_that_members() -> None:
    from agos_core.actions.kanban_board import _legacy_member

    members = {"a-ideas": {"name": "ideas", "title": "Ideas"}}
    assert _legacy_member("agos-marketing--a-ideas", members) == members["a-ideas"]
    assert _legacy_member("marketing--a-ideas", members) == members["a-ideas"]
    assert _legacy_member("agos-marketing--a-gone", members) is None
    assert _legacy_member("someone", members) is None


def test_card_chats_on_an_old_profile_name_get_the_members_name() -> None:
    from agos_core.db.migrations import MIGRATIONS

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY, agent TEXT)")
    db.executemany(
        "INSERT INTO chats (agent) VALUES (?)",
        [("agos-marketing--a-ideas-generator",), ("researcher",), (None,)],
    )
    fix = next(m for m in MIGRATIONS if "WHERE agent LIKE '%--a-%'" in m)
    db.executescript(fix)
    db.executescript(fix)  # replayable
    assert [r[0] for r in db.execute("SELECT agent FROM chats ORDER BY id")] == [
        "ideas-generator",
        "researcher",
        None,
    ]
