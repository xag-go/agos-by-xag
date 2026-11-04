"""Guards for Telegram on Hermes: a member's topic is Hermes's own routed
conversation (Hermes sends the member's answer once, itself), the plugin uses
Hermes's public hooks, and nothing is sent twice. Each guard fails when the old
AGOS way comes back."""

import ast
import asyncio
import json
import re
import sys
import threading
import types
from pathlib import Path
from typing import Any

from ownership_scan import REGISTRY_MODULES

from agos_core.hermes_plugin.agos_guard import bridge as plugin

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
PLUGIN = SRC / "hermes_plugin" / "agos_guard"
SECOND_COPY = re.compile(r"INSERT[^;]*?channel_outbox[^;]*?f\"turn:\{turn_id\}\"", re.S)
MEMBER_RELAY = re.compile(r"msg:h|_queue_member_answers|_hermes_answer\b")


def _sources() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): p.read_text()
        for p in SRC.rglob("*.py")
        if not p.relative_to(SRC).as_posix().startswith("db/migrations")
    }


# ---- item 1/2: member topics are Hermes's ---------------------------------------------


def test_only_hermes_sends_member_answers() -> None:
    hits = [rel for rel, text in _sources().items() if SECOND_COPY.search(text)]
    assert hits == [], f"a second relay of member answers came back: {hits}"
    relay = [rel for rel, text in _sources().items() if MEMBER_RELAY.search(text)]
    assert relay == [], f"AGOS's member-answer relay came back: {relay}"


def test_the_guard_sees_the_old_relay() -> None:
    old = '''core.db.execute("""INSERT OR IGNORE INTO channel_outbox (body, source)
        VALUES (?, ?)""", (text, f"turn:{turn_id}"))'''
    assert SECOND_COPY.search(old)
    assert MEMBER_RELAY.search('source = f"msg:h{m.id}"')
    assert MEMBER_RELAY.search("return added + _queue_member_answers(core)")


def _calls_in(rel: str, function: str) -> set[str]:
    tree = ast.parse((SRC / rel).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            # A bare call (`_dm_member(...)`) or a module's (`hermes_addresses._dm_member(...)`).
            return {
                sub.func.id if isinstance(sub.func, ast.Name) else sub.func.attr
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call) and isinstance(sub.func, (ast.Name, ast.Attribute))
            }
    raise AssertionError(f"{rel}: {function} is gone")


def test_no_member_dm_exception_where_hermes_routes_the_topic() -> None:
    """The member-DM special cases of before (its web messages forced onto the agos
    platform, its topic intercepted and its files copied, its answer relayed, its 👀
    held) are Hermes's routing now: none of these asks `_dm_member` again."""
    for rel, function in (
        ("actions/services/channel/hermes_addresses.py", "chat_on_hermes"),
        ("actions/services/channel/gateway_messages.py", "incoming"),
        ("actions/services/channel/gateway_messages.py", "_reaction_outcome"),
        ("actions/channels.py", "queue_replies"),
    ):
        assert "_dm_member" not in _calls_in(rel, function), f"{rel}: {function}"


def test_only_member_topics_writes_hermess_routes() -> None:
    """`gateway.profile_routes` is written in one place, with Hermes's config CLI:
    no other call anywhere is handed that key. The ownership registry only names it
    as evidence (its `agos(...)`/`move(...)` entries write nothing); any other call
    there is still checked."""
    writers = []
    for rel, text in _sources().items():
        if rel == "actions/member_topics.py":
            continue
        for node in ast.walk(ast.parse(text)):
            reads = isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get"
            if rel in REGISTRY_MODULES and isinstance(node, ast.Call):
                reads = reads or getattr(node.func, "id", "") in {"agos", "move", "cols"}
            if (
                isinstance(node, ast.Call)
                and not reads
                and any(
                    isinstance(a, ast.Constant) and "profile_routes" in str(a.value)
                    for a in [*node.args, *(k.value for k in node.keywords)]
                )
            ):
                writers.append(rel)
    assert writers == [], writers
    text = (SRC / "actions/member_topics.py").read_text()
    assert "engine.set_setting(workspace_id, ROUTES_KEY" in text
    assert 'ROUTES_KEY = "gateway.profile_routes"' in text


def test_the_reader_shows_a_members_telegram_session() -> None:
    """A member's DM's Telegram place is read in its own profile too (no `agent`
    exception in the places, no root-only Telegram filter)."""
    chats = (SRC / "db/chats.py").read_text()
    places = chats[chats.index("def _telegram_places") : chats.index("def where_of")]
    assert 'row["agent"]' not in places
    store = (SRC / "hermes_gateway/chat_sessions.py").read_text()
    session_filter = store[store.index("def _session_filter") : store.index("def sessions(")]
    assert "where.own" not in session_filter


# ---- item 4: duplicate sends -----------------------------------------------------------


def test_telegram_is_quiet_and_restarts_drain() -> None:
    """Telegram gets only the answer (no interim commentary, no working bubble), and
    a restart AGOS makes lets a running answer finish first."""
    from agos_core.actions.library import profile_settings
    from agos_core.engine.hermes import RESTART_DRAIN_S, STOP_WAIT_S

    pairs = profile_settings([], {})
    assert pairs["display.platforms.telegram.interim_assistant_messages"] == "false"
    assert pairs["display.platforms.telegram.long_running_notifications"] == "false"
    assert int(pairs["agent.restart_drain_timeout"]) == RESTART_DRAIN_S > 0
    assert STOP_WAIT_S > RESTART_DRAIN_S  # AGOS's stop waits for Hermes's drain
    assert json.loads(pairs["plugins.entries.agos-guard.granted_capabilities"]) == [
        "gateway.platform_actions"
    ]


def test_an_outbox_row_goes_out_once(monkeypatch: Any, tmp_path: Path) -> None:
    """A send that timed out may be on Telegram already: it is done, never sent
    again; a row AGOS hands out again (its "sent" got lost) is only reported."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    sent: list[str] = []
    posted: list[tuple[str, dict[str, Any]]] = []
    hand_out: list[dict[str, Any]] = []

    async def send(chat: str, text: str, *_: Any) -> Any:
        sent.append(text)
        if text == "slow":
            await asyncio.sleep(1)
        return types.SimpleNamespace(success=True, message_id=f"m{len(sent)}")

    def post(path: str, body: dict[str, Any], timeout: float = 0) -> Any:
        posted.append((path, body))
        return {"send": hand_out} if path == "outbox" else {}

    monkeypatch.setattr(plugin, "post", post)
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})
    monkeypatch.setattr(plugin, "_home", lambda: tmp_path)
    monkeypatch.setattr(plugin, "BOT_WAIT_S", 0.2)
    monkeypatch.setattr(plugin, "_sent", {})
    monkeypatch.setitem(plugin._ctx, "native", object())
    monkeypatch.setitem(plugin._ctx, "send", send)
    monkeypatch.setitem(plugin._ctx, "loop", loop)
    hand_out[:] = [
        {"id": 1, "address": "-1009:5", "text": "hello"},
        {"id": 2, "address": "-1009:5", "text": "slow"},
    ]
    assert plugin._send_once()
    done = [b for p, b in posted if p == "outbox-done"]
    assert [(d["id"], d["messageId"], d["error"]) for d in done] == [
        (1, "m1", None),
        (2, plugin.UNSURE, None),  # unsure: done, AGOS never hands it out again
    ]
    # AGOS hands both out again (say its "sent" never arrived): nothing is resent.
    posted.clear()
    assert plugin._send_once()
    assert sent == ["hello", "slow"]
    assert [b["messageId"] for p, b in posted if p == "outbox-done"] == ["m1", plugin.UNSURE]
    # Kept across a gateway restart.
    assert json.loads((tmp_path / plugin.SENT_FILE).read_text()) == {"1": "m1", "2": "unsure"}
    loop.call_soon_threadsafe(loop.stop)


# ---- item 5: approval cards of group / topic sessions ----------------------------------


def test_a_group_topics_approval_finds_its_chat_after_a_restart(monkeypatch: Any) -> None:
    """Hermes's key of a group's topic (the Co-Founder's, or a member's routed one)
    names its AGOS address even when this gateway has seen no message there yet."""
    monkeypatch.setattr(plugin, "_keys", {})
    assert plugin._chat_of("agent:main:telegram:group:-1004435538056:5") == "-1004435538056:5"
    assert (
        plugin._chat_of("agent:a-language-coach:telegram:group:-1004435538056:5")
        == "-1004435538056:5"
    )
    assert plugin._chat_of("agent:main:telegram:group:-1001") == "-1001:0"
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "4242")
    assert plugin._chat_of("agent:main:telegram:group:-1001:4242") == "-1001:0"  # his own
    assert plugin._chat_of("agent:main:telegram:group:-1001:5:4242") == "-1001:5"
    assert plugin._chat_of("agent:main:telegram:dm:4242") == "4242:0"
    assert plugin._chat_of("agent:main:telegram:dm:4242:17") == "4242:17"
    assert plugin._chat_of("agent:main:telegram:group:not-a-chat:5") is None
    asked: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(plugin, "bridge", lambda: {"core": "x", "workspace": "w", "key": "k"})

    def post(path: str, body: dict[str, Any], timeout: float = 0) -> dict[str, Any]:
        asked.append((path, body))
        return {}

    monkeypatch.setattr(plugin, "post", post)
    plugin.pre_approval_request(
        command="rm -rf x",
        session_key="agent:a-language-coach:telegram:group:-1004435538056:5",
        surface="gateway",
    )
    assert asked and asked[0][0] == "approval" and asked[0][1]["chat"] == "-1004435538056:5"


# ---- item 7: Hermes's public plugin API ------------------------------------------------


def test_the_plugin_asks_no_private_hermes_check() -> None:
    text = "\n".join(p.read_text() for p in PLUGIN.glob("*.py"))
    assert "_is_user_authorized_for_source" not in text
    assert "_is_cron_approval_context" not in text
    bridge = "".join(p.read_text() for p in PLUGIN.glob("bridge*.py"))
    assert "post_gateway_admission" in bridge and "platform_actions" in bridge
    assert "current_cron_execution" in (PLUGIN / "owner_approval.py").read_text()  # _in_cron


def test_a_cron_run_is_hermess_own_cron_execution(monkeypatch: Any) -> None:
    from agos_core.hermes_plugin import agos_guard

    monkeypatch.setitem(sys.modules, "gateway.session_context", None)
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    running: list[Any] = [None]
    ctx = types.SimpleNamespace(current_cron_execution=lambda: running[0])
    monkeypatch.setitem(agos_guard._CTX, "ctx", ctx)
    assert agos_guard._in_cron() is False
    running[0] = types.SimpleNamespace(job_id="j1")
    assert agos_guard._in_cron() is True
    # A cron run's delegated child: Hermes's execution says None, its session flag stays.
    running[0] = None
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert agos_guard._in_cron() is True


def test_the_plugin_binds_a_topic_only_when_hermes_routes_it(monkeypatch: Any) -> None:
    """The live move: the topic's key points at the member's session from before
    (Hermes's own SessionStore.switch_session), only when Hermes routes the topic
    to that member and the key has no conversation yet."""
    calls: list[tuple[str, ...]] = []

    class Store:
        def __init__(self) -> None:
            self.keys: dict[str, str] = {}

        def lookup_by_session_key(self, key: str) -> Any:
            return types.SimpleNamespace(session_id=self.keys[key]) if key in self.keys else None

        def get_or_create_session(self, source: Any) -> Any:
            calls.append(("create", source.profile))
            self.keys["k"] = "fresh"
            return types.SimpleNamespace(session_id="fresh")

        def switch_session(self, key: str, sid: str, **_: Any) -> Any:
            calls.append(("switch", key, sid))
            self.keys[key] = sid
            return types.SimpleNamespace(session_id=sid)

    store = Store()
    routed = {"profile": "a-language-coach"}
    monkeypatch.setattr(plugin, "_runner", lambda: types.SimpleNamespace(session_store=store))
    monkeypatch.setattr(
        plugin, "_source_for", lambda _a, _addr: types.SimpleNamespace(profile=routed["profile"])
    )
    monkeypatch.setattr(plugin, "_session_key_of", lambda _s: "k")
    monkeypatch.setattr(plugin, "_remember_key", lambda *_: None)
    monkeypatch.setitem(plugin._ctx, "adapter", object())
    body = json.dumps({"session": "20261014_220413_08fd55", "profile": "a-language-coach"})
    routed["profile"] = ""  # not routed yet: nothing is bound
    assert plugin._bind("-1004435538056:5", body) is True
    assert calls == []
    routed["profile"] = "a-language-coach"
    assert plugin._bind("-1004435538056:5", body) is True
    assert calls == [("create", "a-language-coach"), ("switch", "k", "20261014_220413_08fd55")]
    assert plugin._bind("-1004435538056:5", body) is True  # once
    assert len(calls) == 2
    monkeypatch.setitem(plugin._ctx, "adapter", None)
    assert plugin._bind("-1:5", body) is False  # the bot isn't up: AGOS hands it again


def test_a_web_message_to_a_member_topic_goes_in_as_his_message(monkeypatch: Any) -> None:
    """After a restart Hermes cannot inject into a topic routed to a member (its
    profile has no Telegram bot; H: gateway/authz_mixin.py _delivery_adapter_for):
    his web message goes in as his message there (with its files), in a member's
    topic and in the root's own chats alike; nothing is injected."""
    injected: list[str] = []
    fed: list[tuple[str, str]] = []
    done: list[Any] = []
    keys = {
        "-1004435538056:5": "agent:a-language-coach:telegram:group:-1004435538056:5",
        "4242:0": "agent:main:telegram:dm:4242",
    }
    items = [{"id": 1, "chat": a, "text": f"hi {a}"} for a in keys]

    def inject(_text: str, session_key: str) -> bool:
        injected.append(session_key)
        return True

    def feed(address: str, item: dict[str, Any]) -> bool:
        fed.append((address, str(item["text"])))
        return True

    def post(path: str, body: Any, _t: Any) -> Any:
        if path == "next":
            return {"items": items}
        done.append(body)
        return None

    ctx = types.SimpleNamespace(inject_message=inject)
    monkeypatch.setitem(plugin._ctx, "ctx", ctx)
    monkeypatch.setattr(plugin, "bridge", lambda: object())
    monkeypatch.setattr(plugin, "_key_for", lambda a: keys[a])
    monkeypatch.setattr(plugin, "_has_session", lambda _k: True)
    monkeypatch.setattr(plugin, "_run_message", feed)
    monkeypatch.setattr(plugin, "post", post)
    plugin._poll_once()
    assert fed == [("-1004435538056:5", "hi -1004435538056:5"), ("4242:0", "hi 4242:0")]
    assert injected == []
    assert all(d["ok"] for d in done)
