"""Channels against a fake Telegram Bot API (a real HTTP server).

The rig (fake Telegram, `env`) is tests/channels_rig.py; the QR-code bot setup is
test_telegram_bot_setup.py, who may talk to the bot test_telegram_people.py.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from channels_rig import (
    MODEL,
    OWNER,
    TOKEN,
    connect,
    hermes_says_connected,
    tick,
)
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram

from agos_core.actions import channels


def test_connect_shows_green_lamp_and_never_the_token(env: Any) -> None:
    client, core, _fake, tg, ws = env
    # Each workspace has its own channels: no bot outside one, and no Buzz.
    alone = client.post("/channels", json={"kind": "telegram", "secret": TOKEN, "allowed": ["1"]})
    assert alone.status_code == 400 and "workspace" in alone.text
    buzz = client.post("/channels", json={"kind": "buzz", "secret": "a" * 64, "allowed": ["1"]})
    assert buzz.status_code == 422
    assert (
        client.post(
            "/channels", json={"kind": "telegram", "secret": TOKEN, "allowed": []}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/channels", json={"kind": "telegram", "secret": "not-a-token-at-all", "allowed": ["1"]}
        ).status_code
        == 400
    )
    r = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": ["1"], "workspaceId": ws},
    )
    assert r.status_code == 201, r.text
    (conn,) = client.get("/channels").json()
    assert conn["status"] == "connecting" and conn["identity"] == ""  # Hermes hasn't said yet
    hermes_says_connected(core, ws)
    (conn,) = client.get("/channels").json()
    assert conn["status"] == "connected" and conn["identity"] == "@agos_test_bot"
    assert tg.asked_me == 0  # AGOS never asked Telegram itself
    assert conn["secret"] == "••••" + TOKEN[-4:]
    assert TOKEN not in client.get("/channels").text


def test_a_chat_gets_its_own_telegram_topic(env: Any) -> None:
    client, core, fake, tg, ws = env
    cid = connect(client)
    chat = client.get(f"/workspaces/{ws}/chats").json()[0]["id"]
    r = client.post(
        f"/workspaces/{ws}/chats/{chat}/addresses",
        json={"connectionId": cid, "createTopicIn": "-100"},
    )
    assert r.status_code == 201, r.text
    (addr,) = client.get(f"/workspaces/{ws}/chats/{chat}/addresses").json()
    assert addr["address"] == "-100:41"
    # The place's name is Hermes's (its channel directory), never a title snapshot.
    from agos_core.actions import hermes_channel

    cols = [r[1] for r in core.db.execute("PRAGMA table_info(chat_addresses)")]
    assert "label" not in cols
    names = {"-100:41": "Team · Sales"}
    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hermes_channel, "place_names", lambda _core, _ws: names)
        (addr,) = client.get(f"/workspaces/{ws}/chats/{chat}/addresses").json()
        assert addr["label"] == "Team · Sales"
        names["-100:41"] = "Team · Sales 2026"  # renamed in Telegram: shows at once
        (addr,) = client.get(f"/workspaces/{ws}/chats/{chat}/addresses").json()
        assert addr["label"] == "Team · Sales 2026"
    # What he writes in the topic joins that chat; Hermes answers it (never AGOS).
    tg.message("What sold today?", topic=41)
    tick(core)
    messages = client.get(f"/workspaces/{ws}/chats/{chat}").json()["messages"]
    assert [m["body"] for m in messages] == ["What sold today?"]
    assert fake.bodies == [] and tg.sent == []


def test_strangers_duplicates_and_unlinked_addresses_are_ignored(env: Any) -> None:
    client, core, fake, tg, ws = env
    cid = connect(client)
    chat = client.get(f"/workspaces/{ws}/chats").json()[0]["id"]
    client.post(
        f"/workspaces/{ws}/chats/{chat}/addresses", json={"connectionId": cid, "address": "-100"}
    )
    tg.message("hi from a stranger", sender=999)
    tg.message("in another group", chat=-200)
    tick(core)
    assert fake.bodies == [] and tg.sent == []
    # Even handed over, a stranger's message never joins a chat: only Hermes's
    # allowlist lets anyone in (AGOS keeps no list of its own to check).
    row = core.db.execute("SELECT * FROM channel_connections").fetchone()
    from agos_core.actions import hermes_channel

    assert hermes_channel.incoming(core, ws, "-100", "999", "hi", "m1", None) is True
    assert all(
        m["body"] != "hi" for m in client.get(f"/workspaces/{ws}/chats/{chat}").json()["messages"]
    )
    assert row["id"] == cid


def test_one_address_is_exactly_one_chat(env: Any) -> None:
    client, _core, _fake, _tg, ws = env
    cid = connect(client)
    first = client.get(f"/workspaces/{ws}/chats").json()[0]["id"]
    second = client.post(f"/workspaces/{ws}/chats", json={"title": "Ads"}).json()["id"]
    assert (
        client.post(
            f"/workspaces/{ws}/chats/{first}/addresses",
            json={"connectionId": cid, "address": "-100:5"},
        ).status_code
        == 201
    )
    r = client.post(
        f"/workspaces/{ws}/chats/{second}/addresses",
        json={"connectionId": cid, "address": "-100:5"},
    )
    assert r.status_code == 409
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    other_chat = client.get(f"/workspaces/{other}/chats").json()[0]["id"]
    assert (
        client.post(
            f"/workspaces/{other}/chats/{other_chat}/addresses",
            json={"connectionId": cid, "address": "-100:5"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/workspaces/{ws}/chats/{second}/addresses",
            json={"connectionId": cid, "address": "nope"},
        ).status_code
        == 400
    )


def test_a_card_is_one_telegram_message_and_replies_go_as_written() -> None:
    """Hermes's own send formats and splits a reply; one of AGOS's cards is one plain
    message with its buttons."""
    card = channels._card_text("**Writer:**\n" + "a" * 5000)
    assert card.startswith("Writer:\n") and len(card) <= channels.TELEGRAM_LIMIT


def test_the_cofounders_actions_and_requests_send_no_agos_cards(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the Co-Founder does or asks with AGOS's tools is said in its Hermes
    conversation (Hermes's own Allow / Deny card first, when he must say yes):
    AGOS sends no card of its own to Telegram."""
    from agos_core.actions import apps as apps_actions
    from agos_core.actions import capabilities, cofounder_actions
    from agos_core.db import chats as chats_repo
    from agos_core.engine import apps as apps_eng
    from agos_core.engine import capabilities as rules
    from agos_core.engine import cofounder_actions as action_rules

    client, core, _fake, tg, ws = env
    apps_actions._catalog_cache["apps"] = {
        "deepwiki": apps_eng.CatalogApp(
            name="deepwiki", description="Docs", url="https://x.example/mcp", auth="none"
        )
    }
    cid = connect(client)
    channels.link_cofounder_chat(core, cid, f"{OWNER}:0")
    dm = next(
        c for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if c["agent"] is None
    )
    turn = chats_repo.insert_turn(
        core.db, chat_id=dm["id"], workspace_id=ws, asked_up_to=0, speaker=None
    )
    capabilities.save(core, ws, dm["id"], turn, [rules.Ask("app", "deepwiki", True, "docs")])
    cofounder_actions.set_mode(core, "ask")
    (action,) = cofounder_actions.save(
        core, ws, dm["id"], turn, [action_rules.Action("add_owner_rule", {"text": "a"})]
    )
    core.db.execute("UPDATE cofounder_actions SET status = 'done' WHERE id = ?", (action,))
    tick(core)
    tick(core)
    assert not any(m.get("reply_markup") for m in tg.sent), tg.sent


def test_the_dashboard_shows_only_this_projects_channels_and_usage(env: Any) -> None:
    """A project's Dashboard never counts another project's bots, tokens or chats."""
    client, core, _fake, _tg, ws = env
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    cid = connect(client)
    core.db.execute("UPDATE channel_connections SET workspace_id = ? WHERE id = ?", (other, cid))
    now = datetime.now(UTC).isoformat()
    counted = {
        str(core.engine.profile_home(w)): tokens for w, tokens in ((ws, 1000), (other, 999_000))
    }
    for w in (ws, other):
        chat = core.db.execute(
            "INSERT INTO chats (workspace_id, title, channel, created_at, updated_at, kind)"
            " VALUES (?, 'Talk', 'web', ?, ?, 'chat') RETURNING id",
            (w, now, now),
        ).fetchone()[0]
        assert chat
    # Usage is what each workspace's own Hermes counted (its analytics, in its root).
    day = datetime.now(UTC).date().isoformat()

    def usage(root: Any, members: Any, month_days: float, chart_days: int) -> Any:
        tokens = counted[str(root)]
        return {
            "models": {"opus": {"tokens": tokens, "calls": 1, "input": tokens, "output": 0}},
            "days": {day: {"tokens": tokens, "calls": 1}},
        }

    core.engine.hermes_usage = usage
    mine = client.get(f"/workspaces/{ws}/overview").json()
    theirs = client.get(f"/workspaces/{other}/overview").json()
    assert mine["channels"] == []
    assert [c["id"] for c in theirs["channels"]] == [cid]
    assert mine["usage"]["tokens"] == 1000
    assert theirs["usage"]["tokens"] == 999_000
    assert sum(d["tokens"] for d in mine["usage"]["days"]) == 1000
    assert len(mine["usage"]["days"]) == 30


def _kanban_ask(core: Any, ws: str, card: str) -> int:
    """A member working a Kanban card asks for his OK (the guard's ask, AGOS's own
    card: its answer is AGOS's per-card grant)."""
    from agos_core.actions import kanban_asks

    assert kanban_asks.ask(core, ws, card, "", "terminal", "Run commands", "rm -rf old/")
    row = core.db.execute("SELECT MAX(id) FROM kanban_asks").fetchone()
    return int(row[0])


def test_a_card_answered_in_agos_closes_in_telegram(env: Any) -> None:
    """Like Hermes's Allow / Deny: answered in one place, closed in both."""
    client, core, _fake, tg, ws = env
    connect(client)
    ask = _kanban_ask(core, ws, "t_1")
    tick(core)
    cards = [m for m in tg.sent if m.get("reply_markup")]
    assert len(cards) == 1 and str(cards[0]["chat_id"]) == str(OWNER) and tg.edited == []
    assert [b["callback_data"] for b in cards[0]["reply_markup"]["inline_keyboard"][0]] == [
        f"kask:once:{ask}",
        f"kask:deny:{ask}",
    ]
    # He answers in AGOS: the card on the phone shows it, without its buttons.
    r = client.post(f"/workspaces/{ws}/kanban-asks/{ask}", json={"allow": False})
    assert r.status_code == 200, r.text
    tick(core)
    assert [e["text"].rsplit("→ ", 1)[1] for e in tg.edited] == ["Denied."]
    assert all(e["reply_markup"] == {"inline_keyboard": []} for e in tg.edited)
    tick(core)
    assert len(tg.edited) == 1  # closed once


def test_a_card_answered_by_its_button_is_left_to_hermes(env: Any) -> None:
    client, core, _fake, tg, ws = env
    connect(client)
    ask = _kanban_ask(core, ws, "t_2")
    tick(core)
    card = next(m for m in tg.sent if m.get("reply_markup"))
    tg.press(f"kask:once:{ask}", chat=OWNER)
    tg.updates[-1]["callback_query"]["message"]["message_id"] = card["message_id"]
    tick(core)
    assert tg.answered == ["Allowed once: the card goes on."]
    assert tg.edited == []  # the plugin updates its card itself
    # Someone Hermes doesn't let in presses nothing (Hermes's own button check).
    other = _kanban_ask(core, ws, "t_3")
    tg.press(f"kask:once:{other}", chat=OWNER)
    tg.updates[-1]["callback_query"]["from"]["id"] = 999
    tick(core)
    status = core.db.execute("SELECT status FROM kanban_asks WHERE id = ?", (other,))
    assert status.fetchone()[0] == "waiting"


def test_a_card_far_past_its_usual_tokens_asks_the_cofounder_only(
    env: Any, monkeypatch: Any
) -> None:
    """Hermes reports a Kanban card's tokens as they grow: past the workspace's mark
    the owner is told once per level, in the Co-Founder's chat and its Telegram (never
    copied to every group); Let it go on / Stop it work from there."""
    client, core, _fake, tg, ws = env
    cid = connect(client)
    from agos_core.actions import kanban_board, token_watch
    from agos_core.actions.hermes_channel import bridge_key
    from agos_core.actions.services.channel import owner_needs
    from agos_core.actions.workers import create_group

    owner_needs.tell_owner(core, ws, "hello")  # the Co-Founder chat
    cofounder = owner_needs.cofounder_chat(core, ws)
    assert cofounder is not None
    client.post(
        f"/workspaces/{ws}/chats/{cofounder}/addresses",
        json={"connectionId": cid, "address": f"{OWNER}:0"},
    )
    group = create_group(core, ws, "Team", [])
    client.post(
        f"/workspaces/{ws}/chats/{group}/addresses", json={"connectionId": cid, "address": "-100"}
    )
    card = kanban_board.create(core, ws, "Invoices", "D", "")
    board = core.engine.runner.kanban[core.engine.profile(ws)]
    # Hermes keeps the counts and decides (its Kanban's events, tokens.py); here its
    # board database holds what Hermes wrote when it told.
    import json as _json
    import sqlite3 as _sqlite3

    from agos_core.actions import agent_profiles

    home = agent_profiles.board_home(core, ws)
    home.mkdir(parents=True, exist_ok=True)
    hermes_board = _sqlite3.connect(home / "kanban.db")
    hermes_board.execute(
        "CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER)"
    )
    hermes_board.commit()

    def facts(core: Any, workspace: str, ids: list[str]) -> dict[str, dict[str, str]]:
        cards = core.engine.runner.kanban.get(core.engine.profile(workspace), {})
        return {
            c: {"status": cards[c]["status"], "title": cards[c]["title"], "result": ""}
            for c in ids
            if c in cards
        }

    monkeypatch.setattr(kanban_board, "facts", facts)
    tick(core)
    before = len(tg.sent)

    def hermes_told(level: int, tokens: int) -> Any:
        payload = {"level": level, "tokens": tokens, "usual": 1_000_000}
        hermes_board.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?, 7, 'agos_tokens_told', ?, 0)",
            (card, _json.dumps(payload)),
        )
        hermes_board.commit()
        return client.post(
            f"/hermes-bridge/{ws}/card-tokens-told",
            json={"card": card, **payload},
            headers={"authorization": f"Bearer {bridge_key(core, ws)}"},
        )

    assert hermes_told(1, 3_200_000).json() == {"ok": True}
    tick(core)
    tick(core)
    new = [m for m in tg.sent[before:] if card in m["text"]]
    assert [str(m["chat_id"]) for m in new] == [str(OWNER)]  # the Co-Founder's only
    assert "3.7M" not in new[0]["text"] and "3.2M" in new[0]["text"]
    buttons = [b["callback_data"] for b in new[0]["reply_markup"]["inline_keyboard"][0]]
    assert buttons == [f"tok:go:{card}", f"tok:stop:{card}"]
    msgs = [
        str(m["body"])
        for m in core.db.execute("SELECT body FROM messages WHERE chat_id = ?", (group,))
    ]
    assert not any(card in m for m in msgs)
    # Another run of the same card adds up (Hermes): twice the mark is the next level.
    assert hermes_told(2, 6_100_000).json() == {"ok": True}
    # A card another workspace never counted can't be stopped from here.
    assert token_watch.answer(core, "nobody", card, "stop") == "This card isn't this workspace's."
    # In AGOS too: the warning waits under the Co-Founder's chat, answered there or
    # on the phone (then it's gone from both).
    live = client.get(f"/workspaces/{ws}/chats/{cofounder}/live").json()
    assert [(w["card"], w["used"]) for w in live["tokens"]] == [(card, "6.1M")]
    group_live = client.get(f"/workspaces/{ws}/chats/{group}/live").json()
    assert group_live["tokens"] == []
    tg.press(f"tok:stop:{card}", chat=OWNER)
    tick(core)
    assert board[card]["status"] == "blocked"
    live = client.get(f"/workspaces/{ws}/chats/{cofounder}/live").json()
    assert live["tokens"] == []
    r = client.post(f"/workspaces/{ws}/card-tokens/{card}", json={"go": True})
    assert r.json()["message"].startswith("OK, it goes on")
    assert tg.answered[-1].startswith("Stopped.")


def test_a_card_from_before_with_buttons_nothing_answers_is_never_sent(env: Any) -> None:
    client, core, _fake, tg, _ws = env
    cid = connect(client)
    for buttons in ('[["Undo", "act:undo:3"]]', '[["Allow once", "kask:once:4"]]'):
        core.db.execute(
            """INSERT INTO channel_outbox (connection_id, address, body, buttons, source, created_at)
               VALUES (?, ?, 'card', ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (cid, f"{OWNER}:0", buttons, buttons),
        )
    tick(core)
    assert [m["reply_markup"]["inline_keyboard"][0][0]["callback_data"] for m in tg.sent] == [
        "kask:once:4"
    ]


def test_the_bot_token_lives_only_in_the_workspaces_hermes(env: Any) -> None:
    """One copy: the profile's .env (Hermes's own place for it), none in AGOS's
    database; AGOS still checks the bot and makes topics with it."""
    client, core, _fake, _tg, ws = env
    cid = connect(client)
    # The token's one home is Hermes's .env: AGOS keeps no copy, not even its end.
    columns = {r[1] for r in core.db.execute("PRAGMA table_info(channel_connections)")}
    assert not {"secret", "secret_last4"} & columns
    dotenv = (core.engine.profile_home(ws) / ".env").read_text()
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}" in dotenv
    channels.check_one(core, cid)
    assert client.get("/channels").json()[0]["status"] == "connected"
    # A later sync keeps it (its line is rewritten from Hermes's own copy).
    from agos_core.actions import library

    library.apply_workspace(core, ws)
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}" in (core.engine.profile_home(ws) / ".env").read_text()


def test_a_bots_on_off_and_reactions_are_hermess_own_switches(env: Any, monkeypatch: Any) -> None:
    """Off is Hermes's platforms.telegram.enabled (the token stays in .env), the
    reactions Hermes's telegram.reactions; AGOS keeps neither."""
    import yaml

    from agos_core.actions import hermes_channel

    client, core, _fake, _tg, ws = env
    cid = connect(client)
    home = core.engine.profile_home(ws)
    said: list[tuple[str, ...]] = []

    def hermes(workspace_id: str, *args: str, timeout: float = 60) -> str:
        said.append(args)
        if args[:2] == ("config", "set"):  # what Hermes's `config set` writes
            cfg = yaml.safe_load((home / "config.yaml").read_text()) or {}
            node = cfg
            *path, last = args[2].split(".")
            for part in path:
                node = node.setdefault(part, {})
            node[last] = args[3] == "true"
            (home / "config.yaml").write_text(yaml.safe_dump(cfg))
        return ""

    monkeypatch.setattr(core.engine, "_hermes", hermes)
    monkeypatch.setattr(hermes_channel, "restart_gateway", lambda *_: None)
    columns = {r[1] for r in core.db.execute("PRAGMA table_info(channel_connections)")}
    assert "enabled" not in columns
    r = client.put(f"/channels/{cid}", json={"name": "Bot", "enabled": False, "reactions": False})
    assert r.status_code == 204, r.text
    assert ("config", "set", "platforms.telegram.enabled", "false") in said
    assert ("config", "set", "telegram.reactions", "false") in said
    [bot] = client.get("/channels").json()
    assert bot["enabled"] is False and bot["reactions"] is False
    assert hermes_channel.connection(core, ws) is None  # nothing routes to it while off
    from agos_core.actions import library

    library.apply_workspace(core, ws)
    dotenv = (home / ".env").read_text()
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}" in dotenv and "TELEGRAM_REACTIONS" not in dotenv
    client.put(f"/channels/{cid}", json={"name": "Bot", "enabled": True})
    assert client.get("/channels").json()[0]["enabled"] is True
    assert hermes_channel.connection(core, ws) is not None


def test_a_new_bot_restarts_the_running_gateway(env: Any) -> None:
    """Hermes reads TELEGRAM_BOT_TOKEN only when its gateway starts: one already
    running (started before the bot existed) is restarted by the add itself,
    before the bot says "saved" — never left running without its Telegram."""
    client, core, _fake, _tg, ws = env
    moves: list[str] = []
    core.engine.stop = lambda w, **_: moves.append(f"stop {w}")
    core.engine.start = lambda w, **_: moves.append(f"start {w}")
    connect(client)
    assert moves[-2:] == [f"stop {ws}", f"start {ws}"]


def test_a_new_token_restarts_the_gateway_a_name_never(env: Any, monkeypatch: Any) -> None:
    """A pasted token lands in Hermes's .env, read only at the gateway's start:
    saving it restarts the gateway. A rename alone never touches it."""
    from agos_core.actions import hermes_channel

    client, core, _fake, _tg, ws = env
    cid = connect(client)
    restarted: list[str] = []
    monkeypatch.setattr(hermes_channel, "restart_gateway", lambda _c, w, **_: restarted.append(w))
    fresh = TOKEN[:-1] + "B"
    r = client.put(f"/channels/{cid}", json={"name": "Phone", "secret": fresh})
    assert r.status_code == 204, r.text
    lines = (core.engine.profile_home(ws) / ".env").read_text().splitlines()
    assert f"TELEGRAM_BOT_TOKEN={fresh}" in lines
    assert restarted == [ws]
    r = client.put(f"/channels/{cid}", json={"name": "Renamed"})
    assert r.status_code == 204, r.text
    assert restarted == [ws]  # the name is AGOS's own row: no restart for it


def test_the_menus_are_rebuilt_only_when_the_team_or_a_group_changed(
    env: Any, monkeypatch: Any
) -> None:
    """The upkeep loop reads no profile while nothing changed: only a member added
    or gone, a job title, on/off, or a group's members make it rebuild the menus."""
    import os

    client, core, _fake, _tg, ws = env
    connect(client)
    from agos_core.actions import hermes_channel

    rebuilt: list[Any] = []
    real = hermes_channel.sync_member_menus

    def counted(c: Any, only: Any = None) -> Any:
        rebuilt.append(only)
        return real(c, only)

    monkeypatch.setattr(hermes_channel, "sync_member_menus", counted)
    channels.upkeep(core)
    assert rebuilt == [{ws}]
    for _ in range(3):
        channels.upkeep(core)
    assert rebuilt == [{ws}]  # nothing changed: no profile read
    profiles = core.engine.root(ws) / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    os.utime(profiles, ns=(1, 1))  # a member added or gone changes the folder
    channels.upkeep(core)
    assert rebuilt == [{ws}, {ws}]
    channels.upkeep(core)
    assert rebuilt == [{ws}, {ws}]


def test_the_sending_round_runs_no_hermes_process(env: Any, monkeypatch: Any) -> None:
    """Replies go out from a round of database work only: a Hermes command (which
    can wait while Hermes prepares a new root) runs in the upkeep loop, never in it."""
    client, core, _fake, _tg, _ws = env
    connect(client)
    ran: list[Any] = []
    real = core.engine.runner.run

    def run(args: Any, **k: Any) -> Any:
        ran.append(list(args)[:4])
        return real(args, **k)

    monkeypatch.setattr(core.engine.runner, "run", run)
    from agos_core.actions import hermes_channel

    upkept: list[str] = []
    for name in ("sync_member_menus",):
        real_fn = getattr(hermes_channel, name)

        def counted(c: Any, only: Any = None, _n: str = name, _f: Any = real_fn) -> Any:
            upkept.append(_n)
            return _f(c, only)

        monkeypatch.setattr(hermes_channel, name, counted)
    channels.send_round.real(core)  # type: ignore[attr-defined]
    assert ran == [] and upkept == []
    channels.upkeep(core)  # the members' menus: where Hermes commands may run
    assert upkept == ["sync_member_menus"]


def test_one_bot_token_is_never_two_workspaces_bots(env: Any) -> None:
    """Each root's gateway now keeps its locks in its own folder (Hermes's
    HERMES_GATEWAY_LOCK_DIR), so Hermes's machine-wide token lock no longer sees
    another workspace using the same bot: AGOS refuses that token itself."""
    from agos_core.actions import hermes_channel
    from agos_core.actions.errors import ActionError

    client, core, _fake, _tg, ws = env
    connect(client)
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    with pytest.raises(ActionError) as refused:
        hermes_channel.write_token(core, other, TOKEN)
    assert refused.value.status == 409 and "Argan" in refused.value.message
    assert TOKEN not in (core.engine.profile_home(other) / ".env").read_text()
    r = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": [str(OWNER)], "workspaceId": other},
    )
    assert r.status_code == 409, r.text
    hermes_channel.write_token(core, ws, TOKEN)  # its own bot again: fine
