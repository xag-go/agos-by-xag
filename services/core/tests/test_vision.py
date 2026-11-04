"""Step 53: the Vision page.

- Migration: Step 51's goal rows become the Vision / goals / projects (a success
  measure becomes a key result of a new goal), replayable.
- The owner's CRUD of the Vision, goals, key results and projects; the rollup and
  progress (cards -> project -> key results / goal -> Vision); the SOUL.md section.
- Proposals of plan changes, edited by the owner before Approve (a key result's
  numbers, a project's fields); a key result's number needs its source.
- The daily plan: proposed through agos_goals, on Telegram with Accept / Skip,
  Accept creates today's cards (agos-today:<date>:<n>, idempotent) and the owner's
  You list; Change sends a note back; Skip ends it; one accepted plan a day.
- The recap / weekly review posts; the three Hermes cron jobs in the Co-Founder's
  profile (made with the first Vision, re-timed, turned off) and their prompts.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_team_hierarchy import _agent

from agos_core.actions import goals, hermes_channel, proposals, rhythm, today
from agos_core.actions.services.channel import owner_needs
from agos_core.actions.services.vision import plan_board as vision_plan_board
from agos_core.db import connection
from agos_core.db.migrations import MIGRATIONS
from agos_core.engine import goals as rules
from agos_core.engine import identity

MARK = "CREATE TABLE IF NOT EXISTS key_results"


@pytest.fixture
def space(env: Any) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, cron, ws = env
    _agent(client, ws, "editor")
    _agent(client, ws, "writer")
    return client, core, cron, ws


@pytest.fixture
def pushed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What AGOS sends to the owner's Telegram (the asks' path, owner_needs.push)."""
    sent: list[dict[str, Any]] = []

    def push(core: Any, ws: str, body: str, source: str, **kw: Any) -> int:
        sent.append({"body": body, "source": source, **kw})
        return 1

    monkeypatch.setattr(owner_needs, "push", push)
    return sent


def _bridge(client: Any, core: Any, ws: str, body: dict[str, Any]) -> dict[str, Any]:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/goals", json=body, headers={"authorization": f"Bearer {key}"}
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _cards(core: Any, ws: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = core.engine.runner.kanban.setdefault(
        core.engine.profile(ws), {}
    )
    return found


def _soul(core: Any, ws: str) -> str:
    return str((core.engine.profile_home(ws) / "SOUL.md").read_text(encoding="utf-8"))


# ---- the migration ------------------------------------------------------------------


def test_step51_goals_become_the_vision_goals_and_projects_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark = next(i for i, m in enumerate(MIGRATIONS) if MARK in m)
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:mark])
    connection._migrate(db)
    for ws in ("w", "v"):
        db.execute(
            "INSERT INTO workspaces (id, created_at, updated_at) VALUES (?, 't', 't')", (ws,)
        )
    old = """INSERT INTO goals (id, workspace_id, parent_id, title, why, measure, owner,
                                created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 't', 't')"""
    db.execute(old, (1, "w", None, "Grow", "Sponsors", "10k by June", ""))
    db.execute(old, (2, "w", 1, "Reels", "", "", "editor"))
    db.execute(old, (3, "w", 2, "Hooks", "", "", ""))
    db.execute(old, (4, "w", 3, "Deeper", "", "", ""))  # a sub-sub-sub-goal
    db.execute(old, (5, "v", None, "Other", "", "", ""))  # no measure: no new goal
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[: mark + 1])
    connection._migrate(db)

    def state() -> list[tuple[Any, ...]]:
        return [
            tuple(r)
            for r in db.execute(
                "SELECT id, workspace_id, parent_id, level, title, measure FROM goals ORDER BY id"
            )
        ]

    assert state() == [
        (1, "w", None, "vision", "Grow", ""),
        (2, "w", 1, "goal", "Reels", ""),
        (3, "w", 2, "project", "Hooks", ""),
        (4, "w", 2, "project", "Deeper", ""),  # hangs under its goal: projects don't nest
        (5, "v", None, "vision", "Other", ""),
        (6, "w", 1, "goal", "Success measure", ""),
    ]
    assert db.execute("SELECT why FROM goals WHERE id = 1").fetchone()[0] == "Sponsors"
    krs = [tuple(r) for r in db.execute("SELECT goal_id, title, target FROM key_results")]
    assert krs == [(6, "10k by June", None)]  # words only: the owner sets the numbers
    # Replayed on a database already at this migration: nothing doubles or moves.
    db.execute(f"PRAGMA user_version = {mark}")
    connection._migrate(db)
    assert len(state()) == 6
    assert db.execute("SELECT COUNT(*) FROM key_results").fetchone()[0] == 1
    # The rows read back as the tree the page shows.
    rows = [goals._goal(r) for r in db.execute("SELECT * FROM goals WHERE workspace_id = 'w'")]
    results = [goals._result(r) for r in db.execute("SELECT * FROM key_results")]
    top = rules.tree(rows, results)
    assert top is not None and [c.title for c in top.children] == [
        "Success measure",
        "Reels",
    ]
    assert top.children[0].results[0].title == "10k by June"


# ---- the owner's plan: CRUD, rollup, progress, SOUL.md --------------------------------


def test_key_results_roll_up_into_goal_and_vision_progress(space: Any) -> None:
    client, core, _cron, ws = space
    vid = client.put(
        f"/workspaces/{ws}/vision",
        json={"title": "The Argan brand Moroccans trust", "why": "Family", "strategy": "Reels"},
    ).json()["vision"]["id"]
    goal = client.post(
        f"/workspaces/{ws}/vision/goals",
        json={"title": "Grow the audience", "owner": "editor", "dueOn": "2027-01-31"},
    ).json()["id"]
    sales = client.post(f"/workspaces/{ws}/vision/goals", json={"title": "Sell"}).json()["id"]
    url = f"/workspaces/{ws}/vision/goals/{goal}/results"
    followers = client.post(
        url,
        json={
            "title": "Followers",
            "start": 1000,
            "current": 4000,
            "target": 11000,
            "unit": "followers",
        },
    ).json()["id"]
    reels = client.post(url, json={"title": "Reels posted", "target": 48, "current": 36}).json()[
        "id"
    ]
    r = client.post(url, json={"title": "Bad", "dueOn": "next week"})
    assert r.status_code == 422
    # A project: dated or recurring; an end before its start is refused.
    r = client.post(
        f"/workspaces/{ws}/vision/goals/{goal}/projects",
        json={"title": "Launch", "startsOn": "2026-11-10", "endsOn": "2026-11-01"},
    )
    assert r.status_code == 400 and "ends on or after" in r.text
    weekly = client.post(
        f"/workspaces/{ws}/vision/goals/{goal}/projects",
        json={"title": "Weekly reels", "projectKind": "recurring", "rhythm": "4 reels a week"},
    ).json()["id"]
    view = client.get(f"/workspaces/{ws}/vision").json()
    shown = view["vision"]["children"][0]
    assert shown["id"] == goal and shown["dueOn"] == "2027-01-31"
    progress = {k["title"]: k["progress"] for k in shown["results"]}
    assert progress == {"Followers": 0.3, "Reels posted": 0.75}
    assert shown["progress"] == pytest.approx(0.525)  # the key results' mean
    assert view["vision"]["children"][1]["progress"] is None  # Sell: nothing to measure
    assert view["vision"]["progress"] == pytest.approx(0.525)  # the measured goals' mean
    assert shown["children"][0]["projectKind"] == "recurring"
    # The owner moves a number; the source says it was him.
    assert (
        client.put(
            f"/workspaces/{ws}/vision/results/{followers}", json={"current": 11000}
        ).status_code
        == 204
    )
    found = goals._one_result(core, ws, followers)
    assert found.current == 11000 and found.source == "the owner"
    assert rules.result_progress(found) == 1.0
    # The SOUL.md section: the Vision, the strategy, the numbers and the projects.
    section = identity.goal_of(_soul(core, ws))
    assert f"Vision #{vid}: The Argan brand Moroccans trust" in section
    assert "Strategy: Reels" in section
    assert f"  - KR #{followers} Followers: 11000 / 11000 followers (100%)" in section
    assert f"  - KR #{reels} Reels posted: 36 / 48 (75%)" in section
    assert f"  - Project #{weekly} Weekly reels (recurring: 4 reels a week)" in section
    assert f"- Goal #{sales} Sell" in section
    assert "you may only suggest a change" in section
    # Status for the agents: the same tree with its numbers, and today's line.
    status = goals.status_text(core, ws)
    assert f"KR #{reels} Reels posted: 36 / 48 (75%)" in status
    assert "Today (" in status and "no plan proposed yet" in status
    # A key result goes; a target can be cleared (not set yet).
    client.put(f"/workspaces/{ws}/vision/results/{reels}", json={"target": None})
    assert goals._one_result(core, ws, reels).target is None
    assert client.delete(f"/workspaces/{ws}/vision/results/{reels}").status_code == 204
    assert client.delete(f"/workspaces/{ws}/vision/results/{reels}").status_code == 404


def test_each_project_shows_its_next_card_from_the_same_board_read(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    reels = goals.add_project(core, ws, goal, title="Reels")
    live = goals.add_project(core, ws, goal, title="Live")
    empty = goals.add_project(core, ws, goal, title="Collab")

    def card(cid: str, status: str, project: int, at: int, prio: int = 0) -> dict[str, Any]:
        body = f"## Goal\nProject #{project}: x\n"
        return {
            "id": cid,
            "status": status,
            "body": body,
            "title": f"Card {cid}",
            "assignee": "",
            "key": "",
            "priority": prio,
            "created_at": at,
        }

    tasks = [
        card("r1", "done", reels, 1),
        card("r2", "todo", reels, 2),
        card("r3", "review", reels, 3),
        card("r4", "running", reels, 4),
        card("r5", "running", reels, 5, prio=0),
        card("l1", "todo", live, 9),
        card("l2", "ready", live, 8),  # older: first among ready / to do
        card("l3", "blocked", live, 10),
        card("l4", "archived", live, 1),
        # A child card with no '## Goal' line serves its parent's project.
        {**card("k1", "todo", live, 0), "body": "no goal line"},
    ]
    reads: list[str] = []

    def board(core: Any, ws: str) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        reads.append(ws)
        return tasks, [("l3", "k1")]

    monkeypatch.setattr(vision_plan_board, "board_tasks", board)
    view = client.get(f"/workspaces/{ws}/vision").json()
    assert len(reads) == 1  # the counts, today's column and the next cards: one read
    shown = {p["id"]: p for p in view["vision"]["children"][0]["children"]}
    assert shown[reels]["nextCard"] == {"id": "r4", "title": "Card r4", "status": "running"}
    assert shown[live]["nextCard"] == {"id": "l3", "title": "Card l3", "status": "blocked"}
    assert shown[empty]["nextCard"] is None
    assert view["vision"]["children"][0]["nextCard"]["id"] == "r4"  # the goal's: its projects'
    # Without running / review / blocked: the oldest ready / to do card.
    tasks[:] = [t for t in tasks if t["id"] in ("l1", "l2")]
    view = client.get(f"/workspaces/{ws}/vision").json()
    assert view["vision"]["children"][0]["children"][1]["nextCard"]["id"] == "l2"


def test_each_workspace_has_its_own_plan(space: Any) -> None:
    client, core, _cron, ws = space
    other = client.post(
        "/workspaces",
        json={
            "name": "Other",
            "defaultModel": {"provider": "claude", "mode": "cli", "model": "m", "effort": "high"},
        },
    ).json()["id"]
    goals.set_vision(core, ws, title="Mine")
    goal = goals.add_goal(core, ws, title="Grow")
    assert client.get(f"/workspaces/{other}/vision").json()["vision"] is None
    r = client.put(f"/workspaces/{other}/vision/items/{goal}", json={"title": "Stolen"})
    assert r.status_code == 404
    r = client.post(f"/workspaces/{other}/vision/goals/{goal}/results", json={"title": "X"})
    assert r.status_code == 404


# ---- proposals: edited before Approve -------------------------------------------------


def test_the_owner_edits_a_proposed_key_result_before_approving(space: Any, pushed: Any) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    made = _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "kr",
            "payload": {
                "goal_id": goal,
                "title": "Followers",
                "start": 1000,
                "target": 5000,
                "unit": "followers",
                "due_on": "2027-01-31",
                "why": "The number sponsors read",
            },
        },
    )
    assert made.get("proposed") is True, made
    [shown] = proposals.waiting(core, ws)
    assert shown["label"] == "Add the key result: Followers"
    assert "The number sponsors read" in pushed[-1]["body"]
    # Edits only go with an approve; the change itself and its goal stay.
    url = f"/workspaces/{ws}/proposals/{shown['id']}"
    r = client.post(url, json={"choice": "revise", "payload": {"target": 1}})
    assert r.status_code == 400
    r = client.post(url, json={"choice": "approve", "payload": {"target": "lots"}})
    assert r.status_code == 400 and "target must be a number" in r.text
    r = client.post(
        url,
        json={
            "choice": "approve",
            "payload": {"target": 10000, "due_on": "2027-03-31", "change": "drop_goal"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["editedPayload"]["target"] == 10000
    assert r.json()["payload"]["target"] == 5000  # the proposal as it was made
    [kr] = goals.top(core, ws).children[0].results  # type: ignore[union-attr]
    assert (kr.title, kr.start, kr.target, kr.due_on) == ("Followers", 1000, 10000, "2027-03-31")
    # A new number needs its source; with one, the owner corrects it before approving.
    r = _bridge(
        client,
        core,
        ws,
        {"action": "propose", "kind": "kr_update", "payload": {"kr_id": kr.id, "current": 2500}},
    )
    assert "source" in r["error"]
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "kr_update",
            "payload": {
                "kr_id": kr.id,
                "current": 2500,
                "source": "Instagram insights, 25 Oct",
                "why": "Weekly review",
            },
        },
    )
    [update] = proposals.waiting(core, ws)
    assert update["label"] == f"Key result #{kr.id} is now 2500"
    r = client.post(
        f"/workspaces/{ws}/proposals/{update['id']}",
        json={"choice": "approve", "payload": {"current": 2600}},
    )
    assert r.status_code == 200, r.text
    found = goals._one_result(core, ws, kr.id)
    assert found.current == 2600 and found.source == "Instagram insights, 25 Oct"


def test_a_proposed_project_is_edited_then_approved(space: Any, pushed: Any) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "project",
            "payload": {
                "goal_id": goal,
                "title": "Reels",
                "owner": "editor",
                "project_kind": "recurring",
                "rhythm": "3 a week",
                "why": "Reels bring followers",
            },
        },
    )
    [shown] = proposals.waiting(core, ws)
    r = client.post(
        f"/workspaces/{ws}/proposals/{shown['id']}",
        json={"choice": "approve", "payload": {"rhythm": "4 reels a week", "owner": "writer"}},
    )
    assert r.status_code == 200, r.text
    [project] = goals.top(core, ws).children[0].children  # type: ignore[union-attr]
    assert (project.rhythm, project.owner, project.level) == ("4 reels a week", "writer", "project")
    # A vision suggestion: the owner's words win when he edits them.
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "vision",
            "payload": {"title": "Grow big", "strategy": "Reels", "why": "Clearer"},
        },
    )
    [suggestion] = proposals.waiting(core, ws)
    assert suggestion["label"] == "Change the Vision: Grow big"
    client.post(
        f"/workspaces/{ws}/proposals/{suggestion['id']}",
        json={"choice": "approve", "payload": {"title": "Grow, my way"}},
    )
    vision = goals.top(core, ws)
    assert vision is not None and (vision.title, vision.strategy) == ("Grow, my way", "Reels")


# ---- the daily plan ---------------------------------------------------------------


def _plan(client: Any, core: Any, ws: str, project: int, **extra: Any) -> dict[str, Any]:
    return _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "daily_plan",
            "payload": {
                "date": today.date_today(),
                "summary": "Two reels and the supplier call",
                "you": [{"title": "Call the argan supplier", "why": "Prices for December"}],
                "members": [
                    {"member": "editor", "title": "Cut reel 12", "project_id": project},
                    {"member": "writer", "title": "Script reel 13", "body": "60 s, a hook"},
                ],
            },
            **extra,
        },
    )


def test_the_daily_plan_is_accepted_into_todays_cards_once(
    space: Any, pushed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    reels = goals.add_project(core, ws, goal, title="Reels", owner="editor")
    made = _plan(client, core, ws, reels)
    assert made.get("proposed") is True, made
    [shown] = proposals.waiting(core, ws)
    assert shown["label"] == f"Today's plan ({today.date_today()})"
    # On Telegram the way asks are posted: the plan's lines, Accept / Skip.
    phone = pushed[-1]
    assert "today's plan" in phone["body"] and "• Call the argan supplier" in phone["body"]
    assert "@editor: Cut reel 12" in phone["body"]
    assert [b[0] for b in phone["buttons"]] == ["Accept", "Skip"]
    assert phone["buttons"][0][1] == f"kask:approve:{shown['id']}"
    # The owner drops one item before accepting.
    r = client.post(
        f"/workspaces/{ws}/proposals/{shown['id']}",
        json={
            "choice": "approve",
            "payload": {
                "members": [{"member": "editor", "title": "Cut reel 12", "project_id": reels}],
            },
        },
    )
    assert r.status_code == 200, r.text
    date = today.date_today()
    cards = _cards(core, ws)
    made_today = {
        c["key"]: c for c in cards.values() if str(c.get("key") or "").startswith("agos-today:")
    }
    assert set(made_today) == {f"agos-today:{date}:0", f"agos-today:{date}:1"}
    reel = made_today[f"agos-today:{date}:0"]
    assert reel["title"] == "Cut reel 12" and reel["assignee"]
    assert reel["body"].startswith(f"## Goal\nProject #{reels}: Reels (goal #{goal}: Audience)")
    mine = made_today[f"agos-today:{date}:1"]
    # His own item is his Founder task: the Board shows it as his, never "Nobody yet".
    assert mine["assignee"] == "founder" and mine["title"] == "Call the argan supplier"
    assert today.OWNER_NOTE in mine["body"]
    # Accepting again (a replay) makes no new card: Hermes's idempotency key.
    again = today.accept(
        core,
        ws,
        proposals._json(
            core.db.execute(
                "SELECT result FROM kanban_asks WHERE id = ?", (shown["id"],)
            ).fetchone()[0]
        )["edited"],
    )
    assert again["cards"] == [reel["id"]] and again["you"] == [mine["id"]]
    assert len(cards) == len({c["id"] for c in cards.values()})
    assert sum(1 for c in cards.values() if str(c.get("key") or "").startswith("agos-today:")) == 2
    # A second plan for the same day is refused: today's is accepted.
    r = _plan(client, core, ws, reels)
    assert "accepted already" in r["error"]
    # The Today column, from the board read the page makes.
    tasks = [
        {
            "id": c["id"],
            "status": c["status"],
            "body": c.get("body") or "",
            "title": c["title"],
            "assignee": c.get("assignee") or "",
            "key": c.get("key") or "",
        }
        for c in cards.values()
    ]
    monkeypatch.setattr(vision_plan_board, "board_tasks", lambda core, ws: (tasks, []))
    view = client.get(f"/workspaces/{ws}/vision").json()
    column = view["today"]
    assert column["plan"]["status"] == "approved" and column["plan"]["askId"] == shown["id"]
    assert [(m["member"], [c["title"] for c in m["cards"]]) for m in column["members"]] == [
        ("editor", ["Cut reel 12"])
    ]
    assert [(i["title"], i["done"]) for i in column["you"]] == [("Call the argan supplier", False)]
    # Each card names the project it serves (its '## Goal' line), for the page's
    # "moves goal" and project lines; a card with no '## Goal' line names none.
    assert column["members"][0]["cards"][0]["goalId"] == reels
    assert column["you"][0]["goalId"] is None
    assert view["vision"]["children"][0]["children"][0]["cards"]["open"] == 1
    # The owner ticks his item: the card is done (only his own items tick).
    from agos_core.actions import kanban_board

    def keyed(core: Any, ws: str, prefix: str) -> list[dict[str, Any]]:
        return [t | {"assignee": t["assignee"]} for t in tasks if t["key"].startswith(prefix)]

    monkeypatch.setattr(kanban_board, "keyed", keyed)
    assert client.post(f"/workspaces/{ws}/vision/today/{mine['id']}/done").status_code == 204
    assert cards[mine["id"]]["status"] == "done"
    assert client.post(f"/workspaces/{ws}/vision/today/{reel['id']}/done").status_code == 404
    assert "accepted (today's cards are on the board)" in goals.status_text(core, ws)


def test_change_sends_the_plan_back_and_skip_ends_it(space: Any, pushed: Any) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    reels = goals.add_project(core, ws, goal, title="Reels", owner="editor")
    _plan(client, core, ws, reels)
    [first] = proposals.waiting(core, ws)
    r = client.post(
        f"/workspaces/{ws}/proposals/{first['id']}",
        json={"choice": "revise", "note": "No supplier call today, I'm travelling"},
    )
    assert r.status_code == 200, r.text
    card = _cards(core, ws)[first["card"]]
    assert card["status"] == "ready"  # the Co-Founder picks it up again
    said = card["comments"][-1]["body"]
    assert "No supplier call today" in said and "kind daily_plan" in said and "revises" in said
    assert "sent back with a note" in goals.status_text(core, ws)
    # The Co-Founder proposes it again, as a new round on a new card.
    _plan(client, core, ws, reels, revises=first["card"])
    [second] = proposals.waiting(core, ws)
    assert second["round"] == 2 and second["card"] != first["card"]
    assert _cards(core, ws)[first["card"]]["status"] == "done"
    # Skip: the card ends, no card of today is made.
    r = client.post(f"/workspaces/{ws}/proposals/{second['id']}", json={"choice": "reject"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert _cards(core, ws)[second["card"]]["summary"].startswith("Skipped by the owner")
    assert not any(
        str(c.get("key") or "").startswith("agos-today:") for c in _cards(core, ws).values()
    )
    assert "skipped by the owner" in goals.status_text(core, ws)


def test_a_bad_plan_is_refused_with_its_reasons(space: Any, pushed: Any) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    r = _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "daily_plan",
            "payload": {"date": "today", "members": [{"member": "ghost", "title": "Boo"}]},
        },
    )
    assert "date (YYYY-MM-DD" in r["error"] and "no member named ghost" in r["error"]
    r = _bridge(
        client,
        core,
        ws,
        {"action": "propose", "kind": "daily_plan", "payload": {"date": today.date_today()}},
    )
    assert "the plan is empty" in r["error"]


# ---- the recap and the weekly review ---------------------------------------------------


def test_the_recap_and_the_weekly_review_reach_the_inbox_and_telegram(
    space: Any, pushed: Any
) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    done = _bridge(
        client,
        core,
        ws,
        {
            "action": "post",
            "kind": "recap",
            "words": "Done: reel 12. Left: script. Tomorrow: script.",
        },
    )
    assert done["posted"] is True
    _bridge(client, core, ws, {"action": "post", "kind": "recap", "words": "Done: all of it."})
    notes = [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "note"
    ]
    assert [(n["title"], n["note"]["kind"]) for n in notes] == [
        (f"Recap — {today.date_today()}", "recap")
    ]  # one a day: the second replaced the words
    assert notes[0]["note"]["detail"] == "Done: all of it."
    assert pushed[-1]["body"].startswith(f"🌙 **Recap — {today.date_today()}**")
    assert pushed[-1]["source"] == f"recap:{ws}:{today.date_today()}"
    status = goals.status_text(core, ws)
    assert "Last recap" in status and "Done: all of it." in status
    _bridge(client, core, ws, {"action": "post", "kind": "weekly", "words": "On track."})
    assert pushed[-1]["body"].startswith("📊 **Weekly review")
    # Only the Co-Founder posts them; a post needs words and a known kind.
    r = _bridge(
        client, core, ws, {"member": "editor", "action": "post", "kind": "recap", "words": "x"}
    )
    assert "Only the Co-Founder" in r["error"]
    assert (
        "recap or weekly"
        in _bridge(client, core, ws, {"action": "post", "kind": "x", "words": "y"})["error"]
    )


# ---- the Co-Founder's three jobs ----------------------------------------------------------


def _root_jobs(core: Any, cron: Any, ws: str) -> dict[str, dict[str, Any]]:
    home = str(core.engine.profile_home(ws))
    return {j["spec"].name: j for j in cron.jobs.values() if j["home"] == home}


def test_the_first_vision_makes_the_three_jobs_in_the_cofounders_cron(space: Any) -> None:
    client, core, cron, ws = space
    assert _root_jobs(core, cron, ws) == {}
    client.put(f"/workspaces/{ws}/vision", json={"title": "Grow"})
    jobs = _root_jobs(core, cron, ws)
    assert {n: j["spec"].schedule for n, j in jobs.items()} == {
        "AGOS daily plan": "0 8 * * *",
        "AGOS recap": "0 20 * * *",
        "AGOS weekly review": "0 17 * * 5",
    }
    assert all(j["spec"].enabled for j in jobs.values())
    rhythm_view = client.get(f"/workspaces/{ws}/vision").json()["rhythm"]
    assert [(j["which"], j["on"], j["time"], j["day"]) for j in rhythm_view] == [
        ("daily", True, "08:00", None),
        ("recap", True, "20:00", None),
        ("weekly", True, "17:00", 5),
    ]
    # Saving the Vision again makes nothing new.
    client.put(f"/workspaces/{ws}/vision", json={"title": "Grow more"})
    assert len(_root_jobs(core, cron, ws)) == 3
    # Re-timed: the same job, a new schedule.
    r = client.put(f"/workspaces/{ws}/vision/rhythm/daily", json={"on": True, "time": "07:30"})
    assert r.status_code == 200, r.text
    assert _root_jobs(core, cron, ws)["AGOS daily plan"]["spec"].schedule == "30 7 * * *"
    r = client.put(
        f"/workspaces/{ws}/vision/rhythm/weekly", json={"on": True, "time": "16:00", "day": 4}
    )
    assert [j["day"] for j in r.json() if j["which"] == "weekly"] == [4]
    # Off: paused with AGOS's reason, its time kept; on again resumes it.
    r = client.put(f"/workspaces/{ws}/vision/rhythm/recap", json={"on": False, "time": "20:00"})
    recap = _root_jobs(core, cron, ws)["AGOS recap"]
    assert recap["enabled"] is False and recap["paused_reason"] == rhythm.OFF_REASON
    shown = next(j for j in r.json() if j["which"] == "recap")
    assert shown["on"] is False and shown["time"] == "20:00" and shown["problem"] is None
    client.put(f"/workspaces/{ws}/vision/rhythm/recap", json={"on": True, "time": "21:00"})
    recap = _root_jobs(core, cron, ws)["AGOS recap"]
    assert recap["enabled"] is True and recap["spec"].schedule == "0 21 * * *"
    assert len(_root_jobs(core, cron, ws)) == 3
    # Refused: a bad time, a weekly job without its day, an unknown job.
    assert (
        client.put(f"/workspaces/{ws}/vision/rhythm/daily", json={"on": True, "time": "25:00"})
    ).status_code == 422
    r = client.put(f"/workspaces/{ws}/vision/rhythm/weekly", json={"on": True, "time": "17:00"})
    assert r.status_code == 400 and "day" in r.text
    r = client.put(f"/workspaces/{ws}/vision/rhythm/nightly", json={"on": True, "time": "17:00"})
    assert r.status_code == 404


def test_the_jobs_prompts() -> None:
    daily, recap, weekly = (rhythm.PROMPTS[w] for w in ("daily", "recap", "weekly"))
    assert "agos_goals with action status" in daily and "last recap" in daily
    assert "`hermes kanban list --status blocked`" in daily
    assert "kind daily_plan" in daily and '"you"' in daily and '"members"' in daily
    assert "Nothing to do." in daily and "stay cheap" in daily
    assert "Never create today's cards yourself" in daily
    assert "Done, Left, Moves to tomorrow" in recap and "kind recap" in recap
    assert "stay cheap" in recap and "Nothing to do." in recap
    assert "kind kr_update" in weekly and "agos_ask_owner" in weekly and "kind weekly" in weekly
    assert "suggest a change" in weekly and "stay cheap" in weekly
    assert rhythm.schedule_of("08:05", None) == "5 8 * * *"
    assert rhythm._when("5 8 * * *") == ("08:05", None) and rhythm._when("*/5 * * * *") is None


def test_accept_on_the_phone_is_the_plans_accept(
    space: Any, pushed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Telegram buttons of today's plan (the asks' kask:approve / kask:reject)."""
    from agos_core.actions import channels
    from agos_core.actions.services.channel import buttons as channel_buttons

    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    reels = goals.add_project(core, ws, goal, title="Reels", owner="editor")
    _plan(client, core, ws, reels)
    assert len(proposals.waiting(core, ws)) == 1
    monkeypatch.setattr(channel_buttons, "_workspace_of_address", lambda core, row, address: {ws})
    happened, said = channels.button(core, {}, "42", pushed[-1]["buttons"][0][1])
    assert happened == "button: proposal approve"
    assert said == "Accepted: today's cards are on the board."
    keys = {str(c.get("key") or "") for c in _cards(core, ws).values()}
    assert {today.key(today.date_today(), n) for n in range(3)} <= keys
