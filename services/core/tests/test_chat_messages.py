"""The owner's messages in a chat: one answer for messages in a row, replies to a
message or a part of it, edits and deletes, and what Hermes confirmed."""

from functools import partial
from typing import Any

from chat_rig import (
    CLIENT,
    MODEL,
    Env,
    chat_actions_tick,
    get,
    new_chat,
    say,
    settle,
)
from chat_rig import env as env
from fake_gateway import pump

from agos_core.actions import chat as chat_actions
from agos_core.db import chats as chats_repo


def test_messages_sent_one_after_another_are_one_answer_on_hermes(env: Env) -> None:
    """Each message goes to Hermes at once; Hermes makes them one answer (its text
    batching, or its steer when it already works). AGOS queues nothing and starts
    no answer of its own after one ends."""
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    for words in ("salam", "bghit report", "dyal had simana"):
        say(client, ws, chat, words)

    def said() -> str:
        steered = "".join(t for _, t in getattr(fake, "steered", []))
        return (fake.bodies[0]["input"] if fake.bodies else "") + steered

    settle(core, lambda: all(w in said() for w in ("salam", "bghit report", "dyal had simana")))
    assert len(fake.bodies) == 1
    fake.push("run_1", {"event": "run.completed", "output": "Report soon."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    for _ in range(5):
        chat_actions_tick(core)
        pump(core, fake)
    assert len(fake.bodies) == 1  # nothing handed over again by AGOS


def test_a_reply_carries_the_message_it_answers(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "write 3 hooks")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "run.completed", "output": "1. A\n2. B\n3. C"})
    settle(core, lambda: not get(client, ws, chat)["working"])
    answer = get(client, ws, chat)["messages"][-1]
    posted = client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={"body": "the second one, shorter", "replyTo": answer["id"]},
    )
    assert posted.status_code == 201
    settle(core, lambda: len(fake.bodies) == 2)
    # The reply is Hermes's own reply context, his words are as he wrote them.
    assert fake.bodies[1]["input"] == (
        '[Replying to your previous message: "1. A\n2. B\n3. C"]\n\nthe second one, shorter'
    )
    mine = get(client, ws, chat)["messages"][-1]
    assert mine["replyTo"] == answer["id"] and mine["replyPreview"].startswith("1. A")
    # A reply can only point at a message of the same chat.
    other = new_chat(client, ws)
    client.post(
        f"/workspaces/{ws}/chats/{other}/messages", json={"body": "x", "replyTo": answer["id"]}
    )
    assert get(client, ws, other)["messages"][-1]["replyTo"] is None


def test_the_lists_link_no_reply_and_a_chat_splits_each_message_once(
    env: Env, monkeypatch: Any
) -> None:
    """The lists (Chats, Team, Office, Dashboard) show each chat's last words only:
    they link no reply. An open chat links each reply comparing the letters of
    each earlier message once (it compared every reply with every earlier message
    again: 0.2 s of every list on a long chat)."""
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "write 3 hooks")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "run.completed", "output": "1. A\n2. B\n3. C"})
    settle(core, lambda: not get(client, ws, chat)["working"])
    answer = get(client, ws, chat)["messages"][-1]
    for n in range(4):
        client.post(
            f"/workspaces/{ws}/chats/{chat}/messages",
            json={"body": f"take {n}", "replyTo": answer["id"]},
        )
        settle(core, lambda n=n: len(fake.bodies) == n + 2)  # type: ignore[misc]
        fake.push(f"run_{n + 2}", {"event": "run.completed", "output": f"done {n}"})
        settle(core, lambda: not get(client, ws, chat)["working"])
    split: list[str] = []
    real = chats_repo.letters_of

    def counted(text: str) -> str:
        split.append(text)
        return real(text)

    monkeypatch.setattr(chats_repo, "letters_of", counted)
    listed = client.get(f"/workspaces/{ws}/chats").json()
    assert [c["preview"] for c in listed if c["id"] == chat] == ["done 3"]
    assert split == []
    shown = get(client, ws, chat)["messages"]
    replies = [m for m in shown if m["replyTo"]]
    assert [m["replyTo"] for m in replies] == [answer["id"]] * 4
    assert len(split) <= len(shown) + len(replies)


def test_a_reply_to_a_selected_part_sends_only_that_part(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "write 3 hooks")
    settle(core, lambda: bool(fake.bodies))
    fake.push(
        "run_1",
        {"event": "run.completed", "output": "1. **Alpha** opening\n2. Beta middle\n3. Gamma end"},
    )
    settle(core, lambda: not get(client, ws, chat)["working"])
    answer = get(client, ws, chat)["messages"][-1]
    client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={"body": "shorter", "replyTo": answer["id"], "replyExcerpt": "Beta middle"},
    )
    settle(core, lambda: len(fake.bodies) == 2)
    sent = fake.bodies[1]["input"]
    assert sent == '[Replying to your previous message: "Beta middle"]\n\nshorter'
    assert "Gamma" not in sent
    mine = get(client, ws, chat)["messages"][-1]
    assert mine["replyExcerpt"] == "Beta middle" and mine["replyPreview"] == "Beta middle"
    # A selection keeps working across markdown marks (the page shows **Alpha** as Alpha).
    fake.push("run_2", {"event": "run.completed", "output": "ok"})
    settle(core, lambda: not get(client, ws, chat)["working"])
    client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={"body": "this", "replyTo": answer["id"], "replyExcerpt": "Alpha opening"},
    )
    assert get(client, ws, chat)["messages"][-1]["replyExcerpt"] == "Alpha opening"
    # A selection across list items (the page drops "- " and "2.") still counts.
    client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={
            "body": "these two",
            "replyTo": answer["id"],
            "replyExcerpt": "Beta middle\nGamma end",
        },
    )
    assert get(client, ws, chat)["messages"][-1]["replyExcerpt"] == "Beta middle\nGamma end"
    # Text that isn't in the message falls back to replying to the whole message.
    client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={"body": "x", "replyTo": answer["id"], "replyExcerpt": "not in it"},
    )
    assert get(client, ws, chat)["messages"][-1]["replyExcerpt"] is None


def test_owner_edits_and_deletes_messages(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "write about cats")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "run.completed", "output": "Cats are great."})

    settle(
        core,
        lambda: (
            not get(client, ws, chat)["working"] and len(get(client, ws, chat)["messages"]) == 2
        ),
    )
    mine, reply = get(client, ws, chat)["messages"][-2:]
    url = f"/workspaces/{ws}/chats/{chat}/messages"
    # Edit an answered message: the agent hears about it with the next message.
    assert client.put(f"{url}/{mine['id']}", json={"body": "write about dogs"}).status_code == 204
    edited = get(client, ws, chat)["messages"][-2]
    assert edited["body"] == "write about dogs" and edited["editedAt"]
    say(client, ws, chat, "go on")
    settle(core, lambda: len(fake.bodies) == 2)
    sent = fake.bodies[1]["input"]
    assert "write about cats" in sent and "write about dogs" in sent and "go on" in sent
    # Told once only.
    fake.push("run_2", {"event": "run.completed", "output": "Dogs."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    say(client, ws, chat, "again")
    settle(core, lambda: len(fake.bodies) == 3)
    assert "write about cats" not in fake.bodies[2]["input"]
    # Only his own messages can be edited; any message can be deleted.
    assert client.put(f"{url}/{reply['id']}", json={"body": "x"}).status_code == 404
    assert client.delete(f"{url}/{reply['id']}").status_code == 204
    assert reply["id"] not in [m["id"] for m in get(client, ws, chat)["messages"]]
    # Another workspace's chat can't be touched.
    oid = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert client.delete(f"/workspaces/{oid}/chats/{chat}/messages/{mine['id']}").status_code == 404


def test_edit_and_answer_again(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    say(client, ws, chat, "a poem about cats")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "run.completed", "output": "Cats poem."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    mine = get(client, ws, chat)["messages"][-2]
    url = f"/workspaces/{ws}/chats/{chat}/messages/{mine['id']}"
    r = client.put(url, json={"body": "a poem about dogs", "reanswer": True})
    assert r.status_code == 204
    settle(core, lambda: len(fake.bodies) == 2)
    # Hermes's /undo took the old exchange out, then the new text is simply asked.
    assert getattr(fake, "undone", []) == [fake.bodies[0]["address"]]
    assert fake.bodies[1]["input"] == "a poem about dogs"
    assert "Cats poem." not in [m["body"] for m in get(client, ws, chat)["messages"]]
    # While it answers, another re-answer is refused (nothing is cut).
    assert client.put(url, json={"body": "birds", "reanswer": True}).status_code == 409
    fake.push("run_2", {"event": "run.completed", "output": "Dogs poem."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    assert get(client, ws, chat)["messages"][-1]["body"] == "Dogs poem."
    # The change was told already: the next message doesn't repeat it.
    say(client, ws, chat, "thanks")
    settle(core, lambda: len(fake.bodies) == 3)
    assert "a poem about cats" not in fake.bodies[2]["input"]


def test_messages_in_a_row_go_to_hermes_each_once(env: Env) -> None:
    """Each message is one item of the agos platform's queue, in order (Hermes
    batches messages sent in a row itself)."""
    client, _fake, core, ws = env
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Race"}).json()["id"]
    chat_actions.post_message(core, ws, chat, "burst one")
    chat_actions.post_message(core, ws, chat, "burst two")
    sent = [
        r["text"]
        for r in core.db.execute(
            "SELECT text FROM hermes_inbox WHERE chat_ref = ? AND kind = 'message' ORDER BY id",
            (f"agos:{chat}",),
        )
    ]
    assert sent == ["burst one", "burst two"]


def test_a_message_hermes_never_confirmed_comes_again(env: Env) -> None:
    """Hermes confirms each message once it has it (after its text batch went in).
    One a stopped gateway took and never confirmed is handed again; once confirmed,
    a restart is Hermes's own (it resumes an interrupted turn itself)."""
    client, _fake, core, ws = env
    from agos_core.actions import hermes_channel

    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Restart"}).json()["id"]
    chat_actions.save_owner_message(core, ws, chat, "write about cats")
    portal = CLIENT["client"].portal
    assert portal is not None
    portal.call(chat_actions.start_turn, core, ws, chat)
    first = hermes_channel.take_inbox(core, ws, agos=True)
    taken = [i for i in first if i["kind"] == "message"]
    assert [i["text"] for i in taken] == ["write about cats"]
    assert hermes_channel.take_inbox(core, ws, agos=True) == []  # taken, not yet confirmed
    core.db.execute(
        "UPDATE hermes_inbox SET taken_at = '2000-01-01T00:00:00.000Z' WHERE done_at IS NULL"
    )
    again = [i for i in hermes_channel.take_inbox(core, ws, agos=True) if i["kind"] == "message"]
    assert [i["id"] for i in again] == [taken[0]["id"]]
    for item in first:
        hermes_channel.inbox_done(core, ws, item["id"], True)
    core.db.execute("UPDATE hermes_inbox SET taken_at = '2000-01-01T00:00:00.000Z'")
    assert hermes_channel.take_inbox(core, ws, agos=True) == []
    turns = core.db.execute("SELECT status FROM chat_turns WHERE chat_id = ?", (chat,)).fetchall()
    assert [t["status"] for t in turns] == ["running"]


def test_deleting_the_last_exchange_is_hermess_undo(env: Env) -> None:
    """His last message (or its answer) deleted: Hermes's /undo drops the exchange
    from the agent's conversation, and both go from the chat. An older one is told
    to the agent as deleted (Hermes can't take one out of the middle)."""
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    for n, words in enumerate(("first", "second"), 1):
        say(client, ws, chat, words)
        settle(core, partial(lambda want: len(fake.bodies) == want, n))
        fake.push(f"run_{n}", {"event": "run.completed", "output": f"Answer {n}."})
        settle(core, lambda: not get(client, ws, chat)["working"])
    url = f"/workspaces/{ws}/chats/{chat}/messages"
    answer = get(client, ws, chat)["messages"][-1]
    assert client.delete(f"{url}/{answer['id']}").status_code == 204
    settle(core, lambda: bool(getattr(fake, "undone", [])))
    bodies = [m["body"] for m in get(client, ws, chat)["messages"]]
    assert bodies == ["first", "Answer 1."]
    say(client, ws, chat, "third")
    settle(core, lambda: len(fake.bodies) == 3)
    fake.push("run_3", {"event": "run.completed", "output": "Answer 3."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    first = get(client, ws, chat)["messages"][0]
    assert client.delete(f"{url}/{first['id']}").status_code == 204
    say(client, ws, chat, "fourth")
    settle(core, lambda: len(fake.bodies) == 4)
    assert "deleted an earlier message" in fake.bodies[3]["input"]
    assert len(getattr(fake, "undone", [])) == 1
    # Hermes's notes about that /undo (its confirm, its result) aren't shown.
    from agos_core.actions import hermes_channel

    address = fake.bodies[0]["address"]
    assert hermes_channel.platform_said(core, ws, address, "↩️ Undid 1 turn(s) (2 message(s)).")
    assert "↩️ Undid" not in str([m["body"] for m in get(client, ws, chat)["messages"]])


def test_agos_guesses_no_dead_turn_hermes_recovers_crash_lost_ones(env: Env) -> None:
    """#49: Hermes v0.22.2 resumes a turn lost in a crash itself (H:
    gateway/run_startup.py recover_interrupted_turns, resume-pending) and reports its
    end, so AGOS's recurring tick closes no live turn. Only turns from before
    everything ran on Hermes (no `via`) are closed, once, at the core's start."""
    client, _fake, core, ws = env
    ids = {}
    for via in ("hermes", "room", None):
        chat = new_chat(client, ws, f"Chat {via}")
        turn = chats_repo.insert_turn(core.db, chat_id=chat, workspace_id=ws, asked_up_to=0)
        core.db.execute(
            "UPDATE chat_turns SET status = 'running', via = ? WHERE id = ?", (via, turn)
        )
        ids[via] = turn
    core.db.commit()

    def status(via: str | None) -> str:
        found = chats_repo.get_turn(core.db, ids[via])
        assert found is not None
        return str(found.status)

    chat_actions_tick(core)
    assert [status(v) for v in ("hermes", "room", None)] == ["running"] * 3
    assert chat_actions.close_pre_hermes(core) == 1
    assert [status(v) for v in ("hermes", "room", None)] == ["running", "running", "failed"]
    assert chat_actions.close_pre_hermes(core) == 0
