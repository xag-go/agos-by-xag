"""Voice notes, Hermes's own commands (from Telegram or AGOS), retry and undo,
and AGOS chats as Hermes conversations, on the workspace's Hermes gateway."""

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
from agos_core.actions import chat as chat_actions
from agos_core.db import chats as chats_repo


def test_voice_notes_and_hermes_commands_show_what_hermes_read(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"chat": str(OWNER), "sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"text": "🎤 Voice note"})
    start = _bridge(
        client,
        ws,
        key,
        "turn-start",
        {"chat": str(OWNER), "sessionId": "v", "said": '"chno kayn f board"', "how": "replace"},
    ).json()
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Walo."})
    # A /command Hermes turned into a request: AGOS gets what Hermes read.
    again = _bridge(
        client,
        ws,
        key,
        "turn-start",
        {"chat": str(OWNER), "sessionId": "v", "said": "Use the brief skill", "how": "store"},
    ).json()
    _bridge(client, ws, key, "turn-finish", {"turnId": again["turnId"], "text": "Done."})
    msgs = client.get(f"/workspaces/{ws}/chats/{start['chatId']}").json()["messages"]
    assert [m["body"] for m in msgs] == [
        "🎤 chno kayn f board",
        "Walo.",
        "Use the brief skill",
        "Done.",
    ]


def test_a_voice_note_from_agos_reaches_hermes_as_a_file(env: Any, monkeypatch: Any) -> None:
    """A Telegram conversation: his voice note from AGOS goes to Hermes as a file
    (Hermes's own speech-to-text hears it, as on Telegram), never as AGOS's words."""
    import base64
    import inspect

    from agos_core.engine import attachments as files

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    _bridge(client, ws, key, "incoming", {"chat": str(OWNER), "sender": str(OWNER), "text": "hi"})
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "s"}).json()
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Hi!"})
    chat_id = start["chatId"]

    def never(*_: Any, **__: Any) -> str:
        raise AssertionError("AGOS transcribed it")

    monkeypatch.setattr(files, "transcribe", never)
    audio = base64.b64encode(b"OggS" + b"0" * 64).decode()
    r = client.post(
        f"/workspaces/{ws}/chats/{chat_id}/messages",
        json={
            "body": "listen",
            "attachments": [
                {"kind": "audio", "name": "v.webm", "mime": "audio/webm", "data": audio}
            ],
        },
    )
    assert r.status_code == 201, r.text
    for _ in range(50):
        items = _bridge(client, ws, key, "next", {}).json()["items"]
        if items:
            break
        time.sleep(0.1)
    assert items and items[-1]["text"] == "listen"  # held for nothing, words untouched
    media = items[-1]["media"]
    assert [(m["kind"], m["mime"]) for m in media] == [("audio", "audio/webm")]
    assert media[0]["path"].endswith("v.webm") and items[-1]["createdAt"]
    # Guard: no AGOS speech-to-text or text injection for a Telegram conversation.
    assert "_transcribe" not in inspect.getsource(chat_actions.send)
    assert not hasattr(chat_actions, "HELD")
    from agos_core.hermes_plugin.agos_guard import bridge

    assert "inject_message(" not in inspect.getsource(bridge._poll_once)


def test_hermes_commands_from_either_side(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"chat": str(OWNER), "sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"text": "hi"})
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "c"}).json()
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Hi!"})
    chat_id = start["chatId"]
    # Typed in Telegram: the command and Hermes's own answer show in AGOS, and AGOS
    # never waits for an agent's answer to it.
    assert _bridge(client, ws, key, "command", me | {"text": "/status"}).json() == {"shown": True}
    assert chats_repo.live_turn(core.db, chat_id) is None
    assert not chat_actions.pending(core, chat_id)
    _bridge(client, ws, key, "command-reply", {"chat": str(OWNER), "text": "Model: opus"})
    channels.send_round(core)
    msgs = client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]
    assert [m["body"] for m in msgs][-2:] == ["/status", "Model: opus"]
    outbox = core.db.execute("SELECT body FROM channel_outbox WHERE sent_id != 'skipped'")
    assert "Model: opus" not in [r["body"] for r in outbox]  # Hermes already sent it
    # Typed in AGOS: Hermes runs it (handed over as a command), nothing left waiting.
    chat_actions.post_message(core, ws, chat_id, "/usage")
    assert chats_repo.live_turn(core.db, chat_id) is None
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [(i["kind"], i["text"]) for i in items] == [("command", "/usage")]
    # Hermes's menu, for AGOS's "/" list: read from Hermes's own registry each time
    # (what its Telegram shows); AGOS keeps no copy, and what an older plugin still
    # sends is ignored.
    asked: list[str] = []

    def hermes_menu(workspace_id: str) -> list[dict[str, str]]:
        asked.append(workspace_id)
        return [
            {"command": "status", "description": "Show status"},
            {"command": "BAD!", "description": ""},
        ]

    core.engine.command_menu = hermes_menu
    menu = {"commands": [{"command": "stale", "description": "Old copy"}], "bot": "agos_bot"}
    _bridge(client, ws, key, "commands", menu)
    assert client.get(f"/workspaces/{ws}/chats/{chat_id}/hermes-commands").json() == [
        {"command": "status", "description": "Show status"}
    ]
    assert asked == [ws]
    assert (
        core.db.execute("SELECT 1 FROM app_settings WHERE key LIKE 'hermes.commands.%'").fetchone()
        is None
    )
    # Hermes can't be asked: an empty list, never an old copy.
    core.engine.command_menu = lambda _ws: (_ for _ in ()).throw(RuntimeError("down"))
    assert client.get(f"/workspaces/{ws}/chats/{chat_id}/hermes-commands").json() == []


def test_retry_and_undo_in_a_telegram_chat_are_hermess_own(env: Any) -> None:
    """A chat that lives in Telegram: Retry / Undo from AGOS are Hermes's own /retry
    and /undo there (the command hand-over into its Telegram conversation), never
    AGOS re-sending his text; Telegram shows what was done from AGOS."""
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"chat": str(OWNER), "sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"text": "hi"})
    start = _bridge(client, ws, key, "turn-start", {"chat": str(OWNER), "sessionId": "c"}).json()
    chat_id = start["chatId"]
    with core.db:
        assert hermes_channel.own_command(core, ws, chat_id, "/retry")
        assert hermes_channel.own_command(core, ws, chat_id, "/undo")
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [(i["kind"], i["text"]) for i in items] == [
        ("command", "/retry"),
        ("command", "/undo"),
        ("command", "/approve"),  # he already said yes in AGOS
    ]
    assert all(i["chat"] == str(OWNER) or str(OWNER) in str(i["chat"]) for i in items)
    shown = [
        r["body"]
        for r in core.db.execute("SELECT body FROM channel_outbox WHERE source LIKE 'mirror:own:%'")
    ]
    assert shown == [
        f"{hermes_channel.MIRROR_MARK}\n/retry",
        f"{hermes_channel.MIRROR_MARK}\n/undo",
    ]


def test_agos_chats_are_hermes_conversations(env: Any, monkeypatch: Any) -> None:
    """The agos platform: each AGOS chat is a conversation of the workspace's Hermes."""
    import base64

    client, core, _fake, _tg, ws = env
    key = hermes_channel.bridge_key(core, ws)
    env_lines = (core.engine.profile_home(ws) / ".env").read_text().splitlines()
    assert "AGOS_PLATFORM_ENABLED=true" in env_lines
    assert (core.engine.profile_home(ws) / hermes_channel.BRIDGE_FILE).exists()
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Ideas"}).json()["id"]
    audio = base64.b64encode(b"OggS" + b"0" * 64).decode()
    r = client.post(
        f"/workspaces/{ws}/chats/{chat_id}/messages",
        json={
            "body": "listen",
            "attachments": [
                {"kind": "audio", "name": "v.webm", "mime": "audio/webm", "data": audio}
            ],
        },
    )
    assert r.status_code == 201, r.text
    address = f"agos:{chat_id}"
    items: list[Any] = []
    control: list[Any] = []
    for _ in range(50):
        got = _bridge(client, ws, key, "platform-next", {}).json()["items"]
        # AGOS's control conversation (Hermes's /reload-mcp after the setup): not a chat.
        control += [i for i in got if i["chat"] == "agos:0"]
        items += [i for i in got if i["chat"] != "agos:0"]
        if items:
            break
        time.sleep(0.1)
    assert all(i["kind"] == "command" for i in control)
    # The chat's name first, as Hermes's own /title for its session (it follows the
    # workspace's model: no /model of its own).
    assert (items[0]["kind"], items[0]["text"]) == ("command", "/title Ideas")
    items = items[1:]
    assert items and items[0]["chat"] == address and items[0]["text"] == "listen"
    assert items[0]["media"][0]["mime"] == "audio/webm"
    assert items[0]["session"] == ""  # a new chat: Hermes starts its own session
    assert items[0]["topic"] == "Ideas"  # the chat's name: the conversation's topic in Hermes
    assert hermes_channel.take_inbox(core, ws) == []  # not Telegram's
    # Hermes answers it there: the same turn, the same finish as in Telegram.
    start = _bridge(client, ws, key, "turn-start", {"chat": address, "sessionId": "p"}).json()
    assert start["chatId"] == chat_id and "context" not in start  # SOUL.md has it all
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Heard you."})
    # Hermes sends it through the platform too: kept once.
    _bridge(client, ws, key, "platform-send", {"chat": address, "text": "Heard you."})
    _bridge(client, ws, key, "platform-send", {"chat": address, "text": "⏳ Queued."})
    msgs = client.get(f"/workspaces/{ws}/chats/{chat_id}").json()["messages"]
    assert [m["body"] for m in msgs] == ["listen", "Heard you.", "⏳ Queued."]
    # A /command typed in AGOS goes to Hermes as a command; nothing waits for it.
    chat_actions.post_message(core, ws, chat_id, "/status")
    assert chats_repo.live_turn(core.db, chat_id) is None
    got = _bridge(client, ws, key, "platform-next", {}).json()["items"]
    assert [(i["kind"], i["text"]) for i in got] == [("command", "/status")]
