"""Workspace chats on Hermes: streamed answers, queue, Stop, approvals, proposals.

The rig (fake Hermes, `env`) is tests/chat_rig.py; access and attachments are in
test_chat_access_files.py, his messages (replies, edits, order) in
test_chat_messages.py, the Co-Founder's tools in test_chat_tools.py.
"""

from typing import Any

from chat_rig import (
    MODEL,
    Env,
    get,
    new_chat,
    say,
    settle,
)
from chat_rig import env as env
from fake_gateway import ask_me_first

from agos_core.db import chats as chats_repo
from agos_core.engine.chat import LiveTurn
from agos_core.engine.hermes import EngineError

# ---- pure rules ------------------------------------------------------------------


def test_live_turn_folds_events() -> None:
    turn = LiveTurn(turn_id=7)
    turn.apply({"event": "message.delta", "delta": "Hel"})
    turn.apply({"event": "reasoning.available", "text": "think"})
    turn.apply({"event": "tool.started", "tool": "terminal", "preview": "ls"})
    turn.apply({"event": "tool.completed", "tool": "terminal", "duration": 0.42, "preview": "a b"})
    turn.apply({"event": "message.delta", "delta": "lo"})
    assert turn.text == "Hello"
    kinds = [(a.kind, a.title, a.status) for a in turn.activity]
    assert kinds == [("thinking", "Thought", "done"), ("tool", "Ran a command", "done")]
    assert turn.activity[1].detail == "ls\n→ a b" and turn.activity[1].duration == 0.42
    ended = turn.apply({"event": "run.completed", "output": "Hello!", "usage": {"total_tokens": 9}})
    assert ended and turn.final_text() == "Hello!"
    assert not hasattr(turn, "usage")  # an answer's tokens are Hermes's own count
    assert turn.snapshot()["version"] == turn.version > 0


def test_approval_offers_only_once_or_deny() -> None:
    turn = LiveTurn(turn_id=1)
    turn.apply({"event": "approval.request", "command": "rm -rf build", "description": "delete"})
    item = turn.activity[0]
    assert (item.status, item.choices, turn.status) == ("waiting", ["once", "deny"], "waiting")
    turn.apply({"event": "approval.responded", "choice": "deny"})
    assert (item.status, item.choices, turn.status) == ("failed", [], "running")


def test_unfinished_items_close_with_the_turn() -> None:
    turn = LiveTurn(turn_id=1)
    turn.apply({"event": "tool.started", "tool": "terminal", "preview": "sleep 99"})
    turn.apply({"event": "run.cancelled"})
    assert turn.activity[0].status == "failed" and turn.status == "cancelled"


def test_an_answer_is_a_hermes_run_in_the_chats_session(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "What is 2+2?")

    import hermes_store

    def answered() -> bool:
        if fake.bodies and not fake.events["run_1"]:
            # Hermes keeps the step in its session as it runs it.
            hermes_store.tool(
                core.engine.profile_home(ws),
                str(chat),
                "terminal",
                '{"command": "echo $((2+2))"}',
                "4",
            )
            fake.push(
                "run_1",
                {"event": "tool.started", "tool": "terminal", "preview": "echo $((2+2))"},
                {"event": "tool.completed", "tool": "terminal", "duration": 0.1, "preview": "4"},
                {"event": "message.delta", "delta": "4"},
                {
                    "event": "run.completed",
                    "output": "It's **4**.",
                    "usage": {"total_tokens": 42},
                    "runtime": {"provider": "anthropic", "model": "claude-sonnet-5"},
                },
            )
        return get(client, ws, chat)["turns"] != [] and not get(client, ws, chat)["working"]

    settle(core, answered)
    body = fake.bodies[0]
    assert body["session_id"] == chats_repo.hermes_key(core.db, chat)
    assert body["input"] == "What is 2+2?"
    # The chat follows the workspace's model: Hermes runs its profile's own (no
    # /model of its own for this conversation).
    assert getattr(fake, "models", {}) == {}
    assert "Research" in body["instructions"] and "/workspace" in body["instructions"]
    data = get(client, ws, chat)
    assert [(m["from"], m["body"]) for m in data["messages"]] == [
        ("owner", "What is 2+2?"),
        ("agent", "It's **4**."),
    ]
    turn = data["turns"][0]
    assert turn["status"] == "completed"
    assert turn["replyId"] == data["messages"][1]["id"]
    assert [a["title"] for a in turn["activity"]] == ["Ran a command"]
    listed = client.get(f"/workspaces/{ws}/chats").json()[0]
    assert listed["preview"] == "It's **4**." and listed["working"] is False


def test_stop_ends_the_answer_and_retry_asks_again(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "long job")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "message.delta", "delta": "Working"})
    assert client.post(f"/workspaces/{ws}/chats/{chat}/stop").json() == {"stopped": True}
    settle(core, lambda: not get(client, ws, chat)["working"])
    assert fake.stopped == ["run_1"]
    turn = get(client, ws, chat)["turns"][0]
    assert turn["status"] == "stopped"
    assert client.post(f"/workspaces/{ws}/chats/{chat}/retry").status_code == 202
    settle(core, lambda: len(fake.bodies) == 2)
    assert fake.bodies[1]["input"] == "long job"  # Hermes's own /retry asked it again


def test_approval_answers_go_to_hermes_and_never_widen(env: Env) -> None:
    client, fake, core, ws = env
    ask_me_first(core, ws)  # tests Ask me
    chat = new_chat(client, ws)
    say(client, ws, chat, "clean the build")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "approval.request", "command": "rm -rf build"})

    def waiting() -> bool:
        view = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["live"]
        return bool(view) and view["status"] == "waiting"

    settle(core, waiting)
    live = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["live"]
    assert live["status"] == "waiting" and live["activity"][0]["choices"] == ["once", "deny"]
    refused = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "always"})
    assert refused.status_code == 422
    ok = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "once"})
    assert ok.status_code == 204
    assert fake.approvals == [("run_1", "once")]
    fake.push("run_1", {"event": "run.completed", "output": "Done."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    activity = get(client, ws, chat)["turns"][0]["activity"]
    assert activity[0]["title"] == "Allowed once"


def test_a_gateway_that_is_down_loses_nothing(env: Env) -> None:
    """The workspace's gateway can't start: his message waits in Hermes's inbox and
    is answered once the gateway is up (nothing to send again)."""
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    fake.gateway = False  # the gateway is down
    core.engine.is_running = lambda workspace_id: False

    def down(workspace_id: str, **_: Any) -> None:
        raise EngineError("the engine refused to start the work: no credits")

    core.engine.start = down
    say(client, ws, chat, "hello")
    settle(core, lambda: get(client, ws, chat)["working"])
    assert fake.bodies == []
    fake.gateway = True  # up again: it takes what waited
    settle(core, lambda: bool(fake.bodies))
    assert fake.bodies[0]["input"] == "hello"


def test_rename_model_search_and_delete(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    other = MODEL | {"model": "claude-opus-5-5", "effort": "max"}
    r = client.put(f"/workspaces/{ws}/chats/{chat}", json={"title": "Ads", "model": other})
    assert r.status_code == 204
    assert client.put(f"/workspaces/{ws}/chats/{chat}", json={"title": " "}).status_code == 400
    say(client, ws, chat, "Summer campaign budget")
    settle(core, lambda: bool(fake.bodies))
    assert fake.bodies[0]["model"] == "claude-opus-5-5"
    assert fake.bodies[0]["model_options"] == {"reasoning_effort": "max"}
    assert "Ads" in fake.bodies[0]["instructions"]
    hits = client.get(f"/workspaces/{ws}/chats/search", params={"q": "summer BUDGET"}).json()
    assert [(h["chatTitle"], h["from"]) for h in hits] == [("Ads", "owner")]
    assert client.delete(f"/workspaces/{ws}/chats/{chat}").status_code == 204
    # Stopped and hidden, but Hermes keeps the session (the project's memory): hidden
    # is Hermes's own archive of it (set_session_archived); AGOS keeps no mark.
    assert fake.stopped == ["run_1"] and fake.deleted == []
    assert client.get(f"/workspaces/{ws}/chats/{chat}").status_code == 404
    import sqlite3 as _sql

    with _sql.connect(core.engine.profile_home(ws) / "state.db") as state:
        flags = state.execute(
            "SELECT archived FROM sessions WHERE source = 'agos' AND chat_id = ?", (str(chat),)
        ).fetchall()
    assert flags and all(f[0] == 1 for f in flags)
    row = core.db.execute("SELECT deleted_at FROM chats WHERE id = ?", (chat,)).fetchone()
    assert row["deleted_at"] is None
    assert client.get(f"/workspaces/{ws}/chats/search", params={"q": "summer"}).json() == []
    import hermes_store

    assert (
        hermes_store.last_user(core.engine.profile_home(ws), str(chat)) == "Summer campaign budget"
    )
    assert client.get(f"/workspaces/{ws}/chats/{chat}").status_code == 404


def test_a_chat_agos_hid_before_moves_into_hermess_archive(env: Env) -> None:
    """Live data: AGOS's own deleted_at on a chat Hermes has sessions of goes into
    Hermes's per-session archive once (chat_store.move_hidden); the chat stays hidden."""
    import sqlite3 as _sql

    from agos_core.actions import chat_store

    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "Old one")
    settle(core, lambda: bool(fake.bodies))
    core.db.execute("UPDATE chats SET deleted_at = '2026-01-01T00:00:00Z' WHERE id = ?", (chat,))
    assert chat_store.move_hidden(core) == 1
    row = core.db.execute("SELECT deleted_at FROM chats WHERE id = ?", (chat,)).fetchone()
    assert row["deleted_at"] is None
    with _sql.connect(core.engine.profile_home(ws) / "state.db") as state:
        flags = state.execute(
            "SELECT archived FROM sessions WHERE source = 'agos' AND chat_id = ?", (str(chat),)
        ).fetchall()
    assert flags and all(f[0] == 1 for f in flags)
    assert client.get(f"/workspaces/{ws}/chats/{chat}").status_code == 404
    assert chat_store.move_hidden(core) == 0


def test_chats_are_kept_per_workspace(env: Env) -> None:
    client, _fake, _core, ws = env
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    chat = new_chat(client, ws)
    for path in ("", "/live", "/stop"):
        method = client.post if path == "/stop" else client.get
        assert method(f"/workspaces/{other}/chats/{chat}{path}").status_code == 404
    assert (
        client.post(f"/workspaces/{other}/chats/{chat}/messages", json={"body": "x"}).status_code
        == 404
    )
    assert client.get(f"/workspaces/{other}/chats/search", params={"q": "x"}).json() == []
