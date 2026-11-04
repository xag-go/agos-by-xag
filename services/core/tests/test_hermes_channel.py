"""A Telegram bot on the workspace's own Hermes gateway (actions/hermes_channel.py):
Hermes receives and answers, AGOS keeps the same conversation in the chat.

The helpers are tests/hermes_channel_rig.py; voice notes and commands are
test_hermes_channel_commands.py, team-group topics test_hermes_channel_topics.py,
cron jobs, tokens and cards test_hermes_channel_cards.py, the agos-guard plugin's
turn handling test_hermes_channel_plugin.py.
"""

import json
import time
from typing import Any

from channels_rig import OWNER, TOKEN
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram
from hermes_channel_rig import _bridge, _hermes_bot

from agos_core.actions import channels, hermes_channel
from agos_core.actions import chat as chat_actions
from agos_core.db import chats as chats_repo
from agos_core.db import hermes_chats as hc
from agos_core.engine import identity


def test_hermes_runs_the_bot_and_agos_keeps_the_conversation(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    home = core.engine.profile_home(ws)
    lines = (home / ".env").read_text().splitlines()
    assert f"TELEGRAM_BOT_TOKEN={TOKEN}" in lines
    assert f"TELEGRAM_ALLOWED_USERS={OWNER}" in lines
    assert (home / hermes_channel.BRIDGE_FILE).stat().st_mode & 0o777 == 0o600

    # Wrong key: refused.
    bad = _bridge(
        client, ws, "x" * 64, "incoming", {"chat": str(OWNER), "sender": str(OWNER), "text": "hi"}
    )
    assert bad.status_code == 401

    # His message joins the Co-Founder chat, and the chat shows an answer working.
    got = _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "Hi cofounder", "messageId": "9"},
    ).json()
    assert got == {"handled": False}
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s1"}).json()
    # How it works is in its SOUL.md (Hermes reads it): AGOS adds nothing to the turn.
    assert start["turnId"] and "context" not in start
    soul = (home / "SOUL.md").read_text()
    assert identity.RULES in soul and identity.cofounder_view(soul)
    chat_id = start["chatId"]
    turn = core.db.execute("SELECT * FROM chat_turns WHERE id = ?", (start["turnId"],)).fetchone()
    assert turn["via"] == "hermes" and turn["status"] == "running"
    # AGOS never runs its own answer for it meanwhile.
    assert chats_repo.unanswered(core.db, chat_id) == []

    # A second message while it works goes into the same answer.
    _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "and also this"},
    )
    again = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s1"}).json()
    assert again["turnId"] == start["turnId"]

    # The answer ends: AGOS stores it, and Hermes (not AGOS) sends it, unchanged.
    done = _bridge(
        client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Hello! Done."}
    ).json()
    assert done == {"text": "Hello! Done."}
    msgs = client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]
    assert [m["body"] for m in msgs][-3:] == ["Hi cofounder", "and also this", "Hello! Done."]
    channels.send_round(core)
    sent = core.db.execute(
        "SELECT count(*) FROM channel_outbox WHERE body = 'Hello! Done.'"
    ).fetchone()[0]
    assert sent == 0

    # The workspace changes while the conversation goes on: SOUL.md follows (the
    # next conversation reads it); nothing is added to the turn.
    from agos_core.actions import cofounder_actions

    cofounder_actions.set_mode(core, "ask")
    _bridge(client, ws, key, "incoming", {"chat": str(OWNER), "sender": str(OWNER), "text": "next"})
    told = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s1"}).json()
    assert told["turnId"] != start["turnId"] and "context" not in told
    # Rebuilt after the answer started (Hermes built this turn's prompt before it asked).
    for _ in range(500):
        if not hermes_channel._views:
            break
        time.sleep(0.01)
    assert "says yes first" in identity.cofounder_view((home / "SOUL.md").read_text())
    _bridge(client, ws, key, "turn-finish", {"turnId": told["turnId"], "text": "ok"})


def test_what_he_writes_in_agos_goes_into_the_same_conversation(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    # The bot's chat becomes the Co-Founder chat with his first message there.
    _bridge(
        client, ws, key, "incoming", {"chat": str(OWNER), "sender": str(OWNER), "text": "hello"}
    )
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Hi!"})
    chat_id = start["chatId"]

    shown = chat_actions.post_message(core, ws, chat_id, "from AGOS")
    item = shown - hc.PENDING_BASE  # his message waits in the queue until Hermes has it
    # The answer it starts is Hermes's (in the Telegram conversation), not an AGOS run.
    live = chats_repo.live_turn(core.db, chat_id)
    assert live is not None and live.via == "hermes" and live.hermes_run_id is None
    msgs = client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]
    assert (msgs[-1]["id"], msgs[-1]["body"]) == (shown, "from AGOS")
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [i["text"] for i in items] == ["from AGOS"] and items[0]["chat"] == f"{OWNER}:0"
    # Telegram shows his words too, marked as written in AGOS.
    mirror = core.db.execute(
        "SELECT body FROM channel_outbox WHERE source = ?", (f"mirror:p{item}",)
    ).fetchone()
    assert mirror["body"] == f"{hermes_channel.MIRROR_MARK}\nfrom AGOS"
    assert _bridge(client, ws, key, "done", {"id": items[0]["id"], "ok": True}).json()["ok"]
    done = core.db.execute("SELECT done_at FROM hermes_inbox WHERE id = ?", (items[0]["id"],))
    assert done.fetchone()["done_at"]


def test_approvals_show_in_both_and_close_in_both(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "clean the folder"},
    )
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    chat_id, turn_id = start["chatId"], start["turnId"]
    _bridge(
        client,
        ws,
        key,
        "approval",
        {"chat": str(OWNER), "command": "rm -rf old/", "description": "delete files"},
    )
    live = chat_actions._registry(core)[turn_id].turn
    waiting = [a for a in live.activity if a.kind == "approval" and a.status == "waiting"]
    assert waiting and "rm -rf old/" in waiting[0].detail
    # The answer as it is written shows live in AGOS.
    _bridge(
        client,
        ws,
        key,
        "events",
        {
            "turnId": turn_id,
            "events": [
                {"event": "tool.started", "tool": "terminal", "preview": "ls"},
                {"event": "message.delta", "delta": "Cleaning"},
                {"event": "run.completed"},  # not Hermes's to end it this way: ignored
            ],
        },
    )
    assert live.text == "Cleaning" and live.status != "completed"
    assert any(a.kind == "tool" and a.status == "running" for a in live.activity)
    # He answers in AGOS: Hermes gets it through its inbox.
    assert (
        client.post(
            f"/workspaces/{ws}/chats/{chat_id}/approval", json={"choice": "deny"}
        ).status_code
        == 204
    )
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [(i["kind"], i["text"]) for i in items] == [("approval", "deny")]
    # Hermes reports it answered: the card closes in AGOS.
    _bridge(client, ws, key, "approval-done", {"chat": str(OWNER), "choice": "deny"})
    assert [a.status for a in live.activity if a.kind == "approval"] == ["failed"]


def test_task_is_hermes_and_buttons_stay_with_agos(env: Any) -> None:
    """/task is Hermes's skill command (AGOS's shared `task` skill): it reaches the
    Co-Founder's Hermes, which makes the card with its own kanban_create."""
    from agos_core.actions import agos_skills

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    got = _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "/task Check the invoices"},
    ).json()
    assert got == {"handled": False}
    assert hermes_channel.is_hermes_command("/task Check the invoices")
    skill = (agos_skills.skills_dir(core) / "task" / "SKILL.md").read_text()
    assert "name: task" in skill and "kanban_create" in skill
    config = core.engine.runner.config.get(core.engine.profile(ws), {})
    assert str(agos_skills.skills_dir(core)) in json.loads(config["skills.external_dirs"])
    # An AGOS button pressed in Telegram reaches AGOS's own handling.
    pressed = _bridge(
        client,
        ws,
        key,
        "callback",
        {"chat": str(OWNER), "sender": str(OWNER), "data": "tok:go:t_gone", "callbackId": "c1"},
    ).json()
    assert pressed["outcome"] == "ignored: card gone"


def test_a_new_workspace_bot_runs_on_hermes(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    cid = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": [str(OWNER)], "workspaceId": ws},
    ).json()["id"]
    row = core.db.execute("SELECT engine FROM channel_connections WHERE id = ?", (cid,))
    assert row.fetchone()["engine"] == "hermes"


def test_the_bot_lamp_follows_hermes_and_agos_never_starts_the_gateway(
    env: Any,
) -> None:
    """Hermes's service keeps the gateway up; AGOS only reads the bot's state."""
    client, core, _fake, _tg, ws = env
    _hermes_bot(client, core, ws)
    started: list[str] = []
    core.engine.is_running = lambda workspace_id: False
    core.engine.start = lambda workspace_id, **_: started.append(workspace_id)
    from agos_core.actions import channels

    channels.tick(core)
    assert client.get("/channels").json()[0]["status"] == "connecting"  # no Hermes state yet
    (core.engine.profile_home(ws) / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": __import__("os").getpid(),
                "gateway_state": "running",
                "platforms": {
                    "telegram": {"state": "connected", "updated_at": "2026-10-16T09:00:00+00:00"}
                },
            }
        )
    )
    shown = client.get("/channels").json()[0]
    assert shown["status"] == "connected" and shown["lastOkAt"] == "2026-10-16T09:00:00.000Z"
    (core.engine.profile_home(ws) / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": __import__("os").getpid(),
                "gateway_state": "running",
                "platforms": {"telegram": {"state": "fatal", "error_message": "Unauthorized"}},
            }
        )
    )
    shown = client.get("/channels").json()[0]
    assert (shown["status"], shown["statusReason"]) == ("error", "Unauthorized")
    assert started == []


def test_groups_and_topics_run_on_hermes_too(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Ideas"}).json()["id"]
    r = client.post(
        f"/workspaces/{ws}/chats/{chat_id}/addresses",
        json={"connectionId": _cid, "address": "-1001:7"},
    )
    assert r.status_code in (200, 201), r.text
    topic = {"chat": "-1001:7", "sender": str(OWNER)}
    # The linked topic is its own conversation, kept in its AGOS chat.
    got = _bridge(client, ws, key, "incoming", topic | {"text": "idea in the topic"}).json()
    assert got == {"handled": False}
    start = _bridge(client, ws, key, "turn-start", {"chat": "-1001:7", "sessionId": "g"}).json()
    assert start["chatId"] == chat_id
    msgs = client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]
    assert [m["body"] for m in msgs] == ["idea in the topic"]
    # What he writes in that AGOS chat goes to that topic.
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "ok"})
    chat_actions.post_message(core, ws, chat_id, "from AGOS")
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert items and items[-1]["chat"] == "-1001:7" and items[-1]["text"] == "from AGOS"
    # A group or topic no AGOS chat is linked to: the bot stays quiet there.
    other = {"chat": "-1002", "sender": str(OWNER), "text": "hello?"}
    assert _bridge(client, ws, key, "incoming", other).json() == {"handled": True}


def test_strangers_never_reach_agos(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    got = _bridge(
        client, ws, key, "incoming", {"chat": "999", "sender": "999", "text": "let me in"}
    ).json()
    assert got == {"handled": True}
    assert core.db.execute("SELECT count(*) FROM chat_addresses").fetchone()[0] == 0


def test_who_may_write_is_hermess_own_list(env: Any) -> None:
    """The bot's people are Hermes's: its allowlist (from the bot's setup, through
    `hermes config set`) and pairing. AGOS writes no allowlist of its own into the
    profile, and a profile sync never takes Hermes's away."""
    client, core, _fake, _tg, ws = env
    cid = client.post(
        "/channels", json={"kind": "telegram", "secret": TOKEN, "allowed": [], "workspaceId": ws}
    ).json()["id"]
    row = core.db.execute("SELECT engine FROM channel_connections WHERE id = ?", (cid,))
    assert row.fetchone()["engine"] == "hermes"  # on Hermes from the start
    assert "TELEGRAM_ALLOWED_USERS" not in hermes_channel.profile_env(core, ws)
    key = hermes_channel.bridge_key(core, ws)
    # A stranger's message: never reaches AGOS (Hermes answers him with its code).
    assert _bridge(
        client, ws, key, "incoming", {"chat": "42", "sender": "42", "text": "/start x"}
    ).json() == {"handled": True}
    # Hermes's allowlist changed by Hermes (a pairing approval mirrors into it).
    core.engine._hermes(ws, "config", "set", "TELEGRAM_ALLOWED_USERS", str(OWNER))
    from agos_core.actions import library

    library.apply_workspace(core, ws)
    lines = (core.engine.profile_home(ws) / ".env").read_text().splitlines()
    assert f"TELEGRAM_ALLOWED_USERS={OWNER}" in lines and f"TELEGRAM_BOT_TOKEN={TOKEN}" in lines
    assert client.get("/channels").json()[0]["allowed"] == [str(OWNER)]
