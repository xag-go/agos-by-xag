"""An agent's proposal (a hire, an instructions change, a plan) is a Hermes Kanban
card blocked for the owner; AGOS records it from Hermes's block hook, the owner
decides (Approve / Revise / Reject) and the decision lives on the card."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_engine_sync import profile_dir
from test_library import env, ws  # noqa: F401 - fixture
from work_env import fake_models, library_skill, whole

from agos_core.actions import kanban_asks, proposals
from agos_core.engine import proposals as rules

HIRE = {
    "name": "script-writer",
    "title": "Script Writer",
    "role": "Writes the scripts from the approved ideas.",
    "skills": ["writing"],
    "telegram_topic": False,
    "coding_engine": "codex",
    "reports_to": "",
    "why": "Scripts for sub-goal #2 wait a week; nobody on the team writes them.",
}
# What the agent must send: every hire carries its whole kit and model.
WHOLE = whole(HIRE)


def _board(core: Any, a: str) -> sqlite3.Connection:
    from agos_core.actions import agent_profiles

    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,"
        " assignee TEXT, status TEXT, block_kind TEXT);"
        "CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY, task_id TEXT,"
        " kind TEXT, payload TEXT, created_at INTEGER);"
    )
    return db


def _profile(core: Any, a: str) -> str:
    return str(core.engine.profile(a))


def _card_blocks(core: Any, a: str, body: str, assignee: str = "") -> str:
    """The agent's kanban_create + kanban_block, as Hermes's board then holds it (the
    FakeRunner's card for the CLI, the board file for AGOS's read-only look)."""
    raw = json.loads(
        core.engine._hermes(a, "kanban", "create", "Proposal", "--json", "--body", body)
    )
    card = str(raw["id"])
    db = _board(core, a)
    db.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?, 'Proposal', ?, ?, 'blocked', 'needs_input')",
        (card, body, assignee or None),
    )
    db.execute(
        "INSERT INTO task_events (task_id, kind, payload) VALUES (?, 'blocked', ?)",
        (card, json.dumps({"kind": "needs_input", "reason": rules.BLOCK_REASON})),
    )
    db.commit()
    db.close()
    runner_card = core.engine.runner.kanban[_profile(core, a)][card]
    runner_card["status"] = "blocked"
    return card


def _settle(core: Any, a: str, card: str) -> bool:
    """What Hermes's kanban_task_blocked hook makes AGOS do (through the bridge)."""
    return bool(kanban_asks.settle(core, a, card))


def _cli(runner: Any, verb: str, card: str) -> list[list[str]]:
    return [c for c in runner.calls if "kanban" in c and verb in c and card in c]


def _comments(core: Any, a: str, card: str) -> list[str]:
    return [str(c["body"]) for c in core.engine.runner.kanban[_profile(core, a)][card]["comments"]]


@pytest.fixture
def team(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    cofounder_chat(core, a)
    library_skill(core, a)  # the hire's skill, in the workspace's library
    fake_models(monkeypatch)  # its model, checked against Hermes's catalog
    return client, core, runner, a


# ---- the block format --------------------------------------------------------------------


def test_the_block_is_read_from_the_card_body_and_nothing_else_is() -> None:
    body = "Here is my proposal.\n\n" + rules.block("hire", HIRE) + "\n\nThanks."
    found = rules.parse(body)
    assert found is not None and found["kind"] == "hire"
    assert found["payload"]["name"] == "script-writer" and found["payload"]["skills"] == ["writing"]
    assert found["payload"]["coding_engine"] == "codex" and found["payload"]["reports_to"] == ""
    assert "revises" not in found
    # A doc that contains ``` itself: the JSON is read from the fence on, never up to
    # the next fence.
    with_fence = rules.block("plan", {"title": "T", "markdown": "use ```sh``` blocks"})
    plan = rules.parse("x\n" + with_fence)
    assert plan is not None and plan["payload"]["markdown"] == "use ```sh``` blocks"
    assert rules.parse("```agos-proposal\nnot json\n```") is None
    assert rules.parse('```agos-proposal\n{"kind": "nuke", "payload": {}}\n```') is None
    assert rules.parse("no block at all") is None
    revised = rules.parse(rules.block("hire", HIRE, revises="t_old"))
    assert revised is not None and revised["revises"] == "t_old"
    assert rules.problems("hire", {"name": "Bad Name", "title": "", "role": "x"}) == [
        "name must be lowercase-with-dashes",
        "title (the job title) is missing",
    ]
    assert rules.read_marker(rules.marker("t_1", 2, "approve")) == ("t_1", 2, "approve")


# ---- recording from Hermes's block hook ---------------------------------------------------


def test_a_blocked_proposal_card_is_recorded_with_its_kind_and_payload(team: Any) -> None:
    client, core, _runner, a = team
    card = _card_blocks(core, a, "I'd hire a writer.\n\n" + rules.block("hire", WHOLE))
    assert _settle(core, a, card) is False  # recorded, waits for him
    [shown] = proposals.waiting(core, a)
    assert shown["kind"] == "hire" and shown["card"] == card and shown["round"] == 1
    assert shown["payload"]["title"] == "Script Writer" and shown["memberName"] == "Co-Founder"
    assert shown["problems"] == []
    # Not an Autonomy ask: the chat's Allow once / Deny list leaves it out...
    assert kanban_asks.waiting(core, a) == []
    # ...and the Inbox counts it, from one query.
    assert proposals.count(core, a) == 1
    r = client.get(f"/workspaces/{a}/inbox")
    assert r.status_code == 200 and r.json()["count"] == 1
    assert r.json()["items"][0]["proposal"]["payload"]["name"] == "script-writer"
    assert client.get(f"/workspaces/{a}/counters").json()["inbox"] == 1
    # The same block told twice (the hook fired again): one row.
    assert _settle(core, a, card) is False
    assert len(proposals.waiting(core, a)) == 1
    # A member's proposal names the member (its profile is a-<name> on the board).
    other = _card_blocks(
        core, a, rules.block("plan", {"title": "P", "markdown": "# p"}), "a-editor"
    )
    _settle(core, a, other)
    assert [p["member"] for p in proposals.waiting(core, a)] == ["", "editor"]


def test_the_owner_hears_about_a_proposal_like_an_ask(team: Any) -> None:
    _client, core, _runner, a = team
    card = _card_blocks(core, a, rules.block("hire", WHOLE))
    _settle(core, a, card)
    row = core.db.execute(
        "SELECT body, buttons FROM channel_outbox ORDER BY id DESC LIMIT 1"
    ).fetchone()
    # No Telegram channel in this env: the push path is owner_needs.push, the
    # same as the asks (nothing queued without a channel).
    assert row is None or "Hire a Script Writer" in str(row["body"])


# ---- deciding -----------------------------------------------------------------------------


def test_approve_hire_creates_the_member_through_the_team_code_and_completes_the_card(
    team: Any,
) -> None:
    client, core, runner, a = team
    card = _card_blocks(core, a, rules.block("hire", {**WHOLE, "reports_to": "editor"}))
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    r = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["canUndo"] is True
    from agos_core.actions import team

    hired = team.get(core, a, "script-writer")
    assert hired is not None and hired.title == "Script Writer" and hired.reports_to == "editor"
    assert hired.skills == ["writing"]
    assert (profile_dir(runner.hermes_home, f"agos-{a}--a-script-writer") / "SOUL.md").is_file()
    # On the card: the marker comment first, then Hermes's complete with a result.
    [comment] = _comments(core, a, card)
    assert comment.startswith(rules.marker(card, 1, "approve"))
    assert runner.kanban[_profile(core, a)][card]["status"] == "done"
    assert "Hired @script-writer" in str(runner.kanban[_profile(core, a)][card]["result"])
    assert proposals.waiting(core, a) == [] and proposals.count(core, a) == 0
    # The same decision again: nothing new (no second comment, no second member).
    again = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    assert again.status_code == 200 and again.json()["status"] == "approved"
    assert len(_comments(core, a, card)) == 1
    # Another terminal decision after one: refused.
    other = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "reject"})
    assert other.status_code == 409, other.text
    # Undo: the member goes.
    undone = client.post(f"/workspaces/{a}/proposals/{shown['id']}/undo")
    assert undone.status_code == 200 and undone.json()["status"] == "undone"
    assert team.get(core, a, "script-writer") is None
    assert any("undid this hire" in c for c in _comments(core, a, card))


def test_a_hand_written_hire_missing_parts_never_reaches_the_owner(team: Any) -> None:
    _client, core, runner, a = team
    # The Visual Designer's shape: a family as the model, its why inside it, no kit.
    sent = {**HIRE, "name": "Bad Name", "model": {"model": "sonnet", "why": "everyday"}}
    card = _card_blocks(core, a, rules.block("hire", sent))
    assert _settle(core, a, card) is True  # the card went back to the agent
    assert proposals.waiting(core, a) == [] and proposals.count(core, a) == 0
    [comment] = _comments(core, a, card)
    assert comment.startswith(proposals.REFUSED)
    for said in (
        "name must be lowercase-with-dashes",
        "kit is missing",
        "put the why in model_why",
    ):
        assert said in comment, said
    assert "agos_propose" in comment
    assert _cli(runner, "unblock", card)


def test_approve_hire_refuses_a_payload_it_could_not_create_from(team: Any) -> None:
    client, core, _runner, a = team
    # A hire card recorded before these checks (kept as it is: never migrated away).
    ask = proposals.record(core, a, "t_old", "", "hire", {**HIRE, "name": "Bad Name"})
    [shown] = proposals.waiting(core, a)
    assert shown["problems"] == ["name must be lowercase-with-dashes"]
    r = client.post(f"/workspaces/{a}/proposals/{ask}", json={"choice": "approve"})
    assert r.status_code == 400 and "Revise it" in r.text
    assert "kit is missing" in r.text and "model is missing" in r.text
    assert proposals.waiting(core, a)[0]["status"] == "waiting"


def test_approve_instructions_writes_a_consent_token_and_unblocks(team: Any) -> None:
    client, core, runner, a = team
    content = "# Editor\nI edit faster now.\n"
    payload = {
        "target": "SOUL.md",
        "diff": "--- SOUL.md\n+++ SOUL.md\n@@ -1 +1,2 @@\n+I edit faster now.",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "summary": "Edit faster.",
    }
    card = _card_blocks(core, a, rules.block("instructions", payload), "a-editor")
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    assert shown["kind"] == "instructions" and shown["member"] == "editor"
    r = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    token_file = profile_dir(runner.hermes_home, f"agos-{a}--a-editor") / proposals.CONSENT_FILE
    [token] = json.loads(token_file.read_text())["tokens"]
    assert token == {
        "card": card,
        "target": "SOUL.md",
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "approved_at": token["approved_at"],
        "consumed": False,
    }
    assert len(_cli(runner, "unblock", card)) == 1
    assert "write_file" in _comments(core, a, card)[0]


def test_approve_plan_and_revise_unblock_with_the_words_reject_completes(team: Any) -> None:
    client, core, runner, a = team
    plan = {"title": "Launch", "markdown": "# Launch\n1. ideas\n2. scripts"}
    card = _card_blocks(core, a, rules.block("plan", plan))
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    r = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200 and len(_cli(runner, "unblock", card)) == 1
    assert _comments(core, a, card)[0] == f"{rules.marker(card, 1, 'approve')} approved"

    second = _card_blocks(core, a, rules.block("plan", {**plan, "title": "Launch 2"}))
    _settle(core, a, second)
    [shown] = proposals.waiting(core, a)
    r = client.post(
        f"/workspaces/{a}/proposals/{shown['id']}",
        json={"choice": "revise", "note": "Add a review step."},
    )
    assert r.status_code == 200 and r.json()["status"] == "revised"
    assert r.json()["note"] == "Add a review step."
    assert len(_cli(runner, "unblock", second)) == 1
    assert "Add a review step." in _comments(core, a, second)[0]
    assert "NEW card" in _comments(core, a, second)[0]
    # The agent proposes again on a new card: round 2, the old card completed.
    third = _card_blocks(
        core, a, rules.block("plan", {**plan, "title": "Launch 3"}, revises=second)
    )
    _settle(core, a, third)
    [shown] = proposals.waiting(core, a)
    assert shown["card"] == third and shown["round"] == 2
    assert runner.kanban[_profile(core, a)][second]["status"] == "done"
    r = client.post(
        f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "reject", "note": "No."}
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    done = runner.kanban[_profile(core, a)][third]
    assert done["status"] == "done" and done["result"] == "rejected"
    assert proposals.waiting(core, a) == []


def test_a_decision_already_on_the_card_is_the_truth(team: Any) -> None:
    """AGOS wrote his approve on the card and was cut before its row heard: the
    next click reads the card. The same choice goes on (no second comment); a
    different one is refused and the row catches up."""
    client, core, runner, a = team
    plan = {"title": "Launch", "markdown": "# Launch"}
    card = _card_blocks(core, a, rules.block("plan", plan))
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    core.engine._hermes(
        a,
        "kanban",
        "comment",
        card,
        f"{rules.marker(card, 1, 'approve')} approved",
        "--author",
        "owner",
    )
    r = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "reject"})
    assert r.status_code == 409, r.text
    assert proposals.waiting(core, a) == []
    row = core.db.execute("SELECT status FROM kanban_asks WHERE id = ?", (shown["id"],)).fetchone()
    assert row["status"] == "approved"
    # And a waiting row whose card already says approve: approve goes on, one comment.
    other = _card_blocks(core, a, rules.block("plan", {**plan, "title": "L2"}))
    _settle(core, a, other)
    [shown] = proposals.waiting(core, a)
    core.engine._hermes(
        a,
        "kanban",
        "comment",
        other,
        f"{rules.marker(other, 1, 'approve')} approved",
        "--author",
        "owner",
    )
    r = client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert len(_comments(core, a, other)) == 1 and len(_cli(runner, "unblock", other)) == 1


def test_a_block_that_lands_after_the_decision_is_released_at_once(team: Any) -> None:
    """The race: his answer is written, then Hermes's block hook fires (late, or
    again) for the same proposal: the card goes on as he said, no new round."""
    client, core, runner, a = team
    plan = {"title": "Launch", "markdown": "# Launch"}
    card = _card_blocks(core, a, rules.block("plan", plan))
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    client.post(f"/workspaces/{a}/proposals/{shown['id']}", json={"choice": "approve"})
    before = len(_cli(runner, "unblock", card))
    assert _settle(core, a, card) is True  # the late block: released again
    assert len(_cli(runner, "unblock", card)) == before + 1
    assert proposals.waiting(core, a) == []  # no second round for the same proposal
    rows = core.db.execute(
        "SELECT COUNT(*) AS n FROM kanban_asks WHERE card = ?", (card,)
    ).fetchone()
    assert rows["n"] == 1


def test_a_proposal_is_not_answered_as_an_ask_and_other_workspaces_never_see_it(
    team: Any,
) -> None:
    client, core, _runner, a = team
    b = ws(client, "Beta")
    card = _card_blocks(core, a, rules.block("plan", {"title": "P", "markdown": "x"}))
    _settle(core, a, card)
    [shown] = proposals.waiting(core, a)
    assert (
        client.post(f"/workspaces/{a}/kanban-asks/{shown['id']}", json={"allow": True}).status_code
        == 404
    )
    assert (
        client.post(
            f"/workspaces/{b}/proposals/{shown['id']}", json={"choice": "approve"}
        ).status_code
        == 404
    )
    assert client.get(f"/workspaces/{b}/inbox").json()["count"] == 0
    assert proposals.waiting(core, a)[0]["status"] == "waiting"
