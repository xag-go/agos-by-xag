"""Blocked cards with an owner: a card a member blocks for a teammate is handed to
that agent through Hermes; one for the owner stays for his Inbox. The state of
every waiting card (covered / stalled / needs_attention) is derived from one read
of Hermes's board."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_library import env, ws  # noqa: F401 - fixture
from test_proposals import _comments, _profile

from agos_core.actions import blocked, kanban_asks
from agos_core.engine import blocks as rules


@pytest.fixture
def team(env: Any) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    add_agent(client, a, "writer")
    cofounder_chat(core, a)
    return client, core, runner, a


def board(core: Any, a: str) -> sqlite3.Connection:
    """Hermes's board, the columns AGOS reads (hermes_cli/kanban_db.py tasks,
    task_events, task_links)."""
    from agos_core.actions import agent_profiles

    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,"
        " assignee TEXT, status TEXT, block_kind TEXT, current_run_id INTEGER);"
        "CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY, task_id TEXT,"
        " kind TEXT, payload TEXT, created_at INTEGER);"
        "CREATE TABLE IF NOT EXISTS task_links (parent_id TEXT, child_id TEXT);"
    )
    return db


def card(
    db: sqlite3.Connection,
    card_id: str,
    status: str,
    *,
    kind: str = "",
    reason: str = "",
    assignee: str = "",
    running: bool = False,
    parents: tuple[str, ...] = (),
    title: str = "",
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?, ?, '', ?, ?, ?, ?)",
        (card_id, title or card_id, assignee or None, status, kind or None, 1 if running else None),
    )
    if reason or kind:
        db.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, 1800000000)",
            (
                card_id,
                "dependency_wait" if kind == "dependency" else "blocked",
                json.dumps({"kind": kind or None, "reason": reason}),
            ),
        )
    for parent in parents:
        db.execute("INSERT INTO task_links VALUES (?, ?)", (parent, card_id))
    db.commit()


def _runner_card(core: Any, a: str, card_id: str, assignee: str, status: str = "blocked") -> None:
    cards = core.engine.runner.kanban.setdefault(_profile(core, a), {})
    cards[card_id] = {
        "id": card_id,
        "title": card_id,
        "body": "",
        "assignee": assignee,
        "status": status,
        "comments": [],
        "created_at": 1,
    }


# ---- the descriptor -------------------------------------------------------------------------


def test_the_reason_says_who_must_act() -> None:
    assert rules.descriptor("waiting for @editor: review the hook") == {
        "owner": "editor",
        "action": "review the hook",
    }
    assert rules.descriptor("Waiting for @Co-Founder: pick the brand")["owner"] == "cofounder"
    assert rules.descriptor("waiting for @manager: x")["owner"] == "cofounder"  # the old name
    assert rules.descriptor("waiting for @owner: a yes")["owner"] == "owner"
    assert rules.descriptor("waiting for the owner: Run commands") == {
        "owner": "owner",
        "action": "Run commands",
    }
    assert rules.descriptor("Which colour?") == {"owner": "owner", "action": "Which colour?"}
    assert rules.agent_reason("writer", " send the draft ") == "waiting for @writer: send the draft"
    assert rules.read_route_marker(rules.route_marker("t_1", "writer")) == ("t_1", "writer")


# ---- routing --------------------------------------------------------------------------------


def test_a_card_blocked_for_a_teammate_is_handed_over_through_hermes_once(team: Any) -> None:
    _client, core, runner, a = team
    db = board(core, a)
    card(
        db,
        "t_1",
        "blocked",
        kind="needs_input",
        reason="waiting for @writer: send the draft",
        assignee="a-editor",
    )
    db.close()
    _runner_card(core, a, "t_1", "a-editor")
    assert kanban_asks.settle(core, a, "t_1") is True
    held = runner.kanban[_profile(core, a)]["t_1"]
    # The comment names the asker and what is needed, then the card is the writer's, ready.
    [comment] = _comments(core, a, "t_1")
    assert comment.startswith(rules.route_marker("t_1", "writer"))
    assert "Editor waits for you" in comment and "send the draft" in comment
    assert "waiting for @editor:" in comment  # how to hand it back
    assert held["assignee"] == "a-writer" and held["status"] == "ready"
    # The hook fires again (a replay): nothing is done twice.
    held["status"] = "blocked"
    assert kanban_asks.settle(core, a, "t_1") is True
    assert len(_comments(core, a, "t_1")) == 1 and held["status"] == "blocked"
    # Nothing recorded in AGOS: Hermes's card carries it all.
    assert core.db.execute("SELECT COUNT(*) FROM kanban_asks").fetchone()[0] == 0


def test_a_card_blocked_for_the_cofounder_goes_to_its_profile(team: Any) -> None:
    _client, core, runner, a = team
    db = board(core, a)
    card(
        db,
        "t_2",
        "blocked",
        kind="needs_input",
        reason="waiting for @cofounder: pick the brand",
        assignee="a-writer",
    )
    db.close()
    _runner_card(core, a, "t_2", "a-writer")
    assert kanban_asks.settle(core, a, "t_2") is True
    held = runner.kanban[_profile(core, a)]["t_2"]
    assert held["assignee"] == "default" and held["status"] == "ready"
    assert "Writer waits for you" in _comments(core, a, "t_2")[0]


def test_a_card_blocked_for_the_owner_or_an_unknown_name_stays_blocked(team: Any) -> None:
    client, core, runner, a = team
    db = board(core, a)
    card(
        db,
        "t_3",
        "blocked",
        kind="needs_input",
        reason="waiting for @owner: a yes",
        assignee="a-editor",
    )
    card(
        db,
        "t_4",
        "blocked",
        kind="needs_input",
        reason="waiting for @ghost: anything",
        assignee="a-editor",
    )
    card(db, "t_5", "blocked", kind="needs_input", reason="Which colour?", assignee="a-editor")
    db.close()
    for c in ("t_3", "t_4", "t_5"):
        _runner_card(core, a, c, "a-editor")
        assert kanban_asks.settle(core, a, c) is False
        assert runner.kanban[_profile(core, a)][c]["status"] == "blocked"
    # His Inbox shows them, derived from the board (no row), newest first, deduped by card.
    r = client.get(f"/workspaces/{a}/inbox")
    assert r.status_code == 200, r.text
    items = {i["card"]: i for i in r.json()["items"]}
    assert set(items) == {"t_3", "t_4", "t_5"}
    assert items["t_3"]["type"] == "blocked" and items["t_3"]["blocked"]["owner"] == "owner"
    assert items["t_3"]["blocked"]["action"] == "a yes" and items["t_3"]["memberName"] == "Editor"
    assert items["t_5"]["blocked"]["reason"] == "Which colour?"
    assert items["t_3"]["key"].startswith("card:t_3:")
    assert r.json()["count"] == 3 and r.json()["unread"] == 3
    # The badge counts AGOS's rows only (one query, no board): none here.
    assert client.get(f"/workspaces/{a}/inbox/count").json()["count"] == 0


# ---- derived attention ----------------------------------------------------------------------


def test_attention_is_derived_from_the_blocker_chain() -> None:
    cards: dict[str, dict[str, Any]] = {
        "owner": {
            "status": "blocked",
            "block_kind": "needs_input",
            "reason": "waiting for the owner: x",
        },
        "routed": {
            "status": "blocked",
            "block_kind": "needs_input",
            "reason": "waiting for @writer: y",
        },
        "cap": {"status": "blocked", "block_kind": "capability", "reason": "no browser"},
        "untyped": {"status": "blocked", "block_kind": "", "reason": ""},
        "live": {"status": "running", "block_kind": "", "reason": "", "running": True},
        "waits_live": {"status": "todo", "block_kind": "dependency", "reason": "parent"},
        "queued": {"status": "ready", "block_kind": "", "reason": ""},
        "waits_queued": {"status": "todo", "block_kind": "dependency", "reason": "parent"},
        "waits_owner": {"status": "todo", "block_kind": "dependency", "reason": "parent"},
        "waits_routed": {"status": "todo", "block_kind": "dependency", "reason": "parent"},
        "done": {"status": "done", "block_kind": "", "reason": ""},
        "waits_done": {"status": "todo", "block_kind": "", "reason": ""},
        "deep": {"status": "todo", "block_kind": "dependency", "reason": "parent"},
    }
    links = [
        ("live", "waits_live"),
        ("queued", "waits_queued"),
        ("owner", "waits_owner"),
        ("routed", "waits_routed"),
        ("done", "waits_done"),
        ("waits_owner", "deep"),
    ]
    found = rules.attention(cards, links)
    states = {k: v["state"] for k, v in found.items()}
    assert states["owner"] == "needs_attention" and found["owner"]["why"] == "waits for you"
    assert states["routed"] == "covered" and found["routed"]["why"] == "waits for @writer"
    assert states["cap"] == "needs_attention" and "lacks" in found["cap"]["why"]
    assert states["untyped"] == "needs_attention"
    assert states["waits_live"] == "covered" and states["waits_queued"] == "covered"
    assert states["waits_owner"] == "needs_attention" and found["waits_owner"]["stalled"] is True
    assert found["waits_owner"]["blockers"] == ["owner"]
    assert states["waits_routed"] == "covered"  # the writer will answer: it moves
    assert states["deep"] == "needs_attention" and found["deep"]["stalled"] is True
    assert "waits_done" not in found and "live" not in found and "queued" not in found


def test_the_board_shows_each_waiting_cards_state_from_one_query(team: Any) -> None:
    client, core, _runner, a = team
    db = board(core, a)
    card(
        db,
        "p",
        "blocked",
        kind="needs_input",
        reason="waiting for the owner: pick",
        assignee="a-editor",
        title="Pick",
    )
    card(
        db,
        "c",
        "todo",
        kind="dependency",
        reason="parent",
        assignee="a-writer",
        parents=("p",),
        title="Write",
    )
    card(db, "r", "running", assignee="a-writer", running=True, title="Run")
    card(
        db,
        "d",
        "todo",
        kind="dependency",
        reason="parent",
        assignee="a-editor",
        parents=("r",),
        title="After",
    )
    db.close()
    found = blocked.attention(core, a)
    assert found["p"]["state"] == "needs_attention" and found["p"]["title"] == "Pick"
    assert found["c"]["state"] == "needs_attention" and found["c"]["stalled"] is True
    assert found["d"]["state"] == "covered" and found["d"]["blockers"] == ["r"]
    assert "r" not in found
    # The stalled card is an Inbox item of its own (attention); the owner's block too.
    for c, status in (("p", "blocked"), ("c", "todo"), ("r", "running"), ("d", "todo")):
        _runner_card(core, a, c, "a-editor", status)
    items = {i["card"]: i for i in client.get(f"/workspaces/{a}/inbox").json()["items"]}
    assert items["p"]["type"] == "blocked" and items["c"]["type"] == "attention"
    assert items["c"]["blocked"]["stalled"] is True and "d" not in items
    # The Board carries the same state on each card.
    shown = {c["id"]: c for c in client.get(f"/workspaces/{a}/kanban").json()["cards"]}
    assert shown["p"]["attention"] == "needs_attention" and shown["d"]["attention"] == "covered"
    assert shown["r"]["attention"] == "" and "waits on r" in shown["d"]["attentionWhy"]
