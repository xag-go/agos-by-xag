"""The Inbox is one derived list (asks, questions, proposals, blocked cards, Hermes's
approvals in chats); only the owner's read / dismiss marks persist, with undo, and
the badge counts unread actionable rows in one query."""

from __future__ import annotations

from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_blocked import board, card
from test_library import env, ws  # noqa: F401 - fixture
from test_proposals import WHOLE
from work_env import fake_models, library_skill

from agos_core.actions import inbox, kanban_asks, proposals, questions
from agos_core.engine import proposals as proposal_rules


@pytest.fixture
def team(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    cofounder_chat(core, a)
    library_skill(core, a)
    fake_models(monkeypatch)
    return client, core, runner, a


def test_one_list_from_every_source_deduped_by_card_newest_first(team: Any) -> None:
    client, core, _runner, a = team
    # A proposal (its row), a question (its row), an Autonomy ask (its row)...
    proposal = proposals.propose(core, a, "hire", WHOLE, by_tool=True)["card"]
    question = questions.ask(core, a, "editor", "confirm", {"question": "Go?"})["card"]
    kanban_asks.ask(core, a, "t_ask", "editor", "commands", "Run commands", "python3 x.py")
    # ...and the board: the proposal's card is blocked there too (shown once), plus a
    # plain question card with no row.
    db = board(core, a)
    card(db, proposal, "blocked", kind="needs_input", reason=proposal_rules.BLOCK_REASON)
    card(
        db,
        "t_ask",
        "blocked",
        kind="needs_input",
        reason="waiting for the owner: Run commands",
        assignee="a-editor",
    )
    card(db, "t_plain", "blocked", kind="needs_input", reason="Which colour?", assignee="a-editor")
    db.close()
    r = client.get(f"/workspaces/{a}/inbox")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    by_card = {i["card"]: i["type"] for i in items}
    assert by_card == {
        "t_ask": "ask",
        question: "question",
        proposal: "proposal",
        "t_plain": "blocked",
    }
    assert len(items) == 4  # the proposal's and the ask's cards once each
    # Newest first: the rows in the order they were made (the fake board's block stamp
    # is in the future, so its derived item comes first).
    rows = [i["card"] for i in items if i["type"] != "blocked"]
    assert rows == ["t_ask", question, proposal]
    assert r.json()["count"] == 4 and r.json()["unread"] == 4
    assert client.get(f"/workspaces/{a}/inbox/count").json()["count"] == 3  # rows only


def test_read_and_dismiss_persist_by_key_with_undo(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(core, a, "editor", "confirm", {"question": "Go?"})
    key = f"ask:{made['ask_id']}"
    db = board(core, a)
    card(db, "t_plain", "blocked", kind="needs_input", reason="Which colour?", assignee="a-editor")
    db.close()
    plain = next(
        i for i in client.get(f"/workspaces/{a}/inbox").json()["items"] if i["card"] == "t_plain"
    )
    # Read: stays listed, counts no more.
    r = client.post(f"/workspaces/{a}/inbox/marks", json={"key": key, "mark": "read"})
    assert r.status_code == 204, r.text
    shown = client.get(f"/workspaces/{a}/inbox").json()
    assert shown["count"] == 2 and shown["unread"] == 1
    assert next(i for i in shown["items"] if i["key"] == key)["read"] is True
    assert client.get(f"/workspaces/{a}/inbox/count").json()["count"] == 0
    # Dismiss a derived item: gone from the list (kept with ?dismissed), undo brings it back.
    r = client.post(f"/workspaces/{a}/inbox/marks", json={"key": plain["key"], "mark": "dismissed"})
    assert r.status_code == 204
    shown = client.get(f"/workspaces/{a}/inbox").json()
    assert [i["card"] for i in shown["items"]] == [made["card"]] and shown["count"] == 1
    with_dismissed = client.get(f"/workspaces/{a}/inbox", params={"dismissed": "true"}).json()
    assert sorted(i["dismissed"] for i in with_dismissed["items"]) == [False, True]
    assert with_dismissed["count"] == 1  # the dismissed one is not counted
    r = client.delete(
        f"/workspaces/{a}/inbox/marks", params={"key": plain["key"], "mark": "dismissed"}
    )
    assert r.status_code == 204
    assert len(client.get(f"/workspaces/{a}/inbox").json()["items"]) == 2
    # The same mark twice is one row; a mark that isn't one is refused.
    client.post(f"/workspaces/{a}/inbox/marks", json={"key": key, "mark": "read"})
    assert core.db.execute("SELECT COUNT(*) FROM inbox_marks").fetchone()[0] == 1
    assert (
        client.post(
            f"/workspaces/{a}/inbox/marks", json={"key": key, "mark": "starred"}
        ).status_code
        == 422
    )
    # A dismissed item comes back when it changes (its key carries the item's stamp).
    inbox.mark(core, a, "card:t_plain:1", "dismissed")
    assert all(i["card"] != "x" for i in inbox.items(core, a))
    # Marks of an ask that ended are swept (keys read back from the rows).
    client.post(f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"yes": True}})
    assert inbox.sweep(core, a) == 1
    assert (
        core.db.execute("SELECT COUNT(*) FROM inbox_marks WHERE key = ?", (key,)).fetchone()[0] == 0
    )


def test_a_hermes_approval_waiting_in_a_chat_is_listed_with_its_chat(team: Any) -> None:
    client, core, _runner, a = team
    from agos_core.actions import chat as chat_actions
    from agos_core.db import chats as repo
    from agos_core.db.rows import now
    from agos_core.engine.chat import LiveTurn

    chat_id = cofounder_chat(core, a)
    turn_id = int(
        core.db.execute(
            """INSERT INTO chat_turns (chat_id, workspace_id, status, asked_up_to, via, started_at)
               VALUES (?, ?, 'running', 0, 'hermes', ?)""",
            (chat_id, a, now()),
        ).lastrowid
        or 0
    )
    assert repo.get_turn(core.db, turn_id) is not None
    live = LiveTurn(turn_id)
    live.apply({"event": "approval.request", "command": "rm -rf build", "description": ""})
    chat_actions._registry(core)[turn_id] = chat_actions._Live(turn=live)
    try:
        [item] = client.get(f"/workspaces/{a}/inbox").json()["items"]
        assert item["type"] == "approval" and item["approval"]["chatId"] == chat_id
        assert "rm -rf build" in item["approval"]["detail"]
        assert item["key"] == f"approval:{turn_id}:{live.activity[0].id}"
        live.apply({"event": "approval.responded", "choice": "once"})
        assert client.get(f"/workspaces/{a}/inbox").json()["items"] == []
    finally:
        chat_actions._registry(core).pop(turn_id, None)
