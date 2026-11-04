"""Card threads, Board views and labels (Step 58, F17 / F18 / F29): a comment wakes
only the card's assignee (the reviewer in Review), an @mention watches + wakes once
without reassigning, @owner lands in his Inbox, card ids become chips; saved views,
bulk actions batched into Hermes; labels with folders on the card's Hermes body, the
agents' agos_label tool, and the plugin side (the comment hook, `agos-bulk`)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import types
from collections.abc import Iterator
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_library import env, ws  # noqa: F401 - fixture
from test_reviews import _mirror

from agos_core.actions import (
    agent_profiles,
    board_views,
    hermes_channel,
    inbox,
    kanban_board,
    labels,
    threads,
)
from agos_core.engine import threads as rules
from agos_core.engine.hermes import EngineError
from agos_core.hermes_plugin.agos_guard import threads as guard_threads


@pytest.fixture
def team(env: Any) -> tuple[Any, Any, Any, str]:  # noqa: F811
    """A workspace with a lead and a writer, on a fake Hermes board that also takes
    Hermes's notify-subscribe / notify-unsubscribe and many card ids."""
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "lead")
    add_agent(client, a, "writer")
    cofounder_chat(core, a)
    original = runner._kanban
    counter = {"n": 0}

    def opt(args: list[str], name: str) -> str | None:
        return args[args.index(name) + 1] if name in args else None

    def kanban(profile: str, args: list[str]) -> str:
        cards = runner.kanban.setdefault(profile, {})
        verb = args[0]
        if verb == "notify-subscribe":
            subs = cards[args[1]].setdefault("subs", [])
            sub = {
                "platform": opt(args, "--platform"),
                "chat_id": opt(args, "--chat-id"),
                "thread_id": opt(args, "--thread-id"),
                "delivery_mode": opt(args, "--delivery-mode") or "notify",
                "notifier_profile": opt(args, "--notifier-profile"),
            }
            if not any(s["chat_id"] == sub["chat_id"] for s in subs):
                subs.append(sub)
            return f"Subscribed to {args[1]}"
        if verb == "notify-unsubscribe":
            chat = opt(args, "--chat-id")
            card = cards[args[1]]
            card["subs"] = [s for s in card.get("subs", []) if s["chat_id"] != chat]
            return "ok"
        ids = [x for x in args[1:] if x.startswith("t_")]
        if verb in ("archive", "unblock", "complete") and len(ids) > 1:
            flags = [x for x in args[1:] if not x.startswith("t_")]
            for card_id in ids:  # Hermes's _bulk_apply: each id in turn
                original(profile, [verb, card_id, *flags])
            return "ok"
        if verb == "block" and "--ids" in args:
            for card_id in ids:
                original(profile, ["block", card_id])
            return "ok"
        out = str(original(profile, args))
        if verb == "comment":
            counter["n"] += 1
            cards[args[1]]["comments"][-1]["id"] = counter["n"]
        return out

    runner._kanban = kanban
    return client, core, runner, a


def _board(core: Any, a: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = core.engine.runner.kanban[str(core.engine.profile(a))]
    return found


def _profile(core: Any, a: str, member: str) -> str:
    return str(core.engine.hermes_name(agent_profiles.key(a, member)))


def _handed(core: Any, a: str) -> list[tuple[str, str]]:
    """What went into Hermes conversations (the agos platform's inbound queue)."""
    return [
        (str(r["chat_ref"]), str(r["text"]))
        for r in core.db.execute(
            "SELECT chat_ref, text FROM hermes_inbox WHERE workspace_id = ? AND kind = 'message'",
            (a,),
        )
    ]


@contextlib.contextmanager
def _subs_db(core: Any, a: str) -> Iterator[None]:
    """Hermes's board database with the fake board's notify subscriptions in it."""
    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.execute(
        "CREATE TABLE kanban_notify_subs (task_id TEXT, platform TEXT, chat_id TEXT,"
        " thread_id TEXT, delivery_mode TEXT)"
    )
    for card in _board(core, a).values():
        for s in card.get("subs", []):
            db.execute(
                "INSERT INTO kanban_notify_subs VALUES (?, ?, ?, ?, ?)",
                (card["id"], s["platform"], s["chat_id"], s["thread_id"], s["delivery_mode"]),
            )
    db.commit()
    db.close()
    try:
        yield
    finally:
        (folder / "kanban.db").unlink()


def _kanban_calls(runner: Any, verb: str) -> list[list[str]]:
    return [c for c in runner.calls if "kanban" in c and c[c.index("kanban") + 1] == verb]


# ---- the rules ----------------------------------------------------------------------


def test_a_comment_wakes_the_assignee_only_and_mentions_once() -> None:
    plan = rules.wake_plan(status="running", assignee="writer", author="owner", mentioned=[])
    assert [(w.who, w.how, w.why) for w in plan] == [("writer", "steer", "assignee")]
    # Its own comment never wakes itself; a finished card wakes nobody.
    assert rules.wake_plan(status="running", assignee="writer", author="writer", mentioned=[]) == []
    assert rules.wake_plan(status="done", assignee="writer", author="owner", mentioned=[]) == []
    # Review: the reviewer (Hermes's assignee there); his own stage is his Inbox.
    [rev] = rules.wake_plan(status="review", assignee="lead", author="writer", mentioned=[])
    assert (rev.who, rev.how, rev.why) == ("lead", "review", "reviewer")
    [own] = rules.wake_plan(status="review", assignee="owner", author="writer", mentioned=[])
    assert (own.who, own.how) == ("owner", "inbox")
    # His answer to a card's question starts it again; an agent's comment never does.
    [ans] = rules.wake_plan(
        status="blocked",
        assignee="writer",
        author="owner",
        mentioned=[],
        block_kind="needs_input",
        owner_answer=True,
    )
    assert ans.how == "unblock"
    [note] = rules.wake_plan(
        status="blocked", assignee="writer", author="lead", mentioned=[], block_kind="needs_input"
    )
    assert note.how == "waits"
    # Mentions: once each, never the author nor the assignee again, never @all.
    names = ["writer", "lead"]
    said = "@lead @lead @all @owner @Writer mail@lead.com"
    assert rules.mentions(said, names) == ["lead", "owner", "writer"]
    plan = rules.wake_plan(
        status="ready", assignee="writer", author="lead", mentioned=rules.mentions(said, names)
    )
    assert [(w.who, w.how) for w in plan] == [("writer", "dispatch"), ("owner", "inbox")]


def test_card_refs_and_the_labels_block() -> None:
    assert rules.card_refs("see t_a5ba7050 and t_a5ba7050, not t_zz or x/t_00000001", "t_1") == [
        "t_a5ba7050"
    ]
    body = rules.with_labels("Write it.", [3, 1, 3])
    assert rules.card_labels(body) == [3, 1]
    assert rules.without_labels(body) == "Write it."
    assert rules.with_labels(body, []) == "Write it."


# ---- the owner's comment -----------------------------------------------------------


def test_his_comment_wakes_only_the_assignee_never_the_team(team: Any) -> None:
    client, core, runner, a = team
    card = kanban_board.create(core, a, "Write", "The post.", "writer")
    _board(core, a)[card]["status"] = "running"
    r = client.post(f"/workspaces/{a}/kanban/{card}/comment", json={"text": "Shorter please."})
    assert r.status_code == 200, r.text
    assert [(w["who"], w["how"]) for w in r.json()["woke"]] == [("writer", "steer")]
    # Hermes steers it into the running turn itself: nothing else is sent anywhere,
    # nobody is subscribed, the card keeps its assignee.
    assert _handed(core, a) == []
    assert _kanban_calls(runner, "notify-subscribe") == []
    assert _board(core, a)[card]["assignee"] == _profile(core, a, "writer")
    assert _board(core, a)[card]["comments"][-1]["author"] == "owner"


def test_his_answer_to_a_question_unblocks_the_card(team: Any) -> None:
    _client, core, _runner, a = team
    card = kanban_board.create(core, a, "Write", "The post.", "writer")
    _board(core, a)[card].update(status="blocked", block_kind="needs_input")
    woke = threads.comment(core, a, card, "Use the blue logo.")["woke"]
    assert [(w["who"], w["how"]) for w in woke] == [("writer", "unblock")]
    assert _board(core, a)[card]["status"] == "ready"
    # A stopped card (his own Stop) stays stopped, unless he asks to resume it.
    other = kanban_board.create(core, a, "Other", "", "writer")
    _board(core, a)[other]["status"] = "blocked"
    assert threads.comment(core, a, other, "A note.")["woke"][0]["how"] == "waits"
    assert _board(core, a)[other]["status"] == "blocked"
    threads.comment(core, a, other, "Go on.", resume=True)
    assert _board(core, a)[other]["status"] == "ready"


def test_in_review_the_reviewer_is_woken_not_the_implementer(team: Any) -> None:
    _client, core, _runner, a = team
    card = kanban_board.create(core, a, "Write", "", "writer")
    _board(core, a)[card].update(status="review", assignee=_profile(core, a, "lead"))
    woke = threads.comment(core, a, card, "Check the numbers.")["woke"]
    assert [(w["who"], w["how"], w["why"]) for w in woke] == [("lead", "review", "reviewer")]


def test_a_mention_watches_and_wakes_once_without_reassigning(team: Any) -> None:
    client, core, _runner, a = team
    card = kanban_board.create(core, a, "Write", "", "writer")
    woke = threads.comment(core, a, card, "@lead can you check the tone?")["woke"]
    assert [(w["who"], w["how"]) for w in woke] == [("writer", "dispatch"), ("lead", "mention")]
    # Hermes's own subscription of the lead's conversation about the card (wake mode).
    [sub] = _board(core, a)[card]["subs"]
    assert sub["platform"] == "agos" and sub["delivery_mode"] == "wake"
    assert sub["notifier_profile"] == core.engine.hermes_name(a)
    chat = int(sub["chat_id"])
    row = core.db.execute("SELECT agent, kanban_card FROM chats WHERE id = ?", (chat,)).fetchone()
    assert (row["agent"], row["kanban_card"]) == ("lead", card)
    # Woken once, in that conversation, with the comment; the card stays the writer's.
    [(where, text)] = _handed(core, a)
    assert where == f"{hermes_channel.AGOS_PREFIX}{chat}"
    assert "> @lead can you check the tone?" in text and card in text
    assert _board(core, a)[card]["assignee"] == _profile(core, a, "writer")
    # The card shows its watcher (read from Hermes's kanban_notify_subs).
    with _subs_db(core, a):
        assert [(w["name"], w["title"]) for w in threads.watchers(core, a, card)] == [
            ("lead", "Lead")
        ]
    # An agent's comment through the bridge (the plugin's hook), told twice: once.
    _board(core, a)[card]["comments"].append(
        {
            "id": 50,
            "author": _profile(core, a, "lead"),
            "body": "@cofounder the tone is fine, see t_99999999",
            "created_at": 1_800_000_500,
        }
    )
    key = hermes_channel.bridge_key(core, a)
    for _ in range(2):
        r = client.post(
            f"/hermes-bridge/{a}/card-comment",
            json={"card": card, "comment": 50},
            headers={"authorization": f"Bearer {key}"},
        )
        assert r.status_code == 200, r.text
    assert len(_handed(core, a)) == 2  # the Co-Founder, once
    assert r.json() == {"woke": [], "again": True}
    # Unwatch: Hermes's subscription goes.
    with _subs_db(core, a):
        r = client.delete(f"/workspaces/{a}/kanban/{card}/watchers/lead")
        assert r.status_code == 200, r.text
    assert [s["chat_id"] for s in _board(core, a)[card]["subs"]] == [str(cofounder_chat(core, a))]
    # Another workspace's key, or A's card on B's bridge: refused / not found.
    b = ws(client, "Beta")
    cross = client.post(
        f"/hermes-bridge/{b}/card-comment",
        json={"card": card, "comment": 50},
        headers={"authorization": f"Bearer {key}"},
    )
    assert cross.status_code in (401, 403)
    on_b = client.post(
        f"/hermes-bridge/{b}/card-comment",
        json={"card": card, "comment": 51},
        headers={"authorization": f"Bearer {hermes_channel.bridge_key(core, b)}"},
    )
    assert "error" in on_b.json()


def test_a_mention_of_the_owner_lands_in_his_inbox(team: Any) -> None:
    _client, core, _runner, a = team
    card = kanban_board.create(core, a, "Write", "", "writer")
    held = kanban_board.create(core, a, "Approve", "", "writer")
    _board(core, a)[held].update(status="review", assignee="owner")
    writer = _profile(core, a, "writer")
    _board(core, a)[card]["comments"].append(
        {"author": writer, "body": "@owner which logo?", "created_at": 1_800_000_400}
    )
    _board(core, a)[held]["comments"].append(
        {"author": writer, "body": "Ready when you are.", "created_at": 1_800_000_401}
    )
    _mirror(core, a)
    try:
        found = [i for i in inbox.items(core, a) if i["type"] == "mention"]
    finally:
        (agent_profiles.board_home(core, a) / "kanban.db").unlink()
    assert sorted((i["card"], i["mention"]["reason"]) for i in found) == sorted(
        [(card, "mention"), (held, "review")]
    )
    assert all(i["memberName"] == "Writer" for i in found)
    # He answered on the card: gone.
    _board(core, a)[card]["comments"].append(
        {"author": "owner", "body": "The blue one.", "created_at": 1_800_000_402}
    )
    _mirror(core, a)
    try:
        left = [i["card"] for i in inbox.items(core, a) if i["type"] == "mention"]
    finally:
        (agent_profiles.board_home(core, a) / "kanban.db").unlink()
    assert left == [held]


def test_card_ids_in_the_thread_are_chips(team: Any) -> None:
    client, core, _runner, a = team
    first = kanban_board.create(core, a, "Research", "", "writer")
    card = kanban_board.create(core, a, "Write", f"Builds on {first}.", "writer")
    _board(core, a)[first]["status"] = "done"
    threads.comment(core, a, card, f"Also see {first} and t_deadbeef (gone).")
    shown = client.get(f"/workspaces/{a}/kanban/{card}").json()
    assert shown["refs"] == [
        {"id": first, "title": "Research", "status": "done", "statusLabel": "Done"}
    ]
    assert shown["comments"][-1]["id"] > 0


# ---- labels --------------------------------------------------------------------------


def test_labels_folders_on_the_card_and_the_agents_tool(team: Any) -> None:
    client, core, _runner, a = team
    r = client.post(f"/workspaces/{a}/labels", json={"name": "Urgent", "color": "red"})
    assert r.status_code == 201, r.text
    urgent = r.json()["id"]
    blog = client.post(
        f"/workspaces/{a}/labels", json={"name": "Blog", "color": "blue", "folder": "Channels"}
    ).json()["id"]
    dup = client.post(f"/workspaces/{a}/labels", json={"name": "urgent"})
    assert dup.status_code >= 400
    assert (
        client.post(f"/workspaces/{a}/labels", json={"name": "X", "color": "neon"}).status_code
        >= 400
    )
    renamed = client.put(f"/workspaces/{a}/labels/{blog}", json={"name": "Blog posts"}).json()
    assert renamed["name"] == "Blog posts" and renamed["folder"] == "Channels"
    moved = client.post(
        f"/workspaces/{a}/label-folders/rename", json={"old": "Channels", "new": "Where"}
    ).json()
    assert {lb["name"]: lb["folder"] for lb in moved} == {"Blog posts": "Where", "Urgent": ""}
    card = kanban_board.create(core, a, "Write", "The post.", "writer")
    other = kanban_board.create(core, a, "Edit", "", "lead")
    assert (
        client.put(
            f"/workspaces/{a}/kanban/{card}/labels", json={"ids": [urgent, blog]}
        ).status_code
        == 204
    )
    # The card's own Hermes body holds them; the board shows them and a clean body.
    assert rules.card_labels(_board(core, a)[card]["body"]) == [urgent, blog]
    board = client.get(f"/workspaces/{a}/kanban").json()
    shown = {c["id"]: c for c in board["cards"]}
    assert shown[card]["labels"] == [urgent, blog] and shown[card]["body"] == "The post."
    assert shown[other]["labels"] == []
    assert {lb["name"] for lb in board["labels"]} == {"Urgent", "Blog posts"}
    # The agents' tool: by name, only known labels, this workspace's cards.
    assert labels.for_agent(core, a, action="list", card="", names=[])["labels"]
    said = labels.for_agent(core, a, action="add", card=other, names=["urgent"])
    assert said["ok"] and rules.card_labels(_board(core, a)[other]["body"]) == [urgent]
    assert (
        "Unknown label"
        in labels.for_agent(core, a, action="add", card=other, names=["Nope"])["error"]
    )
    key = hermes_channel.bridge_key(core, a)
    r = client.post(
        f"/hermes-bridge/{a}/labels",
        json={"member": "lead", "action": "remove", "card": other, "labels": ["Urgent"]},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.json()["ok"] and rules.card_labels(_board(core, a)[other]["body"]) == []
    # Deleting a label takes it off every card.
    assert client.delete(f"/workspaces/{a}/labels/{urgent}").status_code == 204
    assert rules.card_labels(_board(core, a)[card]["body"]) == [blog]
    assert [lb["name"] for lb in labels.listing(core, a)] == ["Blog posts"]


# ---- views and bulk actions ----------------------------------------------------------


def test_saved_views_crud_and_on_the_board(team: Any) -> None:
    client, _core, _runner, a = team
    view = {
        "name": "Writer's blocked",
        "filters": {"members": ["writer"], "blocked": "yes", "labels": [1], "text": "post"},
        "groupBy": "label",
        "sort": "title",
        "layout": "list",
        "columns": ["id", "title", "labels"],
    }
    r = client.post(f"/workspaces/{a}/board-views", json=view)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["id"] == 1 and saved["groupBy"] == "label" and saved["filters"]["blocked"] == "yes"
    again = client.post(f"/workspaces/{a}/board-views", json={**view, "name": "writer's BLOCKED"})
    assert again.status_code >= 400
    bad = client.post(f"/workspaces/{a}/board-views", json={**view, "groupBy": "planet"})
    assert bad.status_code == 422
    changed = client.put(
        f"/workspaces/{a}/board-views/1", json={**view, "name": "Stuck", "groupBy": "member"}
    ).json()
    assert (changed["id"], changed["name"], changed["groupBy"]) == (1, "Stuck", "member")
    assert [v["name"] for v in client.get(f"/workspaces/{a}/kanban").json()["views"]] == ["Stuck"]
    b = ws(client, "Beta")
    assert client.get(f"/workspaces/{b}/board-views").json() == []  # each workspace its own
    assert client.delete(f"/workspaces/{a}/board-views/1").status_code == 204
    assert client.get(f"/workspaces/{a}/board-views").json() == []


def test_bulk_actions_go_to_hermes_batched(team: Any) -> None:
    client, core, runner, a = team
    cards = [kanban_board.create(core, a, f"Card {n}", "", "writer") for n in range(3)]
    old = [kanban_board.create(core, a, f"Old {n}", "", "writer") for n in range(2)]
    # The board's buttons: ONE Hermes CLI call for all the cards.
    before = len(_kanban_calls(runner, "archive"))
    r = client.post(f"/workspaces/{a}/kanban-bulk", json={"cards": old, "action": "archive"})
    assert r.json() == {"done": old, "failed": {}}
    assert len(_kanban_calls(runner, "archive")) == before + 1
    assert [_board(core, a)[c]["status"] for c in [*old, cards[0]]] == [
        "archived",
        "archived",
        "ready",
    ]
    # Assign and labels: one Hermes process (`hermes agos-bulk`) for every card.
    told: list[tuple[str, ...]] = []

    def walled_cli(key: str, *args: str, timeout: float = 60) -> str:
        told.append(args)
        ops = [json.loads(o) for o in args[1:]]
        found = guard_threads.apply_ops(ops, _FakeKb(_board(core, a)), None)
        return json.dumps(found)

    core.engine.walled_cli = walled_cli
    done = board_views.bulk(core, a, cards, "assign", member="lead")
    assert done == {"done": cards, "failed": {}} and len(told) == 1 and told[0][0] == "agos-bulk"
    assert {_board(core, a)[c]["assignee"] for c in cards} == {_profile(core, a, "lead")}
    tag = labels.create(core, a, "Q3")["id"]
    board_views.bulk(core, a, cards, "label", add=[tag])
    assert len(told) == 2
    assert all(rules.card_labels(_board(core, a)[c]["body"]) == [tag] for c in cards)
    # Mark done needs his words (Hermes refuses most cards without).
    with pytest.raises(Exception, match="what was done"):
        board_views.bulk(core, a, cards, "done")
    # No agos-bulk (an older plugin): one Hermes call per card, same result.

    def refused(key: str, *args: str, timeout: float = 60) -> str:
        raise EngineError("unknown command")

    core.engine.walled_cli = refused
    calls = len(_kanban_calls(runner, "assign"))
    assert board_views.bulk(core, a, cards, "assign", member="writer")["done"] == cards
    assert len(_kanban_calls(runner, "assign")) == calls + 3


class _FakeKb:
    """Hermes's kanban_db writers over the fake board (what agos-bulk calls)."""

    def __init__(self, cards: dict[str, dict[str, Any]]) -> None:
        self.cards = cards

    def assign_task(self, _conn: Any, card: str, profile: str | None) -> bool:
        if card not in self.cards:
            return False
        self.cards[card]["assignee"] = profile
        return True

    def edit_task(self, _conn: Any, card: str, *, body: str) -> bool:
        if card not in self.cards:
            return False
        self.cards[card]["body"] = body
        return True


# ---- the plugin side ------------------------------------------------------------------


def test_the_guard_tells_agos_only_of_a_landed_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[Any, ...]] = []

    class Now:
        def __init__(self, target: Any, args: tuple[Any, ...], **_: Any) -> None:
            self.target, self.args = target, args

        def start(self) -> None:
            self.target(*self.args)

    monkeypatch.setattr("threading.Thread", Now)

    def post(*a: Any) -> None:
        posted.append(a)

    ok = json.dumps({"ok": True, "task_id": "t_1", "comment_id": 7})
    assert guard_threads.commented("kanban_comment", {"task_id": "t_1"}, ok, post=post)
    assert posted == [("card-comment", {"card": "t_1", "comment": 7}, 30)]
    assert not guard_threads.commented("kanban_show", {"task_id": "t_1"}, ok, post=post)
    assert not guard_threads.commented("kanban_comment", {}, '{"error": "no"}', post=post)
    assert len(posted) == 1
    # agos_label goes to the bridge with the member.
    asked: list[Any] = []

    def ask(*a: Any) -> dict[str, Any]:
        asked.append(a)
        return {"ok": True}

    out = guard_threads.label_tool(
        {"action": "add", "card": "t_1", "labels": ["Urgent"]}, member="lead", post=ask
    )
    assert json.loads(out) == {"ok": True}
    assert asked[0][:2] == (
        "labels",
        {"member": "lead", "action": "add", "card": "t_1", "labels": ["Urgent"]},
    )
    # agos-bulk: one failing card never stops the others.
    cards = {"t_1": {"assignee": None}, "t_2": {"assignee": None}}
    kb = _FakeKb(cards)

    def boom(_c: Any, card: str, profile: str | None) -> bool:
        if card == "t_2":
            raise RuntimeError("running under a claim")
        return _FakeKb.assign_task(kb, _c, card, profile)

    kb_mod = types.SimpleNamespace(assign_task=boom, edit_task=kb.edit_task)
    found = guard_threads.apply_ops(
        [
            {"op": "assign", "card": "t_2", "to": "x"},
            {"op": "assign", "card": "t_1", "to": "x"},
            {"op": "body", "card": "t_9", "body": "b"},
        ],
        kb_mod,
        None,
    )
    assert found["done"] == ["t_1"] and set(found["failed"]) == {"t_2", "t_9"}
