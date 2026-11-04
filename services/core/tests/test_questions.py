"""An agent's typed question to the owner (ask, confirm, checkbox, choice, verdicts,
suggest_tasks) is a Hermes Kanban card blocked for him; AGOS writes it for the
agent's agos_ask_owner tool, the owner answers from the Inbox (or a Telegram
button), the answer lives on the card and the card goes on as its continuation
says."""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_library import env, ws  # noqa: F401 - fixture
from test_proposals import _board, _comments, _profile

from agos_core.actions import inbox, kanban_asks, questions
from agos_core.engine import questions as rules


@pytest.fixture
def team(env: Any) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    cofounder_chat(core, a)
    return client, core, runner, a


def _card(core: Any, a: str, card: str) -> dict[str, Any]:
    found: dict[str, Any] = core.engine.runner.kanban[_profile(core, a)][card]
    return found


def _blocked_on_board(core: Any, a: str, card: str, body: str, assignee: str = "") -> None:
    """What the board holds after Hermes's block (AGOS's read-only look)."""
    db = _board(core, a)
    db.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?, 'Q', ?, ?, 'blocked', 'needs_input')",
        (card, body, assignee or None),
    )
    db.execute(
        "INSERT INTO task_events (task_id, kind, payload) VALUES (?, 'blocked', ?)",
        (card, json.dumps({"kind": "needs_input", "reason": rules.BLOCK_REASON})),
    )
    db.commit()
    db.close()


# ---- the block format ---------------------------------------------------------------------


def test_the_question_block_is_read_like_a_proposal_and_typed_per_kind() -> None:
    body = "Context first.\n\n" + rules.block(
        "choice", {"question": "Which tone?", "options": ["Formal", "Playful"]}, "none", "t_9"
    )
    found = rules.parse(body)
    assert found is not None and found["kind"] == "choice" and found["continuation"] == "none"
    assert found["from"] == "t_9"
    assert found["payload"]["options"] == [
        {"id": "formal", "label": "Formal"},
        {"id": "playful", "label": "Playful"},
    ]
    assert rules.parse('```agos-question\n{"kind": "nuke", "payload": {}}\n```') is None
    assert rules.parse("```agos-proposal\n{}\n```") is None
    # Ids given by the agent are kept when they are usable; duplicates get a suffix.
    cleaned = rules.clean(
        "checkbox", {"question": "q", "options": [{"id": "a", "label": "A"}, "A"]}
    )
    assert [o["id"] for o in cleaned["options"]] == ["a", "a-2"]
    assert rules.problems(
        "choice", rules.clean("choice", {"question": "q", "options": ["one"]})
    ) == ["options needs at least two entries"]
    assert rules.problems("ask", {"question": ""}) == ["question (the words) is missing"]
    assert rules.read_marker(rules.marker("t_1", 1) + ' {"yes": true}') == ("t_1", 1)


def test_each_answer_kind_is_checked() -> None:
    options = rules.clean("choice", {"question": "q", "options": ["A", "B"]})
    assert rules.check_answer("ask", {}, {"text": " yes "}) == {"text": "yes"}
    with pytest.raises(ValueError):
        rules.check_answer("ask", {}, {"text": ""})
    assert rules.check_answer("confirm", {}, {"yes": "no", "note": "later"}) == {
        "yes": False,
        "note": "later",
    }
    with pytest.raises(ValueError):
        rules.check_answer("confirm", {}, {"yes": "maybe"})
    assert rules.check_answer("choice", options, {"selected": "b"}) == {"selected": "b"}
    with pytest.raises(ValueError):
        rules.check_answer("choice", options, {"selected": "c"})
    assert rules.check_answer("checkbox", options, {"selected": ["b", "a", "b"]}) == {
        "selected": ["b", "a"]
    }
    items = rules.clean("verdicts", {"question": "q", "items": ["Hook", "Outro"]})
    assert rules.check_answer(
        "verdicts", items, {"verdicts": {"hook": "approve", "outro": "reject"}}
    )
    with pytest.raises(ValueError):
        rules.check_answer("verdicts", items, {"verdicts": {"hook": "approve"}})
    tasks = rules.clean("suggest_tasks", {"tasks": [{"title": "A"}, {"title": "B"}]})
    assert rules.check_answer("suggest_tasks", tasks, {"accepted": [1, 1]}) == {"accepted": [1]}
    with pytest.raises(ValueError):
        rules.check_answer("suggest_tasks", tasks, {"accepted": [2]})
    assert "The owner picked: B." in rules.answer_text("choice", options, {"selected": "b"})


# ---- asking ---------------------------------------------------------------------------------


def test_the_tool_writes_the_card_the_parser_reads_and_records_the_ask(team: Any) -> None:
    client, core, runner, a = team
    made = questions.ask(
        core,
        a,
        "editor",
        "confirm",
        {"question": "Publish the draft today?"},
        "I think it's ready.",
    )
    card = made["card"]
    held = _card(core, a, card)
    # Created by and assigned to the asker, born blocked (the dispatcher never sees it
    # ready), then typed needs_input with the question's reason.
    assert held["assignee"] == "a-editor" and held["status"] == "blocked"
    made_call = next(c for c in runner.calls if "kanban" in c and "create" in c)
    assert made_call[made_call.index("--initial-status") + 1] == "blocked"
    assert made_call[made_call.index("--created-by") + 1] == "a-editor"
    block = next(c for c in runner.calls if "kanban" in c and "block" in c and card in c)
    assert block[-1] == rules.BLOCK_REASON
    parsed = rules.parse(str(held["body"]))
    assert parsed is not None and parsed["kind"] == "confirm"
    assert parsed["payload"]["question"] == "Publish the draft today?"
    assert str(held["body"]).startswith("I think it's ready.")
    [shown] = questions.waiting(core, a)
    assert (
        shown["id"] == made["ask_id"] and shown["kind"] == "confirm" and shown["member"] == "editor"
    )
    assert shown["memberName"] == "Editor" and shown["continuation"] == "wake_assignee"
    # Not a proposal, not an Autonomy ask; the Inbox counts it.
    assert kanban_asks.waiting(core, a) == []
    assert inbox.count(core, a) == 1
    r = client.get(f"/workspaces/{a}/inbox")
    assert r.status_code == 200 and r.json()["count"] == 1
    [item] = r.json()["items"]
    assert item["type"] == "question" and item["question"]["kind"] == "confirm"
    # The hook then tells AGOS the block landed: nothing new (one row).
    _blocked_on_board(core, a, card, str(held["body"]), "a-editor")
    assert kanban_asks.settle(core, a, card) is False
    assert len(questions.waiting(core, a)) == 1


def test_a_hand_blocked_question_card_is_recorded_from_the_hook(team: Any) -> None:
    _client, core, _runner, a = team
    body = rules.block("ask", {"question": "Which folder?"})
    raw = json.loads(core.engine._hermes(a, "kanban", "create", "Q", "--json", "--body", body))
    card = str(raw["id"])
    _blocked_on_board(core, a, card, body)
    assert kanban_asks.settle(core, a, card) is False
    [shown] = questions.waiting(core, a)
    assert shown["card"] == card and shown["kind"] == "ask" and shown["member"] == ""


def test_a_bad_question_is_refused_before_any_card(team: Any) -> None:
    from agos_core.actions.errors import ActionError

    _client, core, runner, a = team
    before = len(runner.calls)
    with pytest.raises(ActionError, match="options needs"):
        questions.ask(core, a, "", "choice", {"question": "q", "options": ["only one"]})
    with pytest.raises(ActionError, match="Unknown question kind"):
        questions.ask(core, a, "", "poll", {"question": "q"})
    with pytest.raises(ActionError, match="Not a member"):
        questions.ask(core, a, "ghost", "ask", {"question": "q"})
    assert len(runner.calls) == before


# ---- answering ------------------------------------------------------------------------------


def test_confirm_from_a_chat_writes_the_marker_and_unblocks_the_card(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(core, a, "editor", "confirm", {"question": "Publish?"})
    card, ask_id = made["card"], made["ask_id"]
    r = client.post(f"/workspaces/{a}/questions/{ask_id}", json={"answer": {"yes": True}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "answered" and r.json()["answer"] == {"yes": True}
    [comment] = _comments(core, a, card)
    assert comment.startswith(rules.marker(card, 1) + ' {"yes": true}')
    assert "The owner says YES." in comment
    assert _card(core, a, card)["status"] == "ready"  # wake_assignee: unblocked for the asker
    assert questions.waiting(core, a) == [] and inbox.count(core, a) == 0
    # The same answer again: nothing new.
    again = client.post(f"/workspaces/{a}/questions/{ask_id}", json={"answer": {"yes": True}})
    assert again.status_code == 200 and len(_comments(core, a, card)) == 1
    # Another answer after one: refused.
    other = client.post(f"/workspaces/{a}/questions/{ask_id}", json={"answer": {"yes": False}})
    assert other.status_code == 409, other.text
    # A wrong shape is a 400 with words.
    made2 = questions.ask(core, a, "", "confirm", {"question": "Again?"})
    bad = client.post(
        f"/workspaces/{a}/questions/{made2['ask_id']}", json={"answer": {"yes": "maybe"}}
    )
    assert bad.status_code == 400 and "yes or no" in bad.text


def test_a_question_asked_from_a_card_is_completed_so_hermes_wakes_that_card(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(
        core,
        a,
        "editor",
        "choice",
        {"question": "Tone?", "options": ["Formal", "Playful"]},
        asked_from="t_work",
    )
    card = made["card"]
    assert rules.parse(str(_card(core, a, card)["body"]))["from"] == "t_work"  # type: ignore[index]
    r = client.post(
        f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"selected": "playful"}}
    )
    assert r.status_code == 200, r.text
    held = _card(core, a, card)
    assert held["status"] == "done" and "The owner picked: Playful." in str(held["result"])
    assert held["result"].startswith("Tone?")


def test_continuation_none_completes_the_card_even_from_a_chat(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(core, a, "", "ask", {"question": "Budget?"}, continuation="none")
    r = client.post(f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"text": "500"}})
    assert r.status_code == 200
    assert _card(core, a, made["card"])["status"] == "done"
    assert "The owner answers: 500" in str(_card(core, a, made["card"])["result"])


def test_checkbox_and_verdicts_round_trip(team: Any) -> None:
    client, core, _runner, a = team
    boxes = questions.ask(
        core, a, "editor", "checkbox", {"question": "Which?", "options": ["Hook", "Outro", "Cut"]}
    )
    r = client.post(
        f"/workspaces/{a}/questions/{boxes['ask_id']}",
        json={"answer": {"selected": ["cut", "hook"]}},
    )
    assert r.status_code == 200 and r.json()["answer"]["selected"] == ["cut", "hook"]
    assert "The owner picked: Cut; Hook." in _comments(core, a, boxes["card"])[0]
    verdicts = questions.ask(
        core, a, "editor", "verdicts", {"question": "Keep?", "items": ["Hook", "Outro"]}
    )
    r = client.post(
        f"/workspaces/{a}/questions/{verdicts['ask_id']}",
        json={"answer": {"verdicts": {"hook": "approve", "outro": "reject"}, "note": "trim it"}},
    )
    assert r.status_code == 200
    [comment] = _comments(core, a, verdicts["card"])
    assert (
        "- Hook: approve" in comment and "- Outro: reject" in comment and "Note: trim it" in comment
    )


def test_suggested_tasks_the_owner_accepts_become_cards(team: Any) -> None:
    client, core, runner, a = team
    made = questions.ask(
        core,
        a,
        "editor",
        "suggest_tasks",
        {
            "question": "Next steps",
            "tasks": [
                {"title": "Write the hook", "body": "20 words", "member": "editor"},
                {"title": "Pick music", "member": "nobody-here"},
                {"title": "Export", "member": "cofounder"},
            ],
        },
    )
    r = client.post(
        f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"accepted": [0, 2]}}
    )
    assert r.status_code == 200, r.text
    cards = r.json()["answer"]["cards"]
    assert len(cards) == 2
    board = runner.kanban[_profile(core, a)]
    assert (
        board[cards[0]]["title"] == "Write the hook" and board[cards[0]]["assignee"] == "a-editor"
    )
    assert board[cards[0]]["body"] == "20 words"
    assert board[cards[1]]["title"] == "Export" and board[cards[1]]["assignee"] == "default"
    assert "Pick music" not in [c["title"] for c in board.values()]
    # Hermes's own dedup key: a replay would not make them twice.
    assert board[cards[0]]["key"] == f"agos-suggested:{made['card']}:0"
    assert "accepted 2 of 3 suggested tasks" in _comments(core, a, made["card"])[0]


def test_the_marker_on_the_card_wins_when_the_row_never_heard(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(core, a, "editor", "confirm", {"question": "Go?"})
    card = made["card"]
    # The comment landed (Hermes), AGOS's row did not hear (a cut between the two).
    _card(core, a, card)["comments"].append(
        {"author": "owner", "body": rules.marker(card, 1) + ' {"yes": false}\nThe owner says NO.'}
    )
    r = client.post(f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"yes": True}})
    assert r.status_code == 409
    [shown] = [q for q in _rows(core, a) if q["id"] == made["ask_id"]]
    assert shown["status"] == "answered" and json.loads(shown["result"]) == {"yes": False}


def _rows(core: Any, a: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in core.db.execute(
            "SELECT * FROM kanban_asks WHERE workspace_id = ? AND kind = 'question'", (a,)
        )
    ]


def test_a_replayed_block_of_an_answered_question_releases_the_card(team: Any) -> None:
    client, core, _runner, a = team
    made = questions.ask(core, a, "editor", "confirm", {"question": "Go?"})
    card = made["card"]
    client.post(f"/workspaces/{a}/questions/{made['ask_id']}", json={"answer": {"yes": True}})
    _card(core, a, card)["status"] = "blocked"  # a late block landed
    _blocked_on_board(core, a, card, str(_card(core, a, card)["body"]), "a-editor")
    assert kanban_asks.settle(core, a, card) is True
    assert _card(core, a, card)["status"] == "ready"


def test_telegram_buttons_answer_confirm_and_choice_only(team: Any) -> None:
    _client, core, _runner, a = team
    confirm = questions.ask(core, a, "editor", "confirm", {"question": "Go?"})
    assert (
        questions.answer_button(core, a, confirm["ask_id"], "no") == "Answered: the card goes on."
    )
    assert questions.answer_button(core, a, confirm["ask_id"], "yes") == "Already answered."
    assert json.loads(_rows(core, a)[0]["result"]) == {"yes": False}
    choice = questions.ask(core, a, "editor", "choice", {"question": "T?", "options": ["A", "B"]})
    assert questions.answer_button(core, a, choice["ask_id"], "b") == "Answered: the card goes on."
    free = questions.ask(core, a, "editor", "ask", {"question": "Why?"})
    from agos_core.actions.errors import ActionError

    with pytest.raises(ActionError, match="Inbox"):
        questions.answer_button(core, a, free["ask_id"], "x")
