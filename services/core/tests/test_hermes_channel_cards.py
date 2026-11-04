"""Reminders as Hermes cron jobs, Hermes's own token counts, cards as Hermes's own
kanban, sent on its bot, and topics made by the workspace's Hermes gateway."""

import json
import sqlite3
import time
from typing import Any

from channels_rig import OWNER
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram
from hermes_channel_rig import (
    _bridge,
    _hermes_bot,
)

from agos_core.actions import channels, hermes_channel


def test_reminders_and_watches_are_hermes_cron_jobs(env: Any, monkeypatch: Any) -> None:
    """What an agent schedules (come back later, keep an eye on something) is a job of
    the workspace's Hermes cron: AGOS lists it with Stop; what the job says reaches
    the chat it came from, once."""
    import json

    client, core, _fake, _tg, ws = env
    key = hermes_channel.bridge_key(core, ws)
    cron = core.engine.profile_home(ws) / "cron"
    cron.mkdir(parents=True, exist_ok=True)
    job = {
        "id": "a1b2",
        "name": "Remind him",
        "prompt": "Ask about the logo",
        "schedule_display": "once at 18:00",
        "next_run_at": "2026-10-07T18:00:00+00:00",
        "enabled": True,
    }
    (cron / "jobs.json").write_text(json.dumps({"jobs": [job]}))
    got = client.get(f"/workspaces/{ws}/ongoing").json()["jobs"]
    assert [(j["id"], j["name"], j["schedule"]) for j in got] == [
        ("a1b2", "Remind him", "once at 18:00")
    ]
    removed: list[tuple[str, ...]] = []

    def hermes(_ws: str, *args: str, **_kw: Any) -> str:
        removed.append(args)
        return ""

    monkeypatch.setattr(core.engine, "_hermes", hermes, raising=False)
    r = client.post(f"/workspaces/{ws}/scheduled/a1b2/remove")
    assert r.status_code == 204, r.text
    assert removed == [("cron", "remove", "a1b2")]
    assert client.post(f"/workspaces/{ws}/scheduled/nope/remove").status_code == 404
    # AGOS's own rhythm jobs are marked as the system's, and Stop refuses them (they
    # are turned off on the Vision page / the agent card, where AGOS keeps their time).
    rhythm_jobs = [
        {"id": "s1", "name": "AGOS daily plan", "prompt": "p", "enabled": True},
        {"id": "s2", "name": "AGOS heartbeat", "prompt": "p", "enabled": True},
        {"id": "a3", "name": "Watch the page", "prompt": "p", "enabled": True},
    ]
    (cron / "jobs.json").write_text(json.dumps({"jobs": rhythm_jobs}))
    got = client.get(f"/workspaces/{ws}/ongoing").json()["jobs"]
    assert [(j["id"], j["system"]) for j in got] == [
        ("s1", "daily"),
        ("s2", "heartbeat"),
        ("a3", None),
    ]
    removed.clear()
    assert client.post(f"/workspaces/{ws}/scheduled/s1/remove").status_code == 409
    assert removed == []
    # The job's message reaches the AGOS chat (sent by Hermes to agos:<chat>), once.
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Logo"}).json()["id"]
    for _ in range(2):
        _bridge(client, ws, key, "platform-send", {"chat": f"agos:{chat_id}", "text": "Logo time?"})
    bodies = [
        str(r["body"])
        for r in core.db.execute("SELECT body FROM messages WHERE chat_id = ?", (chat_id,))
    ]
    assert bodies.count("Logo time?") == 1
    # AGOS's own /model for the chat: its answer stays out of the chat.
    switch = hermes_channel.model_command(
        core, f"agos:{chat_id}", {"provider": "anthropic", "model": "claude-opus-5-5"}
    )
    if switch:
        core.db.execute(
            "INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at) "
            "VALUES (?, ?, ?, 'command', '2026-10-07')",
            (ws, f"agos:{chat_id}", switch),
        )
        _bridge(
            client,
            ws,
            key,
            "platform-send",
            {"chat": f"agos:{chat_id}", "text": "Model switched to x"},
        )
    from agos_core.engine.identity import RULES

    assert "cronjob tool" in RULES  # SOUL.md says how to come back later
    n = core.db.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()[0]
    assert n == 1


def test_hermes_counts_tokens_itself(monkeypatch: Any) -> None:
    """In Hermes (the agos-guard plugin): a chat answer's tokens and model are
    Hermes's own count (nothing is sent with the answer's end); in a Kanban card's
    run they add up for the card, and AGOS hears the count every half million (it
    decides who is told)."""

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    posted: list[tuple[str, dict[str, Any]]] = []

    def fake_post(path: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        posted.append((path, body))
        return {}

    monkeypatch.setattr(plugin, "post", fake_post)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    key = ("s1", "u1")
    plugin._turns[key] = 7
    plugin._busy[key] = "agos:3"
    usage = {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}
    for _ in range(3):
        plugin.api_call_done("s1", "u1", usage=usage, provider="anthropic", model="claude-x")
    assert posted == []
    assert plugin.tool_started("terminal", {}, "s1", "u1") is None
    plugin._finish("s1", "u1", "done")
    assert posted[-1] == ("turn-finish", {"turnId": 7, "text": "done"})

    # A Kanban card's run (no AGOS turn): the count is kept on the card in Hermes's
    # Kanban every half million; AGOS hears only when Hermes says it's a lot.
    from agos_core.hermes_plugin.agos_guard import tokens

    kept: list[tuple[str, str, int]] = []

    def in_hermes(card: str, run: str, total: int) -> dict[str, int] | None:
        kept.append((card, run, total))
        return {"level": 1, "tokens": total, "usual": 1} if total >= 1_000_000 else None

    monkeypatch.setattr(tokens, "record_in_hermes", in_hermes)
    posted.clear()
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_9")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "4")
    big = {"total_tokens": 300_000}
    plugin.api_call_done("w1", "x1", usage=big)
    time.sleep(0.1)
    assert posted == []  # 300k: not yet
    plugin.api_call_done("w1", "x1", usage=big)
    plugin.api_call_done("w1", "x1", usage={"total_tokens": 100_000})
    time.sleep(0.2)
    assert kept == [("t_9", "4", 600_000)] and posted == []
    plugin.api_call_done("w1", "x1", usage={"total_tokens": 500_000})
    time.sleep(0.2)
    assert posted == [
        ("card-tokens-told", {"card": "t_9", "level": 1, "tokens": 1_200_000, "usual": 1})
    ]


def test_hermes_keeps_a_cards_tokens_and_decides_when_it_is_a_lot() -> None:
    """tokens.py, on Hermes's Kanban tables: each run's total is kept on the card;
    the mark comes from the board's finished cards (3x their median, 3M at least);
    told once per level (past the mark, 2x, 4x...); runs of a card add up."""

    from agos_core.hermes_plugin.agos_guard import tokens

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
    db.execute(
        "CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,"
        " run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER)"
    )

    def append(conn: Any, task: str, kind: str, payload: Any = None, *, run_id: Any = None) -> None:
        conn.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?, ?, ?, ?, 0)",
            (task, run_id, kind, json.dumps(payload)),
        )

    assert tokens.mark(db) == 2 * tokens.MIN_MARK  # no history yet: high and safe
    for i, size in enumerate((900_000, 1_000_000, 1_100_000)):
        db.execute("INSERT INTO tasks VALUES (?, 'done')", (f"old{i}",))
        tokens.record(db, append, f"old{i}", "1", size)
    db.execute("INSERT INTO tasks VALUES ('t1', 'running')")
    assert tokens.mark(db, "t1") == 3_000_000
    assert tokens.record(db, append, "t1", "7", 2_500_000) is None  # under the mark
    told = tokens.record(db, append, "t1", "7", 3_200_000)
    assert told == {"level": 1, "tokens": 3_200_000, "usual": 1_000_000}
    assert tokens.record(db, append, "t1", "7", 3_700_000) is None  # same level: once
    # Another run adds up: 3.7M + 2.4M = 6.1M is twice the mark.
    assert tokens.record(db, append, "t1", "8", 2_400_000) == {
        "level": 2,
        "tokens": 6_100_000,
        "usual": 1_000_000,
    }
    (said,) = db.execute(
        "SELECT payload FROM task_events WHERE task_id = 't1' AND kind = ? ORDER BY id DESC",
        (tokens.TOLD,),
    ).fetchone()
    assert json.loads(said)["level"] == 2


def test_cards_are_hermess_own_kanban_create_and_agos_has_no_add_task_tool(
    env: Any,
) -> None:
    """A task from a chat is Hermes's own kanban_create (the guard applies his
    Autonomy rule "Create Kanban cards"): AGOS has no tool nor endpoint of its own."""
    client, core, _fake, _tg, ws = env
    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    assert not hasattr(plugin, "add_task_tool") and not hasattr(plugin, "ADD_TASK_SCHEMA")
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Ideas"}).json()["id"]
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/add-task",
        json={"chat": f"agos:{chat}", "title": "Intro video"},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404


def test_hermes_sends_agos_cards_on_its_own_bot(env: Any, monkeypatch: Any) -> None:
    """AGOS's outbox goes out through the workspace's Hermes gateway: it takes each
    item once (a reply as written, for Hermes's own send; a card as one message with
    its buttons), says what it sent, and closes a card once it's answered."""
    client, core, _fake, tg, ws = env
    # No stand-in gateway here: what the real one gets.
    monkeypatch.setattr(channels, "send_round", channels.send_round.real)  # type: ignore[attr-defined]
    cid, key = _hermes_bot(client, core, ws)
    core.db.execute(
        """INSERT INTO channel_outbox (connection_id, address, body, buttons, source, created_at)
           VALUES (?, ?, 'Allow it?', '[["Yes","chatcmd:once:1"],["No","chatcmd:deny:1"]]',
                   'x', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
        (cid, f"{OWNER}:0"),
    )
    channels.tick(core)
    assert tg.sent == []  # AGOS doesn't send it itself any more
    got = _bridge(client, ws, key, "outbox", {}).json()
    (item,) = got["send"]
    assert item["text"] == "Allow it?" and item["buttons"][0] == ["Yes", "chatcmd:once:1"]
    again = channels.hermes_outbox(core, ws)
    assert again["send"] == []  # taken once
    _bridge(client, ws, key, "outbox-done", {"id": item["id"], "messageId": "77"})
    row = core.db.execute("SELECT sent_id FROM channel_outbox WHERE id = ?", (item["id"],))
    assert row.fetchone()["sent_id"] == "77"
    # Answered (the chat's turn is gone): the gateway closes the card.
    monkeypatch.setattr(channels, "_answered", lambda core, data: "Answered.")
    channels.close_answered(core)
    (closing,) = _bridge(client, ws, key, "outbox", {}).json()["close"]
    assert closing["messageId"] == "77" and closing["text"].endswith("→ Answered.")
    _bridge(client, ws, key, "outbox-done", {"id": item["id"], "kind": "close"})
    row = core.db.execute("SELECT closed_at FROM channel_outbox WHERE id = ?", (item["id"],))
    assert row.fetchone()["closed_at"]


def test_a_topic_is_made_by_the_workspaces_hermes_gateway(monkeypatch: Any) -> None:
    """AGOS never calls Telegram for a topic: it asks the workspace's Hermes gateway
    (the agos-guard plugin, its own bot) through the outbox and waits for the answer."""
    import threading

    from agos_core.actions import channels as ch
    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    made: list[tuple[int, str]] = []

    class Bot:
        async def create_forum_topic(self, chat_id: int, name: str) -> Any:
            made.append((chat_id, name))
            return type("Topic", (), {"message_thread_id": 77})()

    def gateway() -> None:
        # One round of the plugin's sender, against AGOS's own outbox functions.
        import asyncio as _asyncio

        loop = _asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True).start()
        monkeypatch.setitem(plugin._ctx, "loop", loop)
        monkeypatch.setitem(plugin._ctx, "native", type("N", (), {"bot": Bot()})())
        monkeypatch.setattr(
            plugin, "bridge", lambda: {"core": "http://127.0.0.1", "workspace": "w"}
        )

        def post(path: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
            if path == "outbox":
                return {"send": [], "close": [], "topics": ch._topics_to_make("w")}
            nobody: Any = None
            ch.hermes_outbox_done(
                nobody, "w", body["id"], body["kind"], body["messageId"], body["error"]
            )
            return {}

        monkeypatch.setattr(plugin, "post", post)
        import time as _time

        for _ in range(50):
            if plugin._send_once():
                break
            _time.sleep(0.05)

    worker = threading.Thread(target=gateway)
    worker.start()
    address = ch.make_topic.real("w", "-1009", "Invoices")  # type: ignore[attr-defined]
    worker.join(5)
    assert address == "-1009:77"
    assert made == [(-1009, "Invoices")]
