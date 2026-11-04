"""Review stages, the round cap and plan-first on a Kanban card (Step 52, F25 / F26):
the stage routing (lead resolved at the time, self-review skipped, the Co-Founder,
the owner in his Inbox), approve to done, changes back to the implementer, the round
cap to the owner with his four ways out, a plan accepted (and split into cards, once)
before the work, the guard's refusals and its tool, the workspace's defaults."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import (
    agent_profiles,
    card_docs,
    hermes_channel,
    inbox,
    kanban_board,
    reviews,
)
from agos_core.engine import reviews as rules
from agos_core.hermes_plugin.agos_guard import review as guard_review


@pytest.fixture
def team(env: Any) -> tuple[Any, Any, str, reviews.Org]:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "lead")
    add_agent(client, a, "writer", reports_to="lead")
    cofounder_chat(core, a)
    return client, core, a, reviews.org(core, a)


def _cards(core: Any, a: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = core.engine.runner.kanban[str(core.engine.profile(a))]
    return found


def _card(core: Any, a: str, member: str, policy: dict[str, Any], title: str = "Write") -> str:
    """A card under review rules, running with its member (as Hermes would have it)."""
    body = rules.with_policy("Write the launch post.", policy)
    card = kanban_board.create(core, a, title, body, member)
    _cards(core, a)[card]["status"] = "running"
    return card


def _take(core: Any, a: str, card: str, answer: dict[str, Any], me: str) -> None:
    """What the guard's review.py does on Hermes's board with the agent's own run."""
    assert "step" in answer, answer
    c = _cards(core, a)[card]
    step = answer["step"]
    if step["do"] == "hand":
        c.update(status="review", assignee=step["to"], implementer=step["implementer"])
    elif step["do"] == "done":
        c.update(status="done")
    elif step["do"] in ("back", "return"):
        c["parents"] = [*c.get("parents", []), *step.get("link", [])]
        c.update(status="todo" if step.get("link") else "ready", assignee=step["implementer"])
    elif step["do"] == "stuck":
        c.update(status="blocked", block_kind="needs_input")
    c["comments"].append({"author": me, "body": answer["comment"], "created_at": 1_800_000_300})
    reviews.landed(core, a, card)


def _verdict(core: Any, a: str, card: str, member: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return reviews.verdict(
        core, a, member=member, card_id=card, verdict=verdict, working=card, **kw
    )


def _claimed(core: Any, a: str, card: str) -> None:
    """Hermes's dispatcher started the reviewer on it (review -> running)."""
    _cards(core, a)[card]["status"] = "running"


def _mirror(core: Any, a: str) -> None:
    """Hermes's board database as the fake CLI's cards are (AGOS's read-only looks)."""
    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "DROP TABLE IF EXISTS tasks; DROP TABLE IF EXISTS task_comments;"
        " DROP TABLE IF EXISTS task_links; DROP TABLE IF EXISTS task_events;"
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, assignee TEXT,"
        " status TEXT, block_kind TEXT, goal_mode INTEGER);"
        "CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT, author TEXT,"
        " body TEXT, created_at INTEGER);"
        "CREATE TABLE task_links (parent_id TEXT, child_id TEXT);"
        "CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT,"
        " payload TEXT, created_at INTEGER);"
    )
    for c in _cards(core, a).values():
        db.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, 0)",
            (c["id"], c["title"], c["body"], c["assignee"], c["status"], c.get("block_kind")),
        )
        for m in c["comments"]:
            db.execute(
                "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (c["id"], m["author"], m["body"], m["created_at"]),
            )
        for p in c.get("parents") or []:
            db.execute("INSERT INTO task_links VALUES (?, ?)", (p, c["id"]))
    db.commit()
    db.close()


def _inbox(core: Any, a: str) -> list[dict[str, Any]]:
    """The Inbox as the board stands now (then the fake CLI is the board again)."""
    _mirror(core, a)
    try:
        return inbox.items(core, a)
    finally:
        (agent_profiles.board_home(core, a) / "kanban.db").unlink()


# ---- the rules -------------------------------------------------------------------------


def test_the_policy_is_the_cards_block_over_the_workspaces_defaults() -> None:
    base = {"stages": ["lead"], "cap": 4, "planFirst": True, "planReviewer": "cofounder"}
    plain = rules.policy("Do it.", base)
    assert (plain.stages, plain.cap, plain.plan, plain.own) == (["lead"], 4, False, False)
    # 'plan first for big cards': a card with children needs a plan.
    assert rules.policy("Do it.", base, has_children=True).plan is True
    body = rules.with_policy("Do it.", {"stages": ["@Maya", "Co-Founder", "owner"], "cap": 99})
    own = rules.policy(body, base)
    assert own.stages == ["maya", "cofounder", "owner"] and own.cap == 20 and own.own
    assert rules.without_policy(body) == "Do it."
    # An explicit empty list turns the defaults' stages off for this card.
    assert rules.policy(rules.with_policy("x", {"stages": []}), base).stages == []
    # AGOS's own question / proposal cards never get the defaults.
    assert rules.policy("```agos-question\n{}\n```", base).stages == []
    # Markers, also behind Hermes's reopen-review "CHANGES REQUESTED:" prefix.
    mark = rules.read_mark(
        "t_1", "CHANGES REQUESTED: " + rules.review_marker("t_1", 2, 1, "changes") + " owner: no"
    )
    assert mark is not None and (mark.verb, mark.number, mark.round, mark.rest) == (
        "changes",
        1,
        2,
        "owner: no",
    )
    assert rules.read_mark("t_2", rules.review_marker("t_1", 1, 1, "approve")) is None
    tasks = rules.plan_tasks(
        "# Plan\n\nWhy.\n\n## Tasks\n- [ ] Draft the post @writer\n* Check the facts\n"
        "1. Publish it @lead please\n\n## Risks\n- not a task\n"
    )
    assert tasks == [
        {"title": "Draft the post", "member": "writer"},
        {"title": "Check the facts", "member": ""},
        {"title": "Publish it please", "member": "lead"},
    ]
    assert rules.task_key("t_1", 2, 3) == "agos-plan:t_1:2:3"


def test_the_workspace_defaults_are_kept_checked_and_off_by_default(team: Any) -> None:
    client, core, a, _people = team
    url = f"/workspaces/{a}/review-settings"
    shown = client.get(url).json()
    assert {k: shown[k] for k in ("stages", "cap", "planFirst", "planReviewer")} == {
        "stages": [],
        "cap": 3,
        "planFirst": False,
        "planReviewer": "owner",
    }
    # Who a stage may name: the team (and the Co-Founder).
    assert {m["name"] for m in shown["members"]} == {"cofounder", "lead", "writer"}
    saved = client.put(url, json={"stages": ["lead", "owner"], "cap": 2, "planFirst": True})
    assert saved.status_code == 200 and saved.json()["stages"] == ["lead", "owner"]
    assert reviews.defaults(core, a)["cap"] == 2
    assert client.put(url, json={"stages": ["nobody"]}).status_code == 400
    # A card made now goes by them (no block of its own).
    card = kanban_board.create(core, a, "Write", "Body.", "writer")
    flow = reviews.view(reviews.situation(core, a, card))
    assert flow is not None and [s["stage"] for s in flow["stages"]] == ["lead", "owner"]


# ---- routing a card through its stages ---------------------------------------------------


def test_stages_route_lead_then_cofounder_then_owner_to_done(team: Any, monkeypatch: Any) -> None:
    client, core, a, people = team
    from agos_core.actions.services.channel import owner_needs

    pushed: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        owner_needs, "push", lambda _c, _w, body, _s, **kw: pushed.append((body, kw["buttons"]))
    )
    writer, lead = people.profiles["writer"], people.profiles["lead"]
    card = _card(core, a, "writer", {"stages": ["lead", "cofounder", "owner"]})
    # The worker's own finishing call is refused with what to call instead.
    refused = reviews.check(core, a, card, "kanban_complete", "writer")
    assert refused.startswith("Review first: stage 1 of 3 on this card is your lead @lead.")
    assert "agos_review(verdict='submit'" in refused
    assert "summary" in _verdict(core, a, card, "writer", "submit")["error"]
    handed = _verdict(core, a, card, "writer", "submit", summary="Drafted, read it twice.")
    assert handed["step"] == {
        "do": "hand",
        "to": lead,
        "implementer": writer,
        "summary": "Drafted, read it twice.",
    }
    _take(core, a, card, handed, writer)
    # Hermes wakes the lead on it (its review lane); a finishing call is refused.
    _claimed(core, a, card)
    assert reviews.check(core, a, card, "kanban_complete", "lead").startswith(
        "You are reviewing this card (stage 1 of 3)"
    )
    approved = _verdict(core, a, card, "lead", "approve", note="Good.")
    assert approved["step"]["to"] == people.cofounder
    assert approved["step"]["implementer"] == writer  # the handoff names the writer
    _take(core, a, card, approved, lead)
    _claimed(core, a, card)
    to_owner = _verdict(core, a, card, "", "approve")
    assert to_owner["step"]["to"] == rules.OWNER
    _take(core, a, card, to_owner, people.cofounder)
    # The owner's stage: his Inbox (and his phone, with an Approve button).
    [item] = [i for i in _inbox(core, a) if i["type"] == "review"]
    assert item["card"] == card and item["review"]["kind"] == "stage"
    assert (item["review"]["stage"], item["review"]["stages"]) == (3, 3)
    [(said, buttons)] = pushed
    assert said.startswith(f"🔎 Card {card} (Write) waits for your review (stage 3 of 3")
    assert buttons == [("Approve", f"krev:ok:{card}")]
    flow = reviews.view(reviews.situation(core, a, card))
    assert flow is not None
    assert [s["state"] for s in flow["stages"]] == ["approved", "approved", "current"]
    assert flow["ownerCan"] == ["approve", "changes"]
    r = client.post(f"/workspaces/{a}/kanban/{card}/review", json={"action": "approve"})
    assert r.status_code == 200, r.text
    assert _cards(core, a)[card]["status"] == "done"
    assert any("s3: approve] owner" in c["body"] for c in _cards(core, a)[card]["comments"])
    # Decided: a second Approve is refused.
    again = client.post(f"/workspaces/{a}/kanban/{card}/review", json={"action": "approve"})
    assert again.status_code == 409


def test_self_review_and_a_reviewer_twice_are_skipped(team: Any) -> None:
    _client, core, a, people = team
    lead = people.profiles["lead"]
    # The lead's own lead is the Co-Founder: stage 2 (the Co-Founder again) is skipped.
    card = _card(core, a, "lead", {"stages": ["lead", "cofounder"]})
    handed = _verdict(core, a, card, "lead", "submit", summary="Done.")
    assert handed["step"]["to"] == people.cofounder
    _take(core, a, card, handed, lead)
    _claimed(core, a, card)
    assert _verdict(core, a, card, "", "approve")["step"]["do"] == "done"
    # A card whose only reviewer is its own implementer: no review at all.
    own = _card(core, a, "writer", {"stages": ["writer"]})
    alone = _verdict(core, a, own, "writer", "submit", summary="Done.")
    assert alone["step"] == {"do": "done", "summary": "Done."}
    flow = reviews.view(reviews.situation(core, a, own))
    assert flow is not None and flow["stages"][0]["state"] == "skipped"


def test_request_changes_goes_back_to_the_implementer_and_counts_a_round(team: Any) -> None:
    _client, core, a, people = team
    writer, lead = people.profiles["writer"], people.profiles["lead"]
    card = _card(core, a, "writer", {"stages": ["lead", "owner"]})
    _take(core, a, card, _verdict(core, a, card, "writer", "submit", summary="v1"), writer)
    _claimed(core, a, card)
    assert "Say what to change" in _verdict(core, a, card, "lead", "changes")["error"]
    back = _verdict(core, a, card, "lead", "changes", note="Shorter intro.")
    assert back["step"] == {"do": "back", "reason": "Shorter intro.", "implementer": writer}
    _take(core, a, card, back, lead)
    c = _cards(core, a)[card]
    assert (c["status"], c["assignee"]) == ("ready", writer)
    assert c["comments"][-1]["body"].endswith("lead: Shorter intro.")
    flow = reviews.view(reviews.situation(core, a, card))
    assert flow is not None and (flow["round"], flow["rounds"]) == (2, 1)
    assert flow["stages"][0]["state"] == "changes"
    assert [n["text"] for n in flow["notes"] if n["verb"] == "changes"] == ["lead: Shorter intro."]
    # Resubmitted: it comes back to the stage that asked.
    c["status"] = "running"
    again = _verdict(core, a, card, "writer", "submit", summary="v2")
    assert again["step"]["to"] == lead and "r2 s1: submit" in again["comment"]


def test_the_round_cap_hands_the_card_to_the_owner_with_the_notes(team: Any) -> None:
    client, core, a, people = team
    writer, lead = people.profiles["writer"], people.profiles["lead"]

    def stuck_card() -> str:
        card = _card(core, a, "writer", {"stages": ["lead"], "cap": 2})
        _take(core, a, card, _verdict(core, a, card, "writer", "submit", summary="v1"), writer)
        _claimed(core, a, card)
        _take(core, a, card, _verdict(core, a, card, "lead", "changes", note="Tone."), lead)
        _cards(core, a)[card]["status"] = "running"
        _take(core, a, card, _verdict(core, a, card, "writer", "submit", summary="v2"), writer)
        _claimed(core, a, card)
        last = _verdict(core, a, card, "lead", "changes", note="Still the tone.")
        assert last["step"] == {
            "do": "stuck",
            "reason": "waiting for the owner: stuck in review after 2 rounds",
        }
        _take(core, a, card, last, lead)
        return card

    card = stuck_card()
    assert reviews.check(core, a, card, "kanban_complete", "lead").startswith(
        "This card is stuck in review after 2 rounds"
    )
    [item] = [i for i in _inbox(core, a) if i["card"] == card]
    assert item["type"] == "review" and item["review"]["kind"] == "stuck"
    assert [n["text"] for n in item["review"]["notes"] if n["verb"] in ("changes", "stuck")] == [
        "lead: Tone.",
        "lead: Still the tone.",
    ]
    assert item["review"]["ownerCan"] == ["approve", "changes", "reassign", "drop"]
    # Send back with a note: to the implementer, the cap counts again from zero.
    url = f"/workspaces/{a}/kanban/{card}/review"
    assert client.post(url, json={"action": "changes"}).status_code == 400
    sent = client.post(url, json={"action": "changes", "note": "Use the brand voice doc."})
    assert sent.status_code == 200, sent.text
    c = _cards(core, a)[card]
    assert (c["status"], c["assignee"]) == ("ready", writer)
    s = reviews.situation(core, a, card)
    assert (s.state.phase, s.state.since_reset, s.state.rounds) == ("work", 0, 2)
    # Reassign, drop and approve, on cards stuck the same way.
    other = stuck_card()
    r = client.post(
        f"/workspaces/{a}/kanban/{other}/review", json={"action": "reassign", "member": "lead"}
    )
    assert r.status_code == 200 and _cards(core, a)[other]["assignee"] == lead
    dropped = stuck_card()
    client.post(f"/workspaces/{a}/kanban/{dropped}/review", json={"action": "drop"})
    assert _cards(core, a)[dropped]["status"] == "archived"
    passed = stuck_card()
    client.post(f"/workspaces/{a}/kanban/{passed}/review", json={"action": "approve"})
    assert _cards(core, a)[passed]["status"] == "done"
    flow = reviews.view(reviews.situation(core, a, passed))
    assert flow is not None and flow["stages"][0]["state"] == "approved"


# ---- plan first -------------------------------------------------------------------------

PLAN = "# Plan\n\nTwo steps.\n\n## Tasks\n- Draft the post @writer\n- Check the facts @lead\n"


def test_a_plan_is_accepted_and_split_into_cards_before_the_work(team: Any) -> None:
    client, core, a, people = team
    writer = people.profiles["writer"]
    card = _card(core, a, "writer", {"plan": True})
    for tool in ("kanban_complete", "kanban_request_review", "kanban_create"):
        assert reviews.check(core, a, card, tool, "writer").startswith(
            "Plan first: this card needs a plan the owner accepts before the work."
        )
    assert "Write the plan first" in _verdict(core, a, card, "writer", "plan_ready")["error"]
    card_docs.save(core, a, card, "plan", PLAN, who="writer", why="first", base_revision=None)
    ready = _verdict(core, a, card, "writer", "plan_ready")
    assert ready["step"]["to"] == rules.OWNER and "splits into 2 cards" in ready["comment"]
    _take(core, a, card, ready, writer)
    assert reviews.check(core, a, card, "kanban_complete", "writer").startswith(
        "The plan (v1) waits for the owner to accept it"
    )
    [item] = [i for i in _inbox(core, a) if i["card"] == card]
    assert item["review"]["kind"] == "plan" and item["review"]["planRevision"] == 1
    r = client.post(f"/workspaces/{a}/kanban/{card}/review", json={"action": "approve"})
    assert r.status_code == 200, r.text
    cards = _cards(core, a)
    made = [c for c in cards.values() if str(c.get("key") or "").startswith(f"agos-plan:{card}:")]
    assert [(c["key"], c["title"], c["assignee"]) for c in made] == [
        (f"agos-plan:{card}:1:1", "Draft the post", writer),
        (f"agos-plan:{card}:1:2", "Check the facts", people.profiles["lead"]),
    ]
    # The card waits for its plan's cards (Hermes's decompose shape), back with its member.
    assert cards[card]["parents"] == [c["id"] for c in made]
    assert (cards[card]["status"], cards[card]["assignee"]) == ("todo", writer)
    assert r.json()["plan"] == "accepted"
    # Accepting again is refused; the split itself is idempotent (Hermes's key).
    again = client.post(f"/workspaces/{a}/kanban/{card}/review", json={"action": "approve"})
    assert again.status_code == 409
    before = len(cards)
    assert reviews.decompose(core, a, reviews.situation(core, a, card)) == [c["id"] for c in made]
    assert len(_cards(core, a)) == before
    # Work allowed now.
    cards[card]["status"] = "running"
    assert reviews.check(core, a, card, "kanban_complete", "writer") == ""


def test_a_plan_sent_back_and_a_plan_accepted_by_an_agent(team: Any) -> None:
    client, core, a, people = team
    writer, lead = people.profiles["writer"], people.profiles["lead"]
    card = _card(core, a, "writer", {"plan": True})
    card_docs.save(core, a, card, "plan", PLAN, who="writer", why="v1", base_revision=None)
    _take(core, a, card, _verdict(core, a, card, "writer", "plan_ready"), writer)
    r = client.post(
        f"/workspaces/{a}/kanban/{card}/review", json={"action": "changes", "note": "Add risks."}
    )
    assert r.status_code == 200 and r.json()["plan"] == "changes"
    c = _cards(core, a)[card]
    assert (c["status"], c["assignee"]) == ("ready", writer)
    assert c["comments"][-1]["body"].startswith("CHANGES REQUESTED: [agos-plan")
    # The same revision isn't sent again; a new one is.
    c["status"] = "running"
    assert "write a new revision" in _verdict(core, a, card, "writer", "plan_ready")["error"]
    card_docs.save(
        core, a, card, "plan", PLAN + "\n## Risks\n", who="writer", why="v2", base_revision=1
    )
    # Its lead accepts plans here (the card's own rule).
    kanban_board._cli(
        core,
        a,
        "edit",
        card,
        "--body",
        rules.with_policy(c["body"], {"plan": True, "planReviewer": "lead"}),
    )
    ready = _verdict(core, a, card, "writer", "plan_ready")
    assert ready["step"]["to"] == lead
    _take(core, a, card, ready, writer)
    _claimed(core, a, card)
    _cards(core, a)[card]["assignee"] = people.cofounder  # not the plan's reviewer
    assert "waits for your lead @lead" in _verdict(core, a, card, "", "approve")["error"]
    _cards(core, a)[card]["assignee"] = lead
    accepted = _verdict(core, a, card, "lead", "approve")
    assert accepted["step"]["do"] == "return" and accepted["step"]["implementer"] == writer
    assert len(accepted["step"]["link"]) == 2 and "Do the work now." in accepted["comment"]


def test_the_tool_refuses_who_is_not_the_reviewer_and_other_runs(team: Any) -> None:
    client, core, a, people = team
    writer = people.profiles["writer"]
    card = _card(core, a, "writer", {"stages": ["lead"]})
    _take(core, a, card, _verdict(core, a, card, "writer", "submit", summary="v1"), writer)
    _claimed(core, a, card)
    # Running with the lead on it: the writer may not answer for it.
    assert "isn't running with you" in _verdict(core, a, card, "writer", "approve")["error"]
    _cards(core, a)[card]["assignee"] = writer  # even with the card in its hands
    assert _verdict(core, a, card, "writer", "approve")["error"] == (
        "You are not this card's reviewer now: stage 1 of 1 is your lead @lead."
    )
    other = reviews.verdict(
        core, a, member="lead", card_id=card, verdict="approve", working="t_other"
    )
    assert other["error"].startswith("Answer from the card's own run")
    # Through the bridge, with the workspace's key; another workspace's key: 401.
    key = hermes_channel.bridge_key(core, a)
    r = client.post(
        f"/hermes-bridge/{a}/review",
        json={"member": "lead", "card": card, "verdict": "approve", "working": card},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200 and "error" in r.json()
    b = ws(client, "Beta")
    cross = client.post(
        f"/hermes-bridge/{b}/review",
        json={"member": "lead", "card": card, "verdict": "approve", "working": card},
        headers={"authorization": f"Bearer {key}"},
    )
    assert cross.status_code in (401, 403)
    on_b = client.post(
        f"/hermes-bridge/{b}/review-check",
        json={"member": "", "card": card, "tool": "kanban_complete"},
        headers={"authorization": f"Bearer {hermes_channel.bridge_key(core, b)}"},
    )
    assert on_b.json() == {"refuse": ""}  # A's card isn't on B's board


def test_the_board_chip_and_the_card_view(team: Any) -> None:
    client, core, a, people = team
    card = _card(core, a, "writer", {"stages": ["lead", "owner"]})
    plain = kanban_board.create(core, a, "Other", "No rules.", "writer")
    _take(
        core,
        a,
        card,
        _verdict(core, a, card, "writer", "submit", summary="v1"),
        people.profiles["writer"],
    )
    _mirror(core, a)
    shown = {c["id"]: c for c in client.get(f"/workspaces/{a}/kanban").json()["cards"]}
    assert shown[card]["reviewChip"] == {
        "stage": 1,
        "stages": 2,
        "round": 1,
        "phase": "review",
        "plan": "none",
    }
    assert shown[plain]["reviewChip"] is None
    assert "agos-review" not in shown[card]["body"]
    detail = client.get(f"/workspaces/{a}/kanban/{card}").json()
    assert detail["review"]["stages"][0]["label"] == "your lead @lead"
    assert detail["review"]["stages"][1]["state"] == "waiting"
    # The card's own rules, set from the modal (Hermes's `kanban edit --body`).
    r = client.put(f"/workspaces/{a}/kanban/{plain}/review", json={"stages": ["owner"], "cap": 5})
    assert r.status_code == 200 and r.json()["cap"] == 5 and r.json()["own"] is True
    reset = client.put(f"/workspaces/{a}/kanban/{plain}/review", json={"reset": True})
    assert reset.status_code == 200 and reset.json() is None


# ---- the guard ----------------------------------------------------------------------------


class Board:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _kb(monkeypatch: Any, board: Board) -> None:
    kb = types.ModuleType("hermes_cli.kanban_db")

    def record(name: str, answer: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            board.calls.append((name, args[1:], kwargs))
            return answer

        return call

    for name, answer in (
        ("request_review", (True, None)),
        ("request_changes", (True, "a-old")),
        ("complete_task", True),
        ("block_task", True),
        ("schedule_task", True),
        ("assign_task", True),
        ("unblock_task", True),
        ("link_tasks", False),
        ("add_comment", 1),
    ):
        setattr(kb, name, record(name, answer))
    hermes_cli = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", kb)
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_1")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "7")


def test_the_guard_takes_each_step_with_its_own_run(monkeypatch: Any) -> None:
    board = Board()
    _kb(monkeypatch, board)
    sent: list[tuple[str, dict[str, Any]]] = []

    def post(answer: dict[str, Any]) -> Any:
        def call(path: str, body: dict[str, Any], timeout: float = 30) -> Any:
            sent.append((path, body))
            return answer if body["verdict"] != "landed" else {"ok": True}

        return call

    def run(me: str, answer: dict[str, Any], **args: Any) -> dict[str, Any]:
        board.calls.clear()
        out: dict[str, Any] = json.loads(
            guard_review.review_tool(
                {"verdict": "approve", **args},
                member="",
                me=me,
                post=post(answer),
                board=lambda: board,
            )
        )
        return out

    # The implementer's own run hands it over: request_review with its run id.
    hand = {"do": "hand", "to": "a-lead", "implementer": "a-writer", "summary": "v1"}
    said = run("a-writer", {"step": hand, "comment": "[m]", "say": "Handed."})
    assert said == {"ok": True, "card": "t_1", "next": "Handed."}
    assert board.calls == [
        (
            "request_review",
            ("t_1",),
            {"summary": "v1", "reviewer": "a-lead", "expected_run_id": 7, "with_reason": True},
        ),
        ("add_comment", ("t_1", "a-writer", "[m]"), {}),
    ]
    assert [b["verdict"] for _p, b in sent[-2:]] == ["approve", "landed"]
    # A reviewer's run: back to the implementer first, then the next stage.
    run("a-lead", {"step": {**hand, "to": "owner"}, "comment": "[m]"})
    assert [c[0] for c in board.calls] == [
        "schedule_task",
        "assign_task",
        "unblock_task",
        "request_review",
        "add_comment",
    ]
    assert board.calls[1][1] == ("t_1", "a-writer")
    assert board.calls[3][2]["expected_run_id"] is None and board.calls[3][2]["reviewer"] == "owner"
    # Changes: Hermes's request_changes; routed elsewhere -> given back to the implementer.
    run(
        "a-lead", {"step": {"do": "back", "reason": "r", "implementer": "a-writer"}, "comment": "c"}
    )
    assert [c[0] for c in board.calls] == ["request_changes", "assign_task", "add_comment"]
    run("a-lead", {"step": {"do": "stuck", "reason": "waiting for the owner: x"}, "comment": "c"})
    assert board.calls[0] == (
        "block_task",
        ("t_1",),
        {"reason": "waiting for the owner: x", "kind": "needs_input", "expected_run_id": 7},
    )
    run(
        "a-lead",
        {"step": {"do": "return", "implementer": "a-writer", "reason": "ok", "link": ["t_9"]}},
    )
    linked: Any = board.calls[0]  # (mypy keeps the narrowing of the assert above)
    assert linked == ("link_tasks", ("t_9", "t_1"), {"expected_child_run_id": 7})
    # AGOS says no: nothing is touched.
    assert run("a-lead", {"error": "You are not this card's reviewer now."}) == {
        "error": "You are not this card's reviewer now."
    }
    assert board.calls == []


def test_the_guard_refuses_a_finishing_call_only_for_its_own_card(monkeypatch: Any) -> None:
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_1")
    asked: list[dict[str, Any]] = []

    def post(path: str, body: dict[str, Any], timeout: float = 30) -> Any:
        asked.append(body)
        return {"refuse": "Review first."}

    assert guard_review.guard("kanban_complete", {}, member="writer", post=post) == "Review first."
    assert asked == [{"member": "writer", "card": "t_1", "tool": "kanban_complete"}]
    assert guard_review.guard("kanban_complete", {"task_id": "t_2"}, member="", post=post) == ""
    assert guard_review.guard("kanban_show", {}, member="", post=post) == ""

    def down(path: str, body: dict[str, Any], timeout: float = 30) -> Any:
        raise OSError("no AGOS")

    assert guard_review.guard("kanban_complete", {}, member="", post=down) == ""
