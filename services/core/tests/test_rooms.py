"""Group chats as Hermes hosted rooms, the Co-Founder as director (ADR 0020): what AGOS
does on its side of the bridge (the gateway's plugin is played here by the test)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_hermes_roots import _new, roots_env  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, channels, hermes_channel, rooms
from agos_core.actions.services.chat import room_asks, room_sync, room_turns
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction


@pytest.fixture
def group(roots_env: Any, monkeypatch: Any) -> tuple[Any, Any, str, int]:  # noqa: F811
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    for name in ("writer", "editor"):
        core.engine.ensure_profile(agent_profiles.key(ws, name))
    monkeypatch.setattr(
        agent_profiles, "ready", lambda _c, w, a: w == ws and a in ("writer", "editor")
    )
    with transaction(core.db):
        chat = chats_repo.insert_chat(
            core.db,
            workspace_id=ws,
            title="Launch",
            channel="web",
            kind="group",
            members=["writer", "editor"],
        )
    return client, core, ws, int(chat)


def _bridge(
    client: Any, core: Any, ws: str, path: str, body: dict[str, Any], key: str | None = None
) -> Any:
    key = key or hermes_channel.bridge_key(core, ws)
    return client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )


def _jobs(core: Any, ws: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = rooms.take(core, ws)["items"]
    return items


def _say(core: Any, ws: str, chat: int, text: str) -> int:
    with transaction(core.db):
        mid = chats_repo.add_chat_message(core.db, ws, chat, "owner", text)
    assert mid is not None
    rooms.hand_over(core, ws, chat, [(mid, text)])
    return mid


def _member_event(room: str, seq: int, member: str, text: str, discussion: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "event_id": f"dmessage:{room}:{seq}",
        "kind": "message.member",
        "actor": {"kind": "member", "id": member},
        "payload": {
            "member_id": member,
            "text": text,
            "discussion_event_id": discussion,
            "thread_id": "main",
            "round_index": 0,
        },
    }


def _activity(seq: int, discussion: str, reason: str = "max_rounds") -> dict[str, Any]:
    return {
        "seq": seq,
        "event_id": f"dactivity:{discussion}:{reason}:{seq}",
        "kind": "room.activity",
        "actor": {"kind": "gateway", "id": "install:x"},
        "payload": {
            "status": "bounded",
            "reason_code": reason,
            "discussion_event_id": discussion,
            "thread_id": "main",
        },
    }


def test_his_message_goes_in_as_he_wrote_it(group: Any) -> None:
    """Hermes decides who answers (the members he @mentions, or everyone)."""
    _client, core, ws, chat = group
    _say(core, ws, chat, "write a launch post")
    jobs = _jobs(core, ws)
    assert [j["kind"] for j in jobs] == ["room-sync", "room-send"]
    sync, send = jobs[0]["job"], jobs[1]["job"]
    assert sync["room_id"] == f"agos-c{chat}-g1" and sync["disband"] is None
    assert [m["profile"] for m in sync["members"]] == ["default", "a-writer", "a-editor"]
    assert [m["handle"] for m in sync["members"]] == ["cofounder", "writer", "editor"]
    assert send["text"] == "write a launch post"
    # The chat shows the room working (its live turn, Stop works on it).
    turn = chats_repo.live_turn(core.db, chat)
    assert turn is not None and turn.via == rooms.VIA


def test_an_empty_take_opens_no_write_transaction(group: Any, monkeypatch: Any) -> None:
    """The gateway asks for room jobs every few seconds and almost always finds none:
    that ask never takes SQLite's write lock (BEGIN IMMEDIATE waits up to 5 s)."""
    _client, core, ws, chat = group
    opened: list[object] = []

    def counted(db: Any) -> Any:
        opened.append(db)
        return transaction(db)

    # Every room module that opens a transaction (the room service is split in parts).
    for mod in (room_sync, room_turns, room_asks):
        monkeypatch.setattr(mod, "transaction", counted)
    assert rooms.take(core, ws)["items"] == []
    assert opened == []
    _say(core, ws, chat, "write a launch post")
    assert [j["kind"] for j in _jobs(core, ws)] == ["room-sync", "room-send"]
    assert opened


def test_he_can_still_name_a_member(group: Any) -> None:
    _client, core, ws, chat = group
    _say(core, ws, chat, "@editor check the draft")
    send = next(j for j in _jobs(core, ws) if j["kind"] == "room-send")["job"]
    assert send["text"] == "@editor check the draft"


def test_room_log_becomes_the_chat_once_with_names_and_telegram(group: Any) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "write it")
    room = f"agos-c{chat}-g1"
    disc = core.db.execute(
        "SELECT discussion FROM group_rooms WHERE chat_id = ?", (chat,)
    ).fetchone()[0]
    events = [
        _member_event(room, 2, "cofounder", "@writer please write it", disc),
        _member_event(room, 4, "writer", "Draft ready. @cofounder", disc),
    ]
    r = _bridge(client, core, ws, "room-events", {"roomId": room, "events": events})
    assert r.status_code == 200 and r.json()["cursor"] == 4
    # Again (a restarted gateway reads the log again): nothing new.
    _bridge(client, core, ws, "room-events", {"roomId": room, "events": events})
    agent_rows = core.db.execute(
        "SELECT speaker, body FROM messages WHERE chat_id = ? AND author = 'agent' ORDER BY id",
        (chat,),
    ).fetchall()
    assert [(r["speaker"], r["body"]) for r in agent_rows] == [
        (None, "@writer please write it"),
        ("writer", "Draft ready. @cofounder"),
    ]
    # Linked to a Telegram topic: each reply goes there once, under its author's name.
    conn = core.db.execute(
        """INSERT INTO channel_connections (workspace_id, kind, name, engine, created_at)
           VALUES (?, 'telegram', 'bot', 'hermes', '2026-10-13T00:00:00Z')""",
        (ws,),
    ).lastrowid
    core.db.execute(
        """INSERT INTO chat_addresses (chat_id, connection_id, address, created_at)
           VALUES (?, ?, '-1001:7', '2026-10-13T00:00:00Z')""",
        (chat, conn),
    )
    assert channels.queue_replies(core) == 2
    assert channels.queue_replies(core) == 0
    bodies = [r[0] for r in core.db.execute("SELECT body FROM channel_outbox ORDER BY id")]
    assert bodies[0].startswith("**Co-Founder:**") and bodies[1].startswith("**Writer:**")


def test_hermes_ends_the_room_and_agos_adds_nothing(group: Any) -> None:
    """Settled or its own round/message limit: the live answer closes; AGOS never
    sends a turn of its own (no continuation, no note)."""
    client, core, ws, chat = group
    for reason in ("max_rounds", "max_messages", "silent_round"):
        _say(core, ws, chat, f"pingpong {reason}")
        room = f"agos-c{chat}-g1"
        _jobs(core, ws)
        disc = core.db.execute(
            "SELECT discussion FROM group_rooms WHERE chat_id = ?", (chat,)
        ).fetchone()[0]
        seq = 10 * (1 + ("max_rounds", "max_messages", "silent_round").index(reason))
        events = [
            _member_event(room, seq, "writer", "@editor your turn", disc),
            _activity(seq + 1, disc, reason),
        ]
        _bridge(client, core, ws, "room-events", {"roomId": room, "events": events})
        assert [j for j in _jobs(core, ws) if j["kind"] == "room-send"] == []
        assert chats_repo.live_turn(core.db, chat) is None
    notes = core.db.execute(
        "SELECT body FROM messages WHERE chat_id = ? AND speaker = 'AGOS'", (chat,)
    ).fetchall()
    assert notes == []


def test_approvals_card_and_answer(group: Any) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "danger")
    room = f"agos-c{chat}-g1"
    body = {
        "roomId": room,
        "memberId": "writer",
        "taskId": "dtask:1",
        "executionGeneration": 1,
        "requestId": "req-1",
        "command": "rm -rf /tmp/x",
        "description": "dangerous",
    }
    first = _bridge(client, core, ws, "room-approval", body).json()["id"]
    assert first and _bridge(client, core, ws, "room-approval", body).json()["id"] is None
    # His Allow once (AGOS's chat card or Telegram's chatcmd button).
    r = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "once"})
    assert r.status_code in (200, 204), r.text
    jobs = [j for j in _jobs(core, ws) if j["kind"] == "room-approve"]
    assert jobs and jobs[0]["job"] == {
        "room_id": room,
        "member_id": "writer",
        "task_id": "dtask:1",
        "execution_generation": 1,
        "request_id": "req-1",
        "choice": "once",
    }


def test_stop_is_hermes_stop_room(group: Any) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "write it")
    _jobs(core, ws)
    r = client.post(f"/workspaces/{ws}/chats/{chat}/stop")
    assert r.status_code in (200, 204), r.text
    assert [j["kind"] for j in _jobs(core, ws)] == ["room-stop"]
    assert chats_repo.live_turn(core.db, chat) is None


def test_live_work_shows_in_the_chat(group: Any) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "write it")
    room = f"agos-c{chat}-g1"
    items = [
        {
            "member_id": "writer",
            "kind": "tool.started",
            "payload": {"tool": "terminal", "preview": "cat x"},
        }
    ]
    _bridge(client, core, ws, "room-live", {"roomId": room, "items": items})
    from agos_core.actions import chat as chat_actions

    snap = chat_actions.live_snapshot(core, chat)
    assert snap is not None and snap["speaker"] == "writer"
    assert snap["activity"], snap
    assert "cat x" in json.dumps(snap["activity"])


def test_membership_change_makes_the_room_again_agos_keeps_history(
    group: Any, monkeypatch: Any
) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    made = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")["job"]
    # The plugin tells what Hermes's room holds: the members it was made with.
    room = {"pending": [], "members": made["members"]}
    _bridge(client, core, ws, "room-next", {"rooms": {made["room_id"]: room}})
    with transaction(core.db):
        chats_repo.add_chat_message(core.db, ws, chat, "agent", "earlier answer", speaker="writer")
    monkeypatch.setattr(agent_profiles, "ready", lambda _c, w, a: w == ws and a == "writer")
    with transaction(core.db):
        chats_repo.set_members(core.db, ws, chat, ["writer"])
    rooms.members_changed(core, ws, chat)
    sync = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")["job"]
    assert sync["room_id"] == f"agos-c{chat}-g2" and sync["disband"] == f"agos-c{chat}-g1"
    assert [m["handle"] for m in sync["members"]] == ["cofounder", "writer"]
    _say(core, ws, chat, "second")
    send = next(j for j in _jobs(core, ws) if j["kind"] == "room-send")["job"]
    assert send["text"] == "second"  # a new room starts as Hermes starts one
    # AGOS's history is all still there.
    assert len(chats_repo.owner_messages(core.db, chat, 0, 10**9)) == 2


def test_rooms_stay_inside_their_workspace(group: Any) -> None:
    client, core, ws, chat = group
    other = _new(client, "Bees")
    # Another workspace's key never reaches this one's rooms.
    r = _bridge(client, core, ws, "room-next", {}, key=hermes_channel.bridge_key(core, other))
    assert r.status_code == 401
    # Its own key can't feed this workspace's room either (rooms are looked up inside
    # the signing workspace only).
    _say(core, ws, chat, "x")
    room = f"agos-c{chat}-g1"
    events = [_member_event(room, 2, "cofounder", "leak", "d")]
    assert _bridge(
        client, core, other, "room-events", {"roomId": room, "events": events}
    ).json() == {"cursor": 0}
    assert rooms.chat_of(core, other, f"room:{chat}") is None
    assert hermes_channel.chat_at(core, other, f"room:{chat}") is None
    assert hermes_channel.chat_at(core, ws, f"room:{chat}") == chat
    # The roster only ever names this root's own profiles.
    members = rooms.roster(core, ws, chat)
    assert all(m["profile"] in ("default", "a-writer", "a-editor") for m in members)


def test_a_group_with_nobody_ready_says_so(group: Any, monkeypatch: Any) -> None:
    _client, core, ws, chat = group
    monkeypatch.setattr(agent_profiles, "ready", lambda *_a: False)
    _say(core, ws, chat, "hello")
    assert _jobs(core, ws) == []
    note = core.db.execute(
        "SELECT body FROM messages WHERE chat_id = ? AND author = 'agent'", (chat,)
    ).fetchone()
    assert note is not None and "no member" in note[0]


def test_agos_writes_no_room_rules_of_its_own(group: Any) -> None:
    """Hermes's own room prompt has the turn rules; AGOS adds none."""
    _client, core, ws, _chat = group
    from agos_core.actions import engine as engine_actions

    engine_actions.write_identity(core, ws)
    soul = (core.engine.root(ws) / "SOUL.md").read_text()
    assert "Group chats (Hermes rooms)" not in soul
    member = agent_profiles.soul_text(
        core, ws, title="Writer", instructions="Write.", local="", reads=[]
    )
    assert "Group chats (Hermes rooms)" not in member


def test_room_turns_get_the_same_tools_as_chats(group: Any) -> None:
    """Hermes runs a room member's turn with the api_server platform's tools."""
    _client, core, ws, _chat = group
    from agos_core.actions import library

    library.apply_workspace(core, ws)
    config = core.engine.runner.config[core.engine.profile(ws)]
    room_tools = json.loads(config["platform_toolsets.api_server"])
    assert "terminal" in room_tools and "file" in room_tools
    assert room_tools == json.loads(config["platform_toolsets.agos"])


def test_a_member_picked_in_the_telegram_menu_gets_his_next_message(group: Any) -> None:
    _client, core, ws, chat = group
    from agos_core.actions import hermes_channel

    hermes_channel.choose_member(core, ws, chat, "editor")
    _say(core, ws, chat, "please check the intro")
    sends = [j for j in _jobs(core, ws) if j["kind"] == "room-send"]
    assert sends[-1]["job"]["text"] == "@editor please check the intro"
    _say(core, ws, chat, "and thanks")  # only the one message: back to the Co-Founder
    sends = [j for j in _jobs(core, ws) if j["kind"] == "room-send"]
    assert sends[-1]["job"]["text"] == "and thanks"


def test_a_silent_round_after_a_member_answered_him_is_the_end(group: Any) -> None:
    """He wrote to a member; it answered; nobody else had anything to say (Hermes's
    silent round): done. No AGOS note, no Co-Founder repeating the answer."""
    client, core, ws, chat = group
    _say(core, ws, chat, "@editor is the intro ok?")
    room = f"agos-c{chat}-g1"
    _jobs(core, ws)
    disc = core.db.execute(
        "SELECT discussion FROM group_rooms WHERE chat_id = ?", (chat,)
    ).fetchone()[0]
    events = [
        _member_event(room, 2, "editor", "Yes, it reads well.", disc),
        _activity(3, disc, "silent_round"),
    ]
    _bridge(client, core, ws, "room-events", {"roomId": room, "events": events})
    assert [j for j in _jobs(core, ws) if j["kind"] == "room-send"] == []
    assert chats_repo.live_turn(core.db, chat) is None
    bodies = [
        str(r[0]) for r in core.db.execute("SELECT body FROM messages WHERE chat_id = ?", (chat,))
    ]
    assert not any("carry on" in b for b in bodies)


def test_room_event_survives_another_threads_rollback(group: Any) -> None:
    """The Co-Founder's first message went missing from the group chat (writer, editor
    and his summary came): its room event was taken while another thread's
    transaction was open on the shared connection, so it became a savepoint inside
    that one and went with its rollback; the next event moved AGOS's cursor past it
    and the plugin never sent it again."""
    import threading

    _client, core, ws, chat = group
    _say(core, ws, chat, "write a short poem about the sea")
    room = f"agos-c{chat}-g1"
    disc = core.db.execute(
        "SELECT discussion FROM group_rooms WHERE chat_id = ?", (chat,)
    ).fetchone()[0]
    first = _member_event(room, 2, "cofounder", "@writer please write it.", disc)
    later = _member_event(room, 4, "writer", "Draft ready. @cofounder", disc)
    other_in, taken = threading.Event(), threading.Event()

    def other_work() -> None:
        # Any other request's transaction, open meanwhile, that fails and rolls back.
        try:
            with transaction(core.db):
                core.db.execute("UPDATE chats SET updated_at = updated_at WHERE id = ?", (chat,))
                other_in.set()
                taken.wait(1.0)  # the room event is taken meanwhile (when it can be)
                raise RuntimeError("that other work failed")
        except RuntimeError:
            pass

    def take_first() -> None:
        rooms.events(core, ws, room, [first])
        taken.set()

    other = threading.Thread(target=other_work)
    other.start()
    assert other_in.wait(5)
    plugin = threading.Thread(target=take_first)
    plugin.start()
    plugin.join(10)
    other.join(10)
    assert not plugin.is_alive() and not other.is_alive()
    cursor = rooms.events(core, ws, room, [later])
    # The plugin reads the log again after AGOS's cursor: what it would still send.
    rooms.events(core, ws, room, [e for e in (first, later) if e["seq"] > cursor])
    agent_rows = core.db.execute(
        "SELECT speaker, body FROM messages WHERE chat_id = ? AND author = 'agent' ORDER BY id",
        (chat,),
    ).fetchall()
    assert [(r["speaker"], r["body"]) for r in agent_rows] == [
        (None, "@writer please write it."),
        ("writer", "Draft ready. @cofounder"),
    ]


def _hermes_room(core: Any, ws: str, room_id: str, name: str) -> None:
    """Hermes's own record of the room (its root's shared-state.db hosted_rooms)."""
    import sqlite3
    from contextlib import closing

    path = core.engine.profile_home(ws) / "shared-state.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS hosted_rooms (room_id TEXT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT OR REPLACE INTO hosted_rooms VALUES (?, ?)", (room_id, name))
        db.commit()


def _own_title(core: Any, chat: int) -> str:
    return str(core.db.execute("SELECT title FROM chats WHERE id = ?", (chat,)).fetchone()[0])


def test_a_groups_name_is_its_hermes_rooms(group: Any) -> None:
    """Once Hermes made the room, the group's name is the room's (AGOS's copy goes);
    a rename is Hermes's rename_room, and AGOS holds the new name only until then."""
    from agos_core.actions import chat as chat_actions

    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    sync = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")
    assert sync["job"]["name"] == f"Launch · #{chat}"
    _hermes_room(core, ws, sync["job"]["room_id"], sync["job"]["name"])
    rooms.done(core, ws, sync["id"], True)
    assert _own_title(core, chat) == ""
    assert chats_repo.title_of(core.db, chat) == "Launch"
    assert client.get(f"/workspaces/{ws}/chats/{chat}").json()["title"] == "Launch"

    chat_actions.rename(core, ws, chat, "Go live")
    assert _own_title(core, chat) == "Go live"  # until Hermes holds it
    assert chats_repo.title_of(core.db, chat) == "Go live"
    rename = next(j for j in _jobs(core, ws) if j["kind"] == "room-rename")
    assert rename["job"]["room_id"] == sync["job"]["room_id"]
    assert rename["job"]["name"] == f"Go live · #{chat}"
    _hermes_room(core, ws, rename["job"]["room_id"], rename["job"]["name"])
    rooms.done(core, ws, rename["id"], True)
    assert _own_title(core, chat) == ""
    assert chats_repo.title_of(core.db, chat) == "Go live"
    listed = client.get(f"/workspaces/{ws}/workers").json()
    assert "Go live" in json.dumps(listed)

    # A refused rename: the name stays AGOS's, nothing lost.
    chat_actions.rename(core, ws, chat, "Later")
    refused = next(j for j in _jobs(core, ws) if j["kind"] == "room-rename")
    rooms.done(core, ws, refused["id"], False, "hosted room not found")
    assert _own_title(core, chat) == "Later"
    assert chats_repo.title_of(core.db, chat) == "Later"


def test_a_groups_name_moves_into_its_room_once(group: Any) -> None:
    """Live data: a group whose room Hermes already holds. Same name: AGOS's copy
    goes; another name (the old rooms never followed a rename): the room is renamed."""
    _client, core, ws, chat = group
    _say(core, ws, chat, "first")
    sync = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")
    room_id = sync["job"]["room_id"]
    with transaction(core.db):
        core.db.execute("UPDATE group_rooms SET state = 'ready' WHERE chat_id = ?", (chat,))
    _hermes_room(core, ws, room_id, f"Launch · #{chat}")
    assert rooms.move_old_names(core) == 1
    assert _own_title(core, chat) == "" and chats_repo.title_of(core.db, chat) == "Launch"
    assert rooms.move_old_names(core) == 0  # once

    with transaction(core.db):
        core.db.execute("UPDATE chats SET title = 'Renamed' WHERE id = ?", (chat,))
    rooms.move_old_names(core)
    rename = next(j for j in _jobs(core, ws) if j["kind"] == "room-rename")
    assert rename["job"]["name"] == f"Renamed · #{chat}"
    assert _own_title(core, chat) == "Renamed"  # until Hermes confirms


def test_a_new_room_after_a_membership_change_keeps_the_name(group: Any, monkeypatch: Any) -> None:
    """The old room held the name: AGOS holds it again until the new room does."""
    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    sync = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")
    _hermes_room(core, ws, sync["job"]["room_id"], sync["job"]["name"])
    rooms.done(core, ws, sync["id"], True)
    room = {"pending": [], "members": sync["job"]["members"]}
    _bridge(client, core, ws, "room-next", {"rooms": {sync["job"]["room_id"]: room}})
    assert _own_title(core, chat) == ""
    monkeypatch.setattr(agent_profiles, "ready", lambda _c, w, a: w == ws and a == "writer")
    with transaction(core.db):
        chats_repo.set_members(core.db, ws, chat, ["writer"])
    rooms.members_changed(core, ws, chat)
    again = next(j for j in _jobs(core, ws) if j["kind"] == "room-sync")
    assert again["job"]["name"] == f"Launch · #{chat}"
    assert _own_title(core, chat) == "Launch"
    _hermes_room(core, ws, again["job"]["room_id"], again["job"]["name"])
    rooms.done(core, ws, again["id"], True)
    assert _own_title(core, chat) == "" and chats_repo.title_of(core.db, chat) == "Launch"
