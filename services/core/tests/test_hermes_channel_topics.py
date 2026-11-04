"""Team-group topics on the workspace's Hermes gateway: a topic per chat, a member's
routed topic, where cards go, the places he wrote in, group members as commands."""

import json
from typing import Any

import hermes_store
from channels_rig import OWNER
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram
from fake_gateway import ask_me_first
from hermes_channel_rig import (
    _bridge,
    _hermes_bot,
    _member_topic,
)

from agos_core.actions import agent_profiles, channels, hermes_channel
from agos_core.actions import chat as chat_actions
from agos_core.db import chats as chats_repo


def test_each_chat_gets_its_topic_in_the_team_group(env: Any) -> None:
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"sender": str(OWNER)}
    # He adds the bot to a group and writes there: AGOS offers it as the team group.
    got = _bridge(
        client, ws, key, "incoming", me | {"chat": "-1000009", "text": "hi", "chatName": "Team"}
    ).json()
    assert got == {"handled": True}
    assert client.get(f"/workspaces/{ws}/telegram-groups").json() == {
        "groups": [{"id": "-1000009", "name": "Team"}],
        "teamGroup": "",
    }
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Scouter"}).json()["id"]
    url = f"/workspaces/{ws}/chats/{chat_id}/telegram-topic"
    assert client.post(url).status_code == 400  # no team group yet
    assert (
        client.put(f"/workspaces/{ws}/telegram-group", json={"group": "-1000009"}).status_code
        == 204
    )
    assert client.post(url).status_code == 201, client.post(url).text
    where = hermes_channel.chat_on_hermes(core, chat_id)
    assert where is not None and where["address"] == "-1000009:41"
    # Its topic is its Hermes conversation.
    topic = me | {"chat": "-1000009:41", "text": "find 3 topics"}
    assert _bridge(client, ws, key, "incoming", topic).json() == {"handled": False}
    start = _bridge(client, ws, key, "turn-start", {"chat": "-1000009:41", "sessionId": "t"}).json()
    assert start["chatId"] == chat_id
    # An AGOS group chat in its topic: its Hermes room answers, the bot stays quiet.
    group = client.post(f"/workspaces/{ws}/chats", json={"title": "Team"}).json()["id"]
    core.db.execute("UPDATE chats SET kind = 'group' WHERE id = ?", (group,))
    assert client.post(f"/workspaces/{ws}/chats/{group}/telegram-topic").status_code == 201
    # A group is a Hermes room (ADR 0020); its topic only carries what is said.
    where = hermes_channel.chat_on_hermes(core, group)
    assert where is not None and where["address"] == f"agos:{group}"
    said = _bridge(
        client, ws, key, "incoming", me | {"chat": "-1000009:42", "text": "plan it"}
    ).json()
    assert said == {"handled": True}
    msgs = client.get(f"/workspaces/{ws}/chats/{group}").json()["messages"]
    assert msgs[0]["body"] == "plan it"  # then the group's Hermes room takes it


def test_a_members_topic_is_hermess_routed_conversation(env: Any, monkeypatch: Any) -> None:
    """A member's DM linked to its own topic is Hermes's own conversation there:
    Hermes routes the topic to the member's profile (gateway.profile_routes in the
    root's config, written with Hermes's `config set`), the member answers in the
    topic itself, AGOS relays nothing, and the web chat and Telegram are one
    session (what he writes in AGOS goes into the topic's conversation)."""
    from agos_core.actions import member_topics
    from agos_core.engine import config_file

    client, core, _fake, _tg, ws = env
    ask_me_first(core, ws)
    _cid, key = _hermes_bot(client, core, ws)
    restarts: list[str] = []
    monkeypatch.setattr(core.engine, "stop", lambda w, **_: restarts.append(f"stop {w}"))
    monkeypatch.setattr(core.engine, "start", lambda w, **_: restarts.append(f"start {w}"))
    dm, topic = _member_topic(client, core, ws, key, monkeypatch)
    chat, _, thread = topic.partition(":")
    # The root's own Hermes config routes the topic to the member's profile, and its
    # gateway restarted to read it (Hermes loads its routes once, at start).
    routes = config_file.get(
        config_file.read(core.engine.profile_home(ws)), "gateway.profile_routes"
    )
    assert routes == [
        {
            "name": f"agos-topic-{chat}-{thread}",
            "platform": "telegram",
            "chat_id": chat,
            "profile": "a-script-writer",
            "thread_id": thread,
        }
    ]
    assert restarts == [f"stop {ws}", f"start {ws}"]
    assert member_topics.sync(core, ws) is False  # safe to repeat: no second restart
    assert len(restarts) == 2
    # The member's own profile never carries the routes (the root's gateway owns them).
    member_home = core.engine.profile_home(agent_profiles.key(ws, "script-writer"))
    assert config_file.get(config_file.read(member_home), "gateway.profile_routes") is None
    # Its conversation is the topic's (Hermes's), from AGOS too.
    where = hermes_channel.chat_on_hermes(core, dm)
    assert where is not None and where["address"] == topic
    me = {"sender": str(OWNER)}
    said = _bridge(
        client,
        ws,
        key,
        "incoming",
        me | {"chat": topic, "text": "write the hook", "messageId": "7"},
    ).json()
    assert said == {"handled": False}  # Hermes answers it (the member's profile)
    assert hermes_channel.take_inbox(core, ws, agos=True, member="script-writer") == []
    start = _bridge(client, ws, key, "turn-start", {"chat": topic, "sessionId": "m"}).json()
    assert start["agent"] == "script-writer" and start["chatId"] == dm
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Here's the hook"})
    channels.queue_replies(core)
    out = core.db.execute(
        "SELECT count(*) FROM channel_outbox WHERE sent_id IS NULL AND address = ?", (topic,)
    ).fetchone()[0]
    assert out == 0  # Hermes sent the member's answer in the topic itself
    # The web chat shows the member's own Telegram session (its profile's state.db).
    shown = client.get(f"/workspaces/{ws}/chats/{dm}").json()["messages"]
    assert [(m["from"], m["body"]) for m in shown] == [
        ("owner", "write the hook"),
        ("agent", "Here's the hook"),
    ]
    sources = (
        hermes_store._db(member_home)
        .execute("SELECT DISTINCT source, chat_id, thread_id FROM sessions")
        .fetchall()
    )
    assert [tuple(r) for r in sources] == [("telegram", chat, thread)]
    # What he writes in AGOS goes into the same conversation: the topic's.
    chat_actions.post_message(core, ws, dm, "and a title")
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [(i["chat"], i["kind"], i["text"]) for i in items] == [(topic, "message", "and a title")]
    # Hermes's own commands typed in the topic are Hermes's (the member's session).
    took = _bridge(
        client, ws, key, "member-command", me | {"chat": topic, "text": "/new", "messageId": "8"}
    ).json()
    assert took == {"handled": False}
    # A voice note there is Hermes's too (its own STT in the member's profile).
    voice = me | {"chat": topic, "text": "🎤 Voice note", "media": [{"path": "/x.ogg"}]}
    assert _bridge(client, ws, key, "incoming", voice).json() == {"handled": False}
    assert not hermes_channel.keeps_eyes(core, ws, topic, "7")
    # Unlinked: the route goes (the owner's own routes stay), the gateway restarts.
    member_topics.write_routes  # noqa: B018 - named for the reader
    core.engine.set_setting(
        ws,
        "gateway.profile_routes",
        json.dumps(
            [*routes, {"name": "mine", "platform": "telegram", "chat_id": "1", "profile": "x"}]
        ),
    )
    address_id = core.db.execute(
        "SELECT id FROM chat_addresses WHERE chat_id = ?", (dm,)
    ).fetchone()
    r = client.delete(f"/workspaces/{ws}/chats/{dm}/addresses/{address_id['id']}")
    assert r.status_code == 204, r.text
    left = config_file.get(config_file.read(core.engine.profile_home(ws)), "gateway.profile_routes")
    assert left == [{"name": "mine", "platform": "telegram", "chat_id": "1", "profile": "x"}]
    assert restarts[-2:] == [f"stop {ws}", f"start {ws}"]


def test_a_members_topic_continues_its_conversation_from_before(env: Any, monkeypatch: Any) -> None:
    """The live move: a member's DM already linked to a topic talked on the agos
    platform before (its session in the member's profile). Once Hermes routes the
    topic, that session goes on there: one "bind" item for the plugin (Hermes's own
    SessionStore.switch_session), queued once, never again once the topic has its
    own conversation. The old relay's start mark goes."""
    from agos_core.actions import member_topics
    from agos_core.db.app_settings import get_setting, set_setting

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    monkeypatch.setattr(member_topics, "follow", lambda c, w: None)  # links from before
    dm, topic = _member_topic(client, core, ws, key, monkeypatch)
    monkeypatch.setattr(member_topics, "follow", lambda c, w: None)
    member_home = core.engine.profile_home(agent_profiles.key(ws, "script-writer"))
    old = hermes_store.session(member_home, "agos", str(dm))
    hermes_store.say(member_home, str(dm), "user", "the hook, please")
    hermes_store.say(member_home, str(dm), "assistant", "Here it is")
    set_setting(core.db, member_topics.OLD_RELAY_MARK, "2026-10-01T00:00:00.000Z")
    core.engine.set_setting(ws, "gateway.profile_routes", "[]")  # AGOS's relay of before
    assert member_topics.sync_all(core) == 1
    assert get_setting(core.db, member_topics.OLD_RELAY_MARK, None) is None
    items = _bridge(client, ws, key, "next", {}).json()["items"]
    assert [(i["chat"], i["kind"]) for i in items] == [(topic, "bind")]
    assert json.loads(items[0]["text"]) == {"session": old, "profile": "a-script-writer"}
    assert member_topics.sync_all(core) == 0  # safe to repeat: one item, waiting
    assert (
        core.db.execute("SELECT count(*) FROM hermes_inbox WHERE kind = 'bind'").fetchone()[0] == 1
    )
    _bridge(client, ws, key, "done", {"id": items[0]["id"], "ok": True})
    # Hermes bound it: the topic's key goes on in that session (its Telegram row).
    chat, _, thread = topic.partition(":")
    hermes_store.session(member_home, "telegram", chat, thread)
    assert member_topics.queue_binds(core, ws) == 0
    # The web chat still shows the conversation from before.
    shown = client.get(f"/workspaces/{ws}/chats/{dm}").json()["messages"]
    assert [m["body"] for m in shown] == ["the hook, please", "Here it is"]


def test_a_card_goes_only_where_the_agent_works(env: Any) -> None:
    """An approval asked in an AGOS chat shows there, and on the phone as Hermes's
    own Telegram card in that chat's own Telegram place only; a chat with no
    Telegram place has it in the Co-Founder's (here the bot chat). AGOS queues no card
    of its own: the plugin has Hermes's Telegram adapter show it where AGOS says."""
    client, core, _fake, tg, ws = env
    cid, key = _hermes_bot(client, core, ws)
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Scout"}).json()["id"]
    address = f"agos:{chat_id}"
    chats_repo.add_chat_message(core.db, ws, chat_id, "owner", "clean it")
    start = _bridge(client, ws, key, "turn-start", {"chat": address, "sessionId": "a"}).json()
    ask = {"chat": address, "command": "rm -rf old/", "description": "delete files"}
    first = _bridge(client, ws, key, "approval", ask).json()
    assert first["phone"] == {"chat": str(OWNER), "thread": ""}  # the Co-Founder's place
    _bridge(client, ws, key, "approval-done", {"chat": address, "choice": "deny"})
    # Linked to a topic of the team group: the card goes there, only.
    core.db.execute(
        """INSERT INTO chat_addresses (chat_id, connection_id, address, notify, created_at)
           VALUES (?, ?, '-1000009:42', 0, 'now')""",
        (chat_id, cid),
    )
    again = _bridge(client, ws, key, "approval", ask | {"command": "rm -rf new/"}).json()
    assert again["phone"] == {"chat": "-1000009", "thread": "42"}
    channels.tick(core)
    assert tg.sent == []  # nothing of AGOS's own
    # Answered in AGOS: Hermes gets it (the plugin then closes Hermes's own card).
    r = client.post(f"/workspaces/{ws}/chats/{chat_id}/approval", json={"choice": "deny"})
    assert r.status_code == 204
    got = _bridge(client, ws, key, "next", {}).json()["items"]
    assert ("approval", "deny") in [(i["kind"], i["text"]) for i in got], got
    _bridge(client, ws, key, "approval-done", {"chat": address, "choice": "deny"})
    # He turned these off: no card on the phone.
    r = client.put("/preferences/notifications", json={"rules": {"task.waiting": "silent"}})
    assert r.status_code == 204
    quiet = _bridge(client, ws, key, "approval", ask | {"command": "rm -rf x/"}).json()
    assert quiet["phone"] is None
    # His Daily digest: no card now; one line about it in the next morning's digest.
    # The clock and the delivery are Hermes's: a no-agent cron job in the root.
    import json as _json

    from agos_core.actions import digest

    made: list[tuple[str, ...]] = []
    jobs = core.engine.root(ws) / "cron" / "jobs.json"

    def hermes(_key: str, *args: str, **_: Any) -> str:
        made.append(args)
        if args[:2] == ("cron", "create"):
            deliver = next(a.split("=", 1)[1] for a in args if a.startswith("--deliver="))
            jobs.parent.mkdir(parents=True, exist_ok=True)
            jobs.write_text(
                _json.dumps({"jobs": [{"id": "dg1", "name": digest.JOB, "deliver": deliver}]})
            )
            return "Created job: dg1"
        if args[:2] == ("cron", "remove"):
            jobs.write_text(_json.dumps({"jobs": []}))
        return ""

    core.engine._hermes = hermes
    r = client.put("/preferences/notifications", json={"rules": {"task.waiting": "batched"}})
    assert r.status_code == 204
    later = _bridge(client, ws, key, "approval", ask | {"command": "rm -rf later/"}).json()
    assert later["phone"] is None
    assert [h["event"] for h in digest._held(core, ws)] == ["task.waiting"]
    assert "rm -rf later/" in digest._held(core, ws)[0]["text"]
    [create] = [a for a in made if a[:2] == ("cron", "create")]
    assert f"--deliver=telegram:{OWNER}" in create and "--no-agent" in create
    assert f"--script={digest.SCRIPT}" in create and create[-1] == "0 9 * * *"
    assert (core.engine.root(ws) / "scripts" / digest.SCRIPT).read_text() == digest.SCRIPT_TEXT
    assert digest.keep_job(core, ws) == ""  # already right: Hermes isn't asked again
    # Hermes fires it: the script takes the held lines, Hermes delivers what it prints.
    text = _bridge(client, ws, key, "digest", {}).json()["text"]
    assert text.startswith("🗞 **Daily digest**") and "rm -rf later/" in text
    assert digest._held(core, ws) == []
    assert _bridge(client, ws, key, "digest", {}).json()["text"] == ""  # a silent run
    assert (
        core.db.execute("SELECT 1 FROM channel_outbox WHERE source LIKE 'digest:%'").fetchall()
        == []
    )
    # Not an agent's job: Ongoing leaves it out.
    from agos_core.actions import ongoing

    assert ongoing.agent_jobs(core, ws) == []
    # Nothing batched any more: the job goes.
    r = client.put("/preferences/notifications", json={"rules": {"task.waiting": "instant"}})
    assert ("cron", "remove", "dg1") in made
    _bridge(client, ws, key, "turn-finish", {"turnId": start["turnId"], "text": "Ok."})


def test_agos_offers_every_place_he_wrote_in(env: Any) -> None:
    """No ids to look up: the private chat, each group's General and each topic he
    wrote in show up as places to link a chat to; General works as Hermes names it."""
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"sender": str(OWNER)}
    _bridge(
        client, ws, key, "incoming", me | {"chat": "-1000009:1", "text": "hi", "chatName": "Team"}
    )
    _bridge(
        client,
        ws,
        key,
        "incoming",
        me | {"chat": "-1000009:41", "text": "x", "chatName": "Team", "topicName": "Ideas"},
    )
    got = client.get(f"/workspaces/{ws}/telegram-places").json()
    rows = [(p["address"], p["group"], p["label"]) for p in got["places"]]
    assert rows == [
        (f"{OWNER}:0", "", "Private chat with the bot"),
        ("-1000009:0", "Team", "General"),
        ("-1000009:41", "Team", "Ideas"),
    ]
    # He links General to a chat: what he writes in General (topic 1) reaches it.
    chat_id = client.post(f"/workspaces/{ws}/chats", json={"title": "Team chat"}).json()["id"]
    r = client.post(
        f"/workspaces/{ws}/chats/{chat_id}/addresses",
        json={"connectionId": got["connectionId"], "address": "-1000009:0"},
    )
    assert r.status_code == 201, r.text
    linked = client.get(f"/workspaces/{ws}/telegram-places").json()["places"][1]
    assert linked["linkedTo"] == "Team chat"
    said = me | {"chat": "-1000009:1", "text": "hello team"}
    assert _bridge(client, ws, key, "incoming", said).json() == {"handled": False}
    start = _bridge(client, ws, key, "turn-start", {"chat": "-1000009:1", "sessionId": "g"}).json()
    assert start["chatId"] == chat_id


def test_group_members_are_commands_in_telegram(env: Any, monkeypatch: Any) -> None:
    """Telegram's @ list only has real accounts: a linked group's members are "/"
    commands in Hermes's own menu, and /ideas_generator … is a message to that member."""
    client, core, _fake, tg, ws = env
    cid, key = _hermes_bot(client, core, ws)
    for name, title in (("ideas-generator", "Ideas Generator"), ("script-writer", "Script Writer")):
        r = client.post(
            f"/workspaces/{ws}/agents",
            json={"name": name, "title": title, "definition": {"instructions": "x"}},
        )
        assert r.status_code in (200, 201), r.text
    g = client.post(
        f"/workspaces/{ws}/workers/groups",
        json={"title": "Team", "members": ["ideas-generator", "script-writer"]},
    ).json()["id"]
    r = client.post(
        f"/workspaces/{ws}/chats/{g}/addresses", json={"connectionId": cid, "address": "-1000009:0"}
    )
    assert r.status_code == 201, r.text
    channels.tick(core)
    # AGOS never sets Telegram's menu itself: it tells the workspace's Hermes.
    assert tg.menus == []
    import json as _json

    from agos_core.hermes_plugin.agos_guard import POLICY_FILE

    policy = core.engine.profile_home(ws) / POLICY_FILE
    assert _json.loads(policy.read_text())["members"] == [
        {"command": "ideas_generator", "title": "Ideas Generator"},
        {"command": "script_writer", "title": "Script Writer"},
    ]
    # Hermes's menu holds 60 commands: its own setting puts the members first.
    profile = core.engine.profile(ws)
    first = core.engine.runner.config[profile][hermes_channel.MENU_FIRST]
    assert _json.loads(first) == ["ideas_generator", "script_writer"]
    mtime = policy.stat().st_mtime_ns
    channels.tick(core)
    assert policy.stat().st_mtime_ns == mtime  # written again only when the members change
    me = {"chat": "-1000009:1", "sender": str(OWNER)}
    from agos_core.actions import chat as chat_actions

    kicked: list[int] = []
    monkeypatch.setattr(chat_actions, "_kick", lambda _c, _w, chat: kicked.append(chat))
    took = _bridge(client, ws, key, "member-command", me | {"text": "/ideas_generator 3 ideas"})
    assert took.json() == {"handled": True}
    msgs = client.get(f"/workspaces/{ws}/chats/{g}").json()["messages"]
    assert msgs[-1]["body"] == "@ideas-generator 3 ideas"
    assert kicked == [g]  # and its answer starts at once
    # Telegram glued the words on (what's left of "/script_writer@bot hello").
    _bridge(client, ws, key, "member-command", me | {"text": "/script_writerhello"})
    msgs = client.get(f"/workspaces/{ws}/chats/{g}").json()["messages"]
    assert msgs[-1]["body"] == "@script-writer hello"
    # Picked in the menu with no words (Telegram sends it at once): his NEXT message
    # goes to that member; AGOS says so in the group; nothing is answered yet.
    kicked.clear()
    _bridge(client, ws, key, "member-command", me | {"text": "/ideas_generator@agos_bot"})
    msgs = client.get(f"/workspaces/{ws}/chats/{g}").json()["messages"]
    assert msgs[-1]["body"] == "Your next message here goes to Ideas Generator."
    assert kicked == []
    assert hermes_channel.chosen_member(core, g) == "ideas-generator"
    assert hermes_channel.chosen_member(core, g) is None  # once
    # Its answer in Telegram says who wrote it (every answer comes from the same bot).
    chats_repo.add_chat_message(core.db, ws, g, "agent", "Idea one.", speaker="ideas-generator")
    chats_repo.add_chat_message(core.db, ws, g, "agent", "Thanks team.")
    channels.tick(core)
    said = [m["text"] for m in tg.sent if m["chat_id"] == "-1000009"]
    assert "Ideas Generator:" in said[-2] and "Idea one." in said[-2]
    assert "Co-Founder:" in said[-1]
    # Hermes's own command runs in the group's own Hermes conversation, and shows in
    # the chat.
    other = _bridge(client, ws, key, "member-command", me | {"text": "/status"}).json()
    assert other == {"handled": True}
    got = _bridge(client, ws, key, "platform-next", {}).json()["items"]
    assert [(i["chat"], i["kind"], i["text"]) for i in got] == [(f"agos:{g}", "command", "/status")]
    assert client.get(f"/workspaces/{ws}/chats/{g}").json()["messages"][-1]["body"] == "/status"
