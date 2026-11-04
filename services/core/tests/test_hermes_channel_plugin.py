"""The agos-guard plugin's turn handling on the Hermes gateway: the eyes reaction,
who gets in, approvals, the outbox send, how a turn ended or stopped, chat names,
display settings and the gateway lamp."""

import asyncio
import json
import time
from typing import Any

import hermes_store
from channels_rig import OWNER
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram
from hermes_channel_rig import (
    _bridge,
    _hermes_bot,
)
from split_parts import whole_text
from split_sources import split_source

from agos_core.actions import channels, hermes_channel
from agos_core.actions import chat as chat_actions
from agos_core.actions.services.channel import gateway_messages
from agos_core.db import chats as chats_repo
from agos_core.db import hermes_chats as hc


def test_hermes_keeps_its_eyes_until_agoss_answer_is_out(env: Any, monkeypatch: Any) -> None:
    """His message in a topic AGOS answers itself (a group's room): Hermes's 👀
    stays on it while the answer works, and Hermes's own 👍 / 👎 comes once that
    answer is in Telegram. A member's topic is Hermes's own: no 👀 kept there."""

    client, core, _fake, _tg, ws = env
    cid, key = _hermes_bot(client, core, ws)
    monkeypatch.setattr(gateway_messages, "REACTION_SETTLE_S", 0)
    kicked: list[int] = []
    monkeypatch.setattr(chat_actions, "_kick", lambda _c, _w, chat: kicked.append(chat))
    me = {"sender": str(OWNER)}
    room = client.post(f"/workspaces/{ws}/chats", json={"title": "Launch"}).json()["id"]
    core.db.execute("UPDATE chats SET kind = 'group', members = '[]' WHERE id = ?", (room,))
    topic = "-1000009:41"
    core.db.execute(
        """INSERT INTO chat_addresses (chat_id, connection_id, address, notify, created_at)
           VALUES (?, ?, ?, 0, 'now')""",
        (room, cid, topic),
    )
    said = _bridge(
        client, ws, key, "incoming", me | {"chat": topic, "text": "write it", "messageId": "501"}
    ).json()
    assert said == {"handled": True, "keepEyes": True}
    assert hermes_channel.reactions_ready(core, ws) == []  # working: 👀 stays

    def answered(text: str, status: str = "completed") -> None:
        last = core.db.execute(
            "SELECT max(id) FROM messages WHERE chat_id = ? AND author = 'owner'", (room,)
        ).fetchone()[0]
        turn = chats_repo.insert_turn(core.db, chat_id=room, workspace_id=ws, asked_up_to=last)
        reply = chats_repo.add_chat_message(core.db, ws, room, "agent", text, speaker="writer")
        core.db.execute(
            """UPDATE chat_turns SET status = ?, reply_id = ?,
                 ended_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-5 seconds') WHERE id = ?""",
            (status, reply if status == "completed" else None, turn),
        )

    answered("Here it is")
    channels.queue_replies(core)
    time.sleep(0.01)
    assert hermes_channel.reactions_ready(core, ws) == []  # its answer isn't in Telegram yet
    sent = core.db.execute(
        "SELECT id FROM channel_outbox WHERE source LIKE 'msg:%' AND sent_id IS NULL"
    ).fetchone()
    channels.hermes_outbox_done(core, ws, int(sent["id"]), "send", "900", None)
    out = _bridge(client, ws, key, "outbox", {}).json()
    assert [(r["chat"], r["messageId"], r["outcome"]) for r in out["reactions"]] == [
        ("-1000009", "501", "success")
    ]
    done = {"id": int(out["reactions"][0]["id"]), "kind": "reaction"}
    assert _bridge(client, ws, key, "outbox-done", done).status_code == 200
    assert hermes_channel.reactions_ready(core, ws) == []  # once
    assert not hermes_channel.keeps_eyes(core, ws, topic, "501")

    # An answer that fails: Hermes's 👎.
    _bridge(client, ws, key, "incoming", me | {"chat": topic, "text": "again", "messageId": "502"})
    answered("", "failed")
    time.sleep(0.01)
    ready = hermes_channel.reactions_ready(core, ws)
    assert [(r["messageId"], r["outcome"]) for r in ready] == [("502", "failure")]

    # The Co-Founder's own chat with the bot: Hermes answers it itself (its own 👀 / 👍).
    mine = _bridge(
        client, ws, key, "incoming", me | {"chat": str(OWNER), "text": "hey", "messageId": "7"}
    ).json()
    assert mine == {"handled": False}


def test_the_plugin_leaves_hermess_eyes_until_agos_says(monkeypatch: Any) -> None:
    """The plugin skips Hermes's end-of-turn reaction on a message AGOS answers, then
    makes Hermes's own reaction call when AGOS says that answer is out."""
    import asyncio as _asyncio
    import sys
    import threading
    import types
    from enum import Enum

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    class ProcessingOutcome(Enum):
        SUCCESS = "success"
        FAILURE = "failure"
        CANCELLED = "cancelled"

    base = types.ModuleType("gateway.platforms.base")
    base.ProcessingOutcome = ProcessingOutcome  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway.platforms.base", base)
    calls: list[tuple[str, str, Any]] = []

    class Adapter:
        async def on_processing_complete(self, event: Any, outcome: Any) -> None:
            calls.append((str(event.source.chat_id), str(event.message_id), outcome))

    adapter = Adapter()
    monkeypatch.setattr(plugin, "_keep_eyes", set())
    monkeypatch.setitem(plugin._ctx, "complete", None)
    plugin._watch_reactions(adapter)
    plugin._watch_reactions(adapter)  # wired once
    loop = _asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    monkeypatch.setitem(plugin._ctx, "loop", loop)

    def ev(chat: str, mid: str) -> Any:
        return types.SimpleNamespace(source=types.SimpleNamespace(chat_id=chat), message_id=mid)

    plugin._eyes_stay("-1009", "5", {"handled": True, "keepEyes": True})
    plugin._eyes_stay("-1009", "6", {"handled": True})

    def run(coro: Any) -> Any:
        return _asyncio.run_coroutine_threadsafe(coro, loop).result(5)

    run(adapter.on_processing_complete(ev("-1009", "5"), ProcessingOutcome.SUCCESS))
    run(adapter.on_processing_complete(ev("-1009", "6"), ProcessingOutcome.SUCCESS))
    assert calls == [("-1009", "6", ProcessingOutcome.SUCCESS)]  # 5 keeps its 👀
    # 👍 / 👎 are Hermes's own platform actions (ctx.platform_actions).
    reacted: list[tuple[str, str, str, str]] = []

    class Actions:
        async def add_reaction(self, platform: str, chat: str, mid: str, emoji: str) -> Any:
            reacted.append((platform, chat, mid, emoji))
            return {"ok": True}

    monkeypatch.setitem(plugin._ctx, "ctx", types.SimpleNamespace(platform_actions=Actions()))
    assert plugin._react({"chat": "-1009", "messageId": "5", "outcome": "success"}) is None
    assert plugin._react({"chat": "-1009", "messageId": "9", "outcome": "failure"}) is None
    assert reacted == [
        ("telegram", "-1009", "5", "\U0001f44d"),
        ("telegram", "-1009", "9", "\U0001f44e"),
    ]
    # A stopped answer clears the 👀 the way Hermes does (actions only add one).
    assert plugin._react({"chat": "-1009", "messageId": "8", "outcome": "cancelled"}) is None
    assert calls[1:] == [("-1009", "8", ProcessingOutcome.CANCELLED)]
    loop.call_soon_threadsafe(loop.stop)


def test_hermes_starting_on_its_own_answers_none_of_his_messages(env: Any) -> None:
    """A Kanban card's wake (Hermes's notifier) starts a turn in the Co-Founder's chat
    while his newest message is not handed over yet: it is still handed over."""
    from agos_core.actions.services.channel import owner_needs
    from agos_core.db import chats as chats_repo

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    chat_id = owner_needs.ensure_cofounder_chat(core, ws)
    assert chat_id is not None
    mine = chats_repo.add_chat_message(core.db, ws, chat_id, "owner", "/task later")
    assert mine is not None
    start = _bridge(client, ws, key, "turn-start", {"chat": f"agos:{chat_id}", "sessionId": "w"})
    turn = chats_repo.get_turn(core.db, int(start.json()["turnId"]))
    assert turn is not None and turn.asked_up_to < mine
    _bridge(client, ws, key, "turn-finish", {"turnId": turn.id, "text": "Card done."})
    # His own message, handed over (the turn AGOS opens), is answered as before.
    turn_id = hermes_channel._open_turn(core, ws, chat_id, mine)
    again = _bridge(client, ws, key, "turn-start", {"chat": f"agos:{chat_id}", "sessionId": "w"})
    assert again.json()["turnId"] == turn_id
    got = chats_repo.get_turn(core.db, int(turn_id or 0))
    assert got is not None and got.asked_up_to == mine


def test_the_plugin_lets_in_only_whom_hermes_lets_in(env: Any, monkeypatch: Any) -> None:
    """Who may talk to the bot is Hermes's own: a message reaches AGOS only once
    Hermes admitted it (post_gateway_admission), never before (pre_gateway_dispatch
    hands nothing on and asks no private check of Hermes). A /command is mirrored
    only for someone in Hermes's own allowlist or pairing (read from its files)."""
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    posted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})

    def post(path: str, body: dict[str, Any], timeout: float = 0) -> dict[str, Any]:
        posted.append((path, body))
        return {}

    monkeypatch.setattr(plugin, "post", post)

    class Gateway:
        def _is_user_authorized_for_source(self, source: Any) -> bool:
            raise AssertionError("Hermes's private check is never called")

    def event(text: str, user: str) -> Any:
        source = types.SimpleNamespace(
            platform="telegram", chat_id=user, thread_id=None, user_id=user, chat_name=""
        )
        return types.SimpleNamespace(
            text=text, source=source, message_id="1", internal=False, metadata={}, media_urls=[]
        )

    assert asyncio.run(plugin.pre_gateway_dispatch(event("let me in", "999"), Gateway())) is None
    assert posted == []  # a plain message: nothing before Hermes admits it
    # Admitted by Hermes: it reaches AGOS (with what only the event carried).
    source = {"platform": "telegram", "chat_id": "555", "user_id": "555", "chat_type": "dm"}
    asyncio.run(
        plugin.post_gateway_admission(
            session_key="agent:main:telegram:dm:555",
            platform="telegram",
            source=source,
            message_id="1",
            text="hello",
        )
    )
    assert posted[-1][0] == "incoming" and posted[-1][1]["authorized"] is True
    assert plugin._keys["555:0"] == "agent:main:telegram:dm:555"  # Hermes's own key
    # His message typed in AGOS (put in here by the plugin) is not twice; the same
    # words typed in Telegram afterwards are his new message.
    n = len(posted)
    plugin._from_agos["555:0"] = ["from AGOS"]
    for _ in range(2):
        asyncio.run(
            plugin.post_gateway_admission(
                platform="telegram", source=source, message_id="13", text="from AGOS"
            )
        )
    assert len(posted) == n + 1
    # A /command: AGOS decides from Hermes's own allowlist and pairing.
    asyncio.run(plugin.pre_gateway_dispatch(event("/start agos123", "999"), Gateway()))
    assert posted[-1] == ("command", {"chat": "999:0", "sender": "999", "text": "/start agos123"})
    stranger = _bridge(
        client, ws, key, "command", {"chat": "999:0", "sender": "999", "text": "/start x"}
    ).json()
    assert stranger == {"shown": False}
    assert core.db.execute("SELECT count(*) FROM chat_addresses").fetchone()[0] == 0
    owner = _bridge(
        client, ws, key, "command", {"chat": f"{OWNER}:0", "sender": str(OWNER), "text": "/status"}
    ).json()
    assert owner == {"shown": True}
    assert not hasattr(plugin, "_authorized")


def test_an_approval_in_an_agos_chat_is_hermess_own_telegram_card(monkeypatch: Any) -> None:
    """The agos platform's approval prompt: AGOS said where (its approval hook's
    answer); Hermes's own Telegram adapter sends its own card there, for this AGOS
    conversation's session key (its buttons resolve that approval in Hermes)."""
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})
    monkeypatch.setattr(
        plugin,
        "post",
        lambda path, body, timeout=0: {"ok": True, "phone": {"chat": "-1009", "thread": "42"}},
    )
    key = "agent:main:agos:dm:12"
    plugin.pre_approval_request(command="rm -rf x", session_key=key, surface="gateway")
    sent: list[dict[str, Any]] = []

    class Telegram:
        async def send_exec_approval(self, **kwargs: Any) -> Any:
            sent.append(kwargs)
            return types.SimpleNamespace(success=True, message_id="77")

    monkeypatch.setitem(plugin._process(), "telegram", Telegram())
    prompt = types.SimpleNamespace(
        session_key=key,
        command="rm -rf x",
        description="delete",
        actions=[("Allow once", "once", ""), ("Deny", "deny", "")],
        smart_denied=False,
    )
    asyncio.run(plugin._phone_card(prompt))
    assert sent == [
        {
            "chat_id": "-1009",
            "command": "rm -rf x",
            "session_key": key,
            "description": "delete",
            "metadata": {"thread_id": "42"},
            "allow_permanent": False,
            "allow_session": False,
            "smart_denied": False,
        }
    ]
    asyncio.run(plugin._phone_card(prompt))
    assert len(sent) == 1  # one card per approval
    # No place on the phone (no bot, or he turned these off): no card.
    monkeypatch.setattr(plugin, "post", lambda path, body, timeout=0: {"ok": True, "phone": None})
    plugin.pre_approval_request(command="ls", session_key=key, surface="gateway")
    asyncio.run(plugin._phone_card(prompt))
    assert len(sent) == 1


def test_the_outbox_goes_out_with_hermess_own_send(monkeypatch: Any) -> None:
    """A relayed reply goes out with the Telegram adapter's own send (Hermes's
    formatting and splitting, the topic as its thread), never mirrored back into
    AGOS; a card is one message with its buttons."""
    import asyncio as _asyncio
    import threading
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    loop = _asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    monkeypatch.setitem(plugin._ctx, "loop", loop)
    said: list[tuple[str, str, Any]] = []

    async def send(chat: str, text: str, reply_to: Any = None, metadata: Any = None) -> Any:
        said.append((chat, text, metadata))
        return types.SimpleNamespace(success=True, message_id="31")

    monkeypatch.setitem(plugin._ctx, "send", send)
    native = types.SimpleNamespace(bot=types.SimpleNamespace())
    got = plugin._send_item(
        native, {"address": "-1009:41", "text": "**Writer:**\nhi", "buttons": []}
    )
    assert got == ("31", None)
    assert said == [("-1009", "**Writer:**\nhi", {"thread_id": "41"})]
    loop.call_soon_threadsafe(loop.stop)


def test_his_room_message_goes_through_the_room_services_own_send(monkeypatch: Any) -> None:
    """The owner's message into a Hermes room: the service's public send (no private
    authority calls), with Hermes's own event id for his client id."""
    import sys
    import types

    from agos_core.hermes_plugin.agos_guard import rooms

    calls: list[dict[str, Any]] = []

    class Service:
        def send(self, *, room_id: str, event_id: str, payload: Any) -> dict[str, Any]:
            calls.append({"room": room_id, "event": event_id, "payload": payload})
            return {"event_id": event_id}

    hr = types.ModuleType("gateway.hosted_rooms")
    hr.user_event_id = lambda client_id: f"user:{client_id}"  # type: ignore[attr-defined]
    gateway = types.ModuleType("gateway")
    gateway.hosted_rooms = hr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", gateway)
    monkeypatch.setitem(sys.modules, "gateway.hosted_rooms", hr)
    assert rooms._send(Service(), "room_1", "c9", "hello team") == "user:c9"
    assert calls == [
        {
            "room": "room_1",
            "event": "user:c9",
            "payload": {"text": "hello team", "thread_id": "main"},
        }
    ]


def test_how_an_answer_ended_is_hermess_own(env: Any) -> None:
    """How a turn ended is Hermes's on_session_end hook (its turn_exit_reason),
    told after the answer: AGOS keeps it on its turn record (never agent.log).
    Its model stays Hermes's (the session's); AGOS keeps no copy."""
    import inspect

    from agos_core.actions.services.chat import view as chat_view
    from agos_core.actions.services.system import workspace_log as log_api
    from agos_core.db import chats as db_chats

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"chat": str(OWNER), "sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"text": "hi", "messageId": "1"})
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    # Hermes ended it with no answer: turn-finish, then its turn-end says why.
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "failed": True})
    row = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (start["turnId"],)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "The model gave no answer, even after retries"
    assert not {"usage", "provider", "model"} & set(row.keys())
    turns = client.get(f"/workspaces/{ws}/chats/{start['chatId']}").json()["turns"]
    last = turns[-1]
    assert last["status"] == "failed"
    assert last["error"] == "The model gave no answer, even after retries"
    assert last["model"] == "fake-model"
    # Stopped (Hermes's /stop): no answer, only Hermes's turn end, which closes it.
    _bridge(client, ws, key, "incoming", me | {"text": "again", "messageId": "2"})
    again = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    end = {"turnId": again["turnId"], "reason": "interrupted_by_user"}
    assert _bridge(client, ws, "x" * 64, "turn-end", end).status_code == 401
    assert _bridge(client, ws, key, "turn-end", end).status_code == 200
    assert chats_repo.live_turn(core.db, again["chatId"]) is None
    last = client.get(f"/workspaces/{ws}/chats/{start['chatId']}").json()["turns"][-1]
    assert (last["status"], last["error"]) == ("stopped", None)
    # A late failure on an answered turn is kept with Hermes's reason.
    hermes_channel.turn_ended(core, ws, again["turnId"], "max_iterations_reached(90/90)")
    row = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (again["turnId"],)).fetchone()
    assert (row["status"], row["error"]) == ("failed", "It reached its step limit")
    # Guard: no AGOS code reads Hermes's agent.log for a turn's end.
    # hermes_channel is a facade (read with its parts); db/chats's read model is chat_view now.
    texts = [split_source(hermes_channel), inspect.getsource(chat_view)]
    for source in [*texts, *(inspect.getsource(m) for m in (db_chats, hc, log_api))]:
        assert "Turn ended" not in source
        assert "hermes_turns" not in source


def test_the_plugin_reports_how_hermes_ended_a_turn(monkeypatch: Any) -> None:
    """In Hermes: on_session_end (after post_llm_call) sends Hermes's
    turn_exit_reason for the AGOS turn; a turn with no answer closes there."""
    from agos_core.hermes_plugin.agos_guard import bridge

    sent: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any], *_: Any) -> dict[str, Any]:
        sent.append((path, body))
        return {}

    monkeypatch.setattr(bridge, "post", post)
    monkeypatch.setattr(bridge, "_live_add", lambda *a, **k: None)
    bridge._turns[("s1", "t1")] = 7
    bridge.post_llm_call("s1", "t1", assistant_response="done", platform="agos")
    bridge.on_session_end(session_id="s1", turn_id="t1", turn_exit_reason="text_response(x)")
    assert sent == [
        ("turn-finish", {"turnId": 7, "text": "done"}),
        ("turn-end", {"turnId": 7, "reason": "text_response(x)"}),
    ]
    sent.clear()
    bridge._turns[("s1", "t2")] = 8  # no answer: post_llm_call never fired
    bridge.on_session_end(session_id="s1", turn_id="t2", turn_exit_reason="budget_exhausted")
    assert sent == [("turn-end", {"turnId": 8, "reason": "budget_exhausted"})]
    sent.clear()
    bridge.on_session_end(session_id="s1", turn_id="t9", turn_exit_reason="x")  # not AGOS's
    bridge.on_session_end(session_id="s1")  # a CLI exit shape: no turn
    assert sent == []


def test_an_answer_hermes_stopped_closes_at_once(env: Any) -> None:
    """Hermes's /stop (or /new while it works) sends no answer and fires no
    post_llm_call: its agent_loop_stopped closes the AGOS turn at once, stopped
    with Hermes's reason (failed for any other reason), never left running."""
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"chat": str(OWNER), "sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"text": "hi", "messageId": "1"})
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    stop = {"turnId": start["turnId"], "reason": "Stop requested"}
    assert _bridge(client, ws, "x" * 64, "turn-stop", stop).status_code == 401
    assert _bridge(client, ws, key, "turn-stop", stop).status_code == 200
    row = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (start["turnId"],)).fetchone()
    assert (row["status"], row["error"]) == ("stopped", "Stop requested")
    assert row["ended_at"] is not None
    assert chats_repo.live_turn(core.db, start["chatId"]) is None
    # Ended already: a late stop (or finish) changes nothing.
    _bridge(client, ws, key, "turn-stop", stop | {"reason": "Gateway shutting down"})
    row = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (start["turnId"],)).fetchone()
    assert (row["status"], row["error"]) == ("stopped", "Stop requested")
    # Any other reason Hermes gives: failed, with that reason.
    _bridge(client, ws, key, "incoming", me | {"text": "again", "messageId": "2"})
    again = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    why = "Execution timed out (inactivity)"
    _bridge(client, ws, key, "turn-stop", {"turnId": again["turnId"], "reason": why})
    row = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (again["turnId"],)).fetchone()
    assert (row["status"], row["error"]) == ("failed", why)


def test_the_plugin_closes_a_turn_hermes_stopped(monkeypatch: Any) -> None:
    """In Hermes (the agos-guard plugin): Hermes's agent_loop_stopped names the
    conversation's session key; the AGOS turn opened in it is told stopped, with
    Hermes's reason, off the gateway's loop; another conversation's is left."""
    import sys
    import threading
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    posted: list[tuple[str, dict[str, Any]]] = []
    sent = threading.Event()

    def fake_post(path: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        posted.append((path, body))
        if path == "turn-stop":
            sent.set()
        return {"turnId": 41} if path == "turn-start" else {}

    monkeypatch.setattr(plugin, "post", fake_post)
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "http://127.0.0.1:1"})
    session_env = {"HERMES_SESSION_KEY": "agent:main:agos:dm:3", "HERMES_SESSION_CHAT_ID": "3"}
    fake = types.ModuleType("gateway.session_context")
    fake.get_session_env = lambda name, default="": session_env.get(name, default)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.session_context", fake)
    plugin.pre_llm_call("s1", "u1", platform="agos", sender_id="3", user_message="hi")
    assert plugin._turns[("s1", "u1")] == 41
    plugin._turns[("s2", "u2")] = 42  # another conversation's answer
    plugin._turn_keys[("s2", "u2")] = "agent:main:telegram:dm:9"

    plugin.agent_loop_stopped(session_key="agent:main:other", platform="agos", reason="x")
    plugin.agent_loop_stopped(session_key="agent:main:agos:dm:3", platform="tui", reason="x")
    plugin.agent_loop_stopped(
        session_key="agent:main:agos:dm:3",
        platform="agos",
        reason="Stop requested",
        invalidation_reason="stop_command",
    )
    assert sent.wait(5)
    assert posted[-1] == ("turn-stop", {"turnId": 41, "reason": "Stop requested"})
    assert [p for p, _ in posted].count("turn-stop") == 1
    assert ("s1", "u1") not in plugin._turns and ("s1", "u1") not in plugin._turn_keys
    # Its answer coming after all: nothing more is told.
    plugin.post_llm_call("s1", "u1", assistant_response="late", platform="agos")
    assert [p for p, _ in posted].count("turn-finish") == 0
    assert plugin._turns.pop(("s2", "u2")) == 42
    plugin._turn_keys.pop(("s2", "u2"))


def test_the_plugin_listens_for_hermess_stop() -> None:
    """The hook is Hermes's own (H: hermes_cli/plugins.py VALID_HOOKS)."""
    import inspect

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    source = inspect.getsource(plugin.register)
    assert 'ctx.register_hook("agent_loop_stopped", bridge_hooks.agent_loop_stopped)' in source


def test_plugin_stops_a_telegram_turn_whose_start_saw_no_session_key(monkeypatch: Any) -> None:
    """Live: his /stop in Telegram left the AGOS turn running, because the turn's
    start had no session key to note. The stop now finds the answer running in that
    chat (Hermes's key names the chat) and closes its turn."""
    import sys
    import threading
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    posted: list[tuple[str, dict[str, Any]]] = []
    sent = threading.Event()

    def fake_post(path: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        posted.append((path, body))
        if path == "turn-stop":
            sent.set()
        return {"turnId": 819} if path == "turn-start" else {}

    monkeypatch.setattr(plugin, "post", fake_post)
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "http://127.0.0.1:1"})
    monkeypatch.setattr(plugin, "_home", lambda: None)
    monkeypatch.setattr(plugin, "_keys", {})
    fake = types.ModuleType("gateway.session_context")
    fake.get_session_env = lambda name, default="": default  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.session_context", fake)
    plugin.pre_llm_call(
        "s9", "t9", platform="telegram", sender_id="7245299860", user_message="salam"
    )
    assert plugin._turns[("s9", "t9")] == 819
    plugin.agent_loop_stopped(
        session_key="agent:main:telegram:dm:7245299860",
        platform="telegram",
        reason="Stop requested",
        invalidation_reason="stop_command",
    )
    assert sent.wait(5)
    assert posted[-1] == ("turn-stop", {"turnId": 819, "reason": "Stop requested"})
    assert ("s9", "t9") not in plugin._turns


def test_hermes_decides_a_chats_name_and_its_refusal_is_shown(env: Any) -> None:
    """A chat's name is Hermes's /title: AGOS checks nothing and numbers nothing
    (Hermes's own title rules, H: hermes_state_titles.py); a refusal is shown."""

    client, core, _fake, _tg, ws = env
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Plan"}).json()["id"]
    # Another conversation of the root already holds the name: Hermes decides.
    root = core.engine.profile_home(ws)
    hermes_store.title(root, "999", "Plan B")
    hermes_store.say(root, str(chat_id), "user", "hi")
    r = client.put(f"/workspaces/{ws}/chats/{chat_id}", json={"title": "Plan B"})
    assert r.status_code == 204, r.text
    sent = core.db.execute(
        "SELECT text FROM hermes_inbox WHERE chat_ref = ? AND kind = 'command'",
        (f"agos:{chat_id}",),
    ).fetchall()
    assert [s["text"] for s in sent] == ["/title Plan B"]
    # Hermes's refusal reaches the chat (it was hidden as AGOS's own note before).
    refusal = "⚠️ Title 'Plan B' is already in use by session s_x"
    assert hermes_channel.platform_said(core, ws, f"agos:{chat_id}", refusal)
    shown = [m["body"] for m in client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]]
    assert refusal in shown
    # Its confirmation is not shown (the chat shows the new name).
    hermes_channel.platform_said(core, ws, f"agos:{chat_id}", "✏️ Session title set: **X**")
    shown = [m["body"] for m in client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]]
    assert not any(b.startswith("✏️") for b in shown)
    # Guard: no title check or "#n" numbering of AGOS's own comes back.
    source = split_source(hermes_channel) + whole_text("actions/chat.py")  # facades + parts
    assert "title_taken" not in source and "WHERE title" not in source
    assert "#{n}" not in source


def test_hermes_display_settings_stop_progress_lines(env: Any) -> None:
    """No AGOS filter for Hermes's progress lines: the agos platform registers
    Hermes's quietest display tier and its profile turns those notes off."""
    from agos_core.hermes_plugin.agos_guard import bridge

    assert not hasattr(hermes_channel, "PROGRESS_MARKS")
    assert "⏳" not in split_source(hermes_channel)
    assert 'display_tier="minimal"' in split_source(bridge)


def test_the_outbox_hands_its_rows_to_a_gateway_that_waits(env: Any) -> None:
    """A waiting gateway gets the rows at once (a gone one claims nothing)."""
    client, core, _fake, _tg, ws = env
    cid, key = _hermes_bot(client, core, ws)
    core.db.execute(
        """INSERT INTO channel_outbox (connection_id, address, body, source, created_at)
           VALUES (?, ?, 'hello there', 'test:1', '2026-10-20T00:00:00Z')""",
        (cid, f"{OWNER}:0"),
    )
    got = client.post(
        f"/hermes-bridge/{ws}/outbox", json={}, headers={"authorization": f"Bearer {key}"}
    ).json()
    assert [s["text"] for s in got["send"]] == ["hello there"]


def test_a_dead_gateways_last_snapshot_never_shows_a_green_lamp(env: Any) -> None:
    """area1 P1: the lamp is Hermes's verdict (engine.gateway_status: its pid live
    by Hermes's start-time guard, the snapshot not stale), not the last file a
    crashed gateway left behind."""
    client, core, _fake, _tg, ws = env
    _hermes_bot(client, core, ws)
    home = core.engine.profile_home(ws)
    connected = {"platforms": {"telegram": {"state": "connected"}}, "gateway_state": "running"}
    (home / "gateway_state.json").write_text(json.dumps({**connected, "pid": 999_999_999}))
    shown = client.get("/channels").json()[0]
    assert shown["status"] == "connecting" and "isn't running" in shown["statusReason"]
    old = "2026-01-01T00:00:00+00:00"  # alive, but no heartbeat for months: wedged
    (home / "gateway_state.json").write_text(
        json.dumps({**connected, "pid": __import__("os").getpid(), "updated_at": old})
    )
    assert client.get("/channels").json()[0]["status"] == "connecting"
