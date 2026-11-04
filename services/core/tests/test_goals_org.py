"""Step 51: goals + the org chart.

- The workspace goal and its sub-goals: the owner's edits, an agent's proposal the
  owner approves (Inbox kind 'goal'), their one copy in each agent's prompt (its
  SOUL.md, between markers; a member's own sub-goals first), a card's '## Goal' line
  (made with it, set from the modal, inherited from a parent) and the rollup.
- Chain health: a paused / missing / stuck lead stalls its team (Hierarchy, the
  card, ONE Inbox item); a removed lead's reports go to the Co-Founder with a note.
- Cycles: reports_to loops and a hire's loop refused; the guard refuses A -> B -> A.
- The team-design skill, and a hire without a why refused.
- The lost reports_to write (a stale writer, a kept parse) can't happen again.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_team_hierarchy import _agent
from work_env import fake_models, library_skill, whole

from agos_core.actions import goals, hermes_channel, inbox, org, proposals, team
from agos_core.actions.errors import ActionError
from agos_core.engine import goals as rules
from agos_core.engine import identity, profile_meta
from agos_core.hermes_plugin.agos_guard import delegation
from agos_core.hermes_plugin.agos_guard import goals as goals_tool


def _soul(core: Any, ws: str, member: str = "") -> str:
    home = team.home(core, ws, member) if member else core.engine.profile_home(ws)
    assert home is not None
    return (home / "SOUL.md").read_text(encoding="utf-8")


def _board(core: Any, ws: str) -> sqlite3.Connection:
    """Hermes's board, the columns AGOS reads (hermes_cli/kanban_db.py)."""
    from agos_core.actions import agent_profiles

    folder = agent_profiles.board_home(core, ws)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,"
        " assignee TEXT, status TEXT, block_kind TEXT, current_run_id INTEGER,"
        " goal_mode INTEGER, created_by TEXT);"
        "CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY, task_id TEXT,"
        " kind TEXT, payload TEXT, created_at INTEGER);"
        "CREATE TABLE IF NOT EXISTS task_links (parent_id TEXT, child_id TEXT);"
    )
    return db


def _task(
    db: sqlite3.Connection,
    card: str,
    status: str,
    body: str = "",
    *,
    parents: tuple[str, ...] = (),
    assignee: str = "",
    kind: str = "",
    created_by: str = "",
) -> None:
    db.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?, ?, ?, ?, ?, ?, NULL, 0, ?)",
        (card, card, body, assignee or None, status, kind or None, created_by or None),
    )
    if kind:
        db.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'blocked', ?, 1)",
            (card, json.dumps({"kind": kind, "reason": "stuck on it"})),
        )
    for p in parents:
        db.execute("INSERT INTO task_links VALUES (?, ?)", (p, card))
    db.commit()


@pytest.fixture
def space(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, str]:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "head-of-content")
    _agent(client, ws, "writer", reports_to="head-of-content")
    _agent(client, ws, "editor")
    library_skill(core, ws)  # a hire's kit names one skill the library has
    fake_models(monkeypatch)  # and a model of Hermes's catalog
    return client, core, ws


# ---- the plan: the owner's edits and the prompts -----------------------------------


def test_the_vision_its_goals_and_projects_reach_every_prompt_once(space: Any) -> None:
    client, core, ws = space
    assert client.get(f"/workspaces/{ws}/vision").json()["vision"] is None
    r = client.post(f"/workspaces/{ws}/vision/goals", json={"title": "Too early"})
    assert r.status_code == 409  # goals serve a Vision
    r = client.put(
        f"/workspaces/{ws}/vision",
        json={"title": "Grow to 10k followers", "why": "Sponsors", "strategy": "Reels first"},
    )
    assert r.status_code == 200, r.text
    top = r.json()["vision"]
    assert top["level"] == "vision" and top["strategy"] == "Reels first"
    reach = client.post(
        f"/workspaces/{ws}/vision/goals",
        json={"title": "Reach 10k", "owner": "editor", "dueOn": "2027-01-31"},
    ).json()["id"]
    scripts = client.post(
        f"/workspaces/{ws}/vision/goals",
        json={"title": "Scripts ready on Monday", "owner": "writer", "why": "Editing waits"},
    ).json()["id"]
    reels = client.post(
        f"/workspaces/{ws}/vision/goals/{reach}/projects",
        json={
            "title": "Reels",
            "owner": "editor",
            "projectKind": "recurring",
            "rhythm": "4 a week",
        },
    ).json()["id"]
    assert (
        client.post(
            f"/workspaces/{ws}/vision/goals", json={"title": "X", "owner": "ghost"}
        ).status_code
        == 404
    )
    view = client.get(f"/workspaces/{ws}/vision").json()
    assert view["vision"]["id"] == top["id"]
    assert [c["title"] for c in view["vision"]["children"]] == [
        "Reach 10k",
        "Scripts ready on Monday",
    ]
    [project] = view["vision"]["children"][0]["children"]
    assert project["level"] == "project" and project["rhythm"] == "4 a week"
    assert {m["name"] for m in view["members"]} == {"head-of-content", "writer", "editor"}
    # The Co-Founder's SOUL.md: one section, between its markers, every active goal.
    soul = _soul(core, ws)
    assert soul.count(identity.GOAL_START) == 1 and soul.count(identity.GOAL_END) == 1
    section = identity.goal_of(soul)
    assert f"Vision #{top['id']}: Grow to 10k followers" in section
    assert "Strategy: Reels first" in section and "Why: Sponsors" in section
    assert f"- Goal #{reach} Reach 10k — owner @editor, due 2027-01-31" in section
    assert f"  - Project #{reels} Reels (recurring: 4 a week) — owner @editor" in section
    assert '"## Goal"' in section and "agos_goals" in section
    # A member's: the same section, its own goal first and marked; its chain.
    writer = _soul(core, ws, "writer")
    mine = identity.goal_of(writer)
    assert writer.count(identity.GOAL_START) == 1
    assert mine.index(f"#{scripts} Scripts ready on Monday (yours)") < mine.index(f"#{reach}")
    assert (
        "You report to Head-Of-Content (@head-of-content), who reports to the Co-Founder." in writer
    )
    assert "You report to the Co-Founder." in _soul(core, ws, "editor")
    # A dropped goal leaves the prompts.
    assert (
        client.put(
            f"/workspaces/{ws}/vision/items/{scripts}", json={"status": "dropped"}
        ).status_code
        == 204
    )
    assert f"#{scripts}" not in identity.goal_of(_soul(core, ws))
    # A project only serves a goal; it moves to another goal, never under itself.
    r = client.post(f"/workspaces/{ws}/vision/goals/{reels}/projects", json={"title": "Hooks"})
    assert r.status_code == 400 and "serves a goal" in r.text
    r = client.put(f"/workspaces/{ws}/vision/items/{reels}", json={"parentId": reels})
    assert r.status_code == 400
    # Deleting a goal takes its projects and key results with it.
    client.post(f"/workspaces/{ws}/vision/goals/{reach}/results", json={"title": "F", "target": 9})
    assert client.delete(f"/workspaces/{ws}/vision/items/{reach}").status_code == 204
    left = client.get(f"/workspaces/{ws}/vision").json()["vision"]["children"]
    assert [c["title"] for c in left] == ["Scripts ready on Monday"]
    assert core.db.execute("SELECT COUNT(*) FROM key_results").fetchone()[0] == 0
    # The Vision stays (it can change, not go).
    assert client.delete(f"/workspaces/{ws}/vision/items/{top['id']}").status_code == 409
    # Nothing of it is a second copy: one table, the prompts are rendered from it.
    assert (
        core.db.execute("SELECT COUNT(*) FROM goals WHERE workspace_id = ?", (ws,)).fetchone()[0]
        == 2
    )


def test_an_agent_proposes_a_goal_change_and_the_owner_approves_it(space: Any) -> None:
    client, core, ws = space
    goals.set_vision(core, ws, title="Grow to 10k")
    key = hermes_channel.bridge_key(core, ws)
    headers = {"authorization": f"Bearer {key}"}
    url = f"/hermes-bridge/{ws}/goals"
    # Without a why: refused, told why.
    r = client.post(
        url,
        json={
            "member": "editor",
            "action": "propose",
            "kind": "goal",
            "payload": {"title": "Shorts"},
        },
        headers=headers,
    )
    assert "why" in r.json()["error"]
    r = client.post(
        url,
        json={
            "member": "editor",
            "action": "propose",
            "kind": "goal",
            "payload": {
                "title": "Post 3 shorts a day",
                "owner": "editor",
                "why": "Shorts bring most new followers",
            },
        },
        headers=headers,
    )
    assert r.json().get("proposed") is True, r.text
    [shown] = proposals.waiting(core, ws)
    assert shown["kind"] == "goal" and shown["label"] == "Add the goal: Post 3 shorts a day"
    assert shown["payload"]["change"] == "add_goal"
    assert goals.top(core, ws).children == []  # type: ignore[union-attr]
    item = next(
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "proposal"
    )
    assert item["proposal"]["kind"] == "goal"
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    [sub] = goals.top(core, ws).children  # type: ignore[union-attr]
    assert sub.title == "Post 3 shorts a day" and sub.owner == "editor" and sub.level == "goal"
    card = core.engine.runner.kanban[core.engine.profile(ws)][shown["card"]]
    assert card["status"] == "done"
    assert "(yours)" in identity.goal_of(_soul(core, ws, "editor"))
    # The status the heartbeat reads.
    r = client.post(url, json={"action": "status"}, headers=headers)
    assert (
        "Post 3 shorts a day" in r.json()["status"]
        and "0 done, 0 open, 0 blocked" in r.json()["status"]
    )


# ---- cards: the '## Goal' line and the rollup ---------------------------------------


def test_a_card_made_for_a_project_carries_its_goal_line(space: Any) -> None:
    client, core, ws = space
    goals.set_vision(core, ws, title="Grow to 10k")
    goal = goals.add_goal(core, ws, title="Reach 10k")
    reels = goals.add_project(core, ws, goal, title="Ship 4 reels a week", owner="editor")
    r = client.post(
        f"/workspaces/{ws}/kanban",
        json={"title": "Reel 12", "body": "Cut it.", "member": "editor", "goalId": reels},
    )
    assert r.status_code == 201, r.text
    card_id = r.json()["id"]
    raw = core.engine.runner.kanban[core.engine.profile(ws)][card_id]
    assert (
        raw["body"]
        == f"## Goal\nProject #{reels}: Ship 4 reels a week (goal #{goal}: Reach 10k)\n\nCut it."
    )
    board = client.get(f"/workspaces/{ws}/kanban").json()
    [shown] = [c for c in board["cards"] if c["id"] == card_id]
    assert (
        shown["goalId"] == reels and shown["goalInherited"] is False and shown["body"] == "Cut it."
    )
    assert [(g["title"], g["level"]) for g in board["goals"]] == [
        ("Grow to 10k", "vision"),
        ("Reach 10k", "goal"),
        ("Ship 4 reels a week", "project"),
    ]
    # The modal picks another (Hermes's kanban edit --body), or none.
    assert (
        client.put(f"/workspaces/{ws}/kanban/{card_id}/goal", json={"goalId": goal}).status_code
        == 204
    )
    assert raw["body"].startswith(f"## Goal\nGoal #{goal}: Reach 10k (toward: Grow to 10k)")
    assert raw["body"].endswith("Cut it.") and raw["body"].count("## Goal") == 1
    assert (
        client.put(f"/workspaces/{ws}/kanban/{card_id}/goal", json={"goalId": None}).status_code
        == 204
    )
    assert raw["body"] == "Cut it."
    assert (
        client.put(f"/workspaces/{ws}/kanban/{card_id}/goal", json={"goalId": 999}).status_code
        == 404
    )
    # A card made before step 53 ("Sub-goal #") is read the same way.
    assert rules.card_goal(f"## Goal\nSub-goal #{reels}: old words\n\nx") == reels


def test_the_rollup_counts_each_goals_cards_from_one_board_read(space: Any) -> None:
    _client, core, ws = space
    top = goals.set_vision(core, ws, title="Grow")
    reach = goals.add_goal(core, ws, title="Reach")
    reels = goals.add_project(core, ws, reach, title="Reels")
    hooks = goals.add_project(core, ws, reach, title="Hooks")
    scripts = goals.add_goal(core, ws, title="Scripts")

    def line(g: int) -> str:
        return f"## Goal\nProject #{g}: x\n\nwork"

    db = _board(core, ws)
    _task(db, "t1", "done", line(reels))
    _task(db, "t2", "running", line(reels))
    _task(db, "t3", "blocked", line(hooks))
    _task(db, "t4", "ready", parents=("t3",))  # inherits Hooks from its parent
    _task(db, "t5", "done", line(scripts))
    _task(db, "t6", "archived", line(scripts))  # archived: counted nowhere
    _task(db, "t7", "todo")  # no goal
    counts = goals.rollup(core, ws)
    assert counts[hooks] == {"done": 0, "open": 1, "blocked": 1}
    assert counts[reels] == {"done": 1, "open": 1, "blocked": 0}
    assert counts[reach] == {"done": 1, "open": 2, "blocked": 1}  # its projects'
    assert counts[scripts] == {"done": 1, "open": 0, "blocked": 0}
    assert counts[top] == {"done": 2, "open": 2, "blocked": 1}
    view = goals.view(core, ws)
    shown = view["vision"]["children"][0]
    assert shown["cards"] == {"done": 1, "open": 2, "blocked": 1}
    assert shown["progress"] == 0.25  # no key result yet: its cards
    assert shown["children"][0]["progress"] == 0.5
    assert rules.card_goals({"a": ("todo", line(5))}, []) == {"a": (5, False)}
    # The inherited goal shows on the board too (the same read as the cards).
    from agos_core.actions import kanban_board

    extra = kanban_board._extra(core, ws)
    assert extra["t4"]["goal_id"] == hooks


# ---- the org chart ------------------------------------------------------------------


def test_chain_health_is_derived_from_the_profiles() -> None:
    P = org.Person
    found = {
        "head": P("head", "Head", "", True),
        "a": P("a", "A", "head", True),
        "b": P("b", "B", "a", True),
        "c": P("c", "C", "ghost", True),
    }
    h = org.derive(found)
    assert h.chains["b"] == ["a", "head"] and h.stalls == {"c": org.Stall("ghost", "missing", "")}
    paused = org.derive({**found, "head": P("head", "Head", "", False)})
    assert {m: s.why for m, s in paused.stalls.items()} == {
        "a": "paused",
        "b": "paused",
        "c": "missing",
    }
    assert paused.stalls["b"].lead == "head"
    stuck = org.derive(found, {"a": 2})
    assert stuck.stalls["b"] == org.Stall("a", "stuck", "A") and "a" not in stuck.stalls
    loop = org.derive({"x": P("x", "X", "y", True), "y": P("y", "Y", "x", True)})
    assert loop.stalls["x"].why == "loop"
    item = org.inbox_item(paused)
    assert item is not None and item["title"].startswith("Team stalled: 3 members")
    assert item["key"] != org.inbox_item(stuck)["key"]  # type: ignore[index]
    assert org.inbox_item(org.derive({"head": P("head", "Head", "", True)})) is None


def test_a_paused_lead_stalls_its_team_everywhere_the_owner_looks(space: Any) -> None:
    client, core, ws = space
    head = team.home(core, ws, "head-of-content")
    assert head is not None
    profile_meta.set_parked(head, True)  # Hermes's parked marker: off the team
    teamview = client.get(f"/workspaces/{ws}/workers").json()
    assert teamview["org"]["writer"]["stalled"] == {
        "lead": "head-of-content",
        "why": "paused",
        "words": "Head-Of-Content is paused",
    }
    assert teamview["org"]["writer"]["chain"] == [
        {"name": "head-of-content", "title": "Head-Of-Content"}
    ]
    assert teamview["org"]["head-of-content"]["stalls"] == ["writer"]
    assert teamview["org"]["editor"]["stalled"] is None
    items = [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "chain"
    ]
    assert len(items) == 1 and items[0]["chain"]["leads"][0]["members"] == ["writer"]
    # The writer's cards say so.
    r = client.post(f"/workspaces/{ws}/kanban", json={"title": "Draft", "member": "writer"})
    card_id = r.json()["id"]
    [shown] = [
        c for c in client.get(f"/workspaces/{ws}/kanban").json()["cards"] if c["id"] == card_id
    ]
    assert shown["chainStalled"] == "Head-Of-Content is paused"
    # Dismissed: gone until what stalls whom changes.
    client.post(f"/workspaces/{ws}/inbox/marks", json={"key": items[0]["key"], "mark": "dismissed"})
    assert not [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "chain"
    ]


def test_a_stuck_lead_stalls_its_team(space: Any) -> None:
    client, core, ws = space
    db = _board(core, ws)
    _task(db, "t1", "blocked", assignee="a-head-of-content", kind="needs_input")
    entry = client.get(f"/workspaces/{ws}/workers").json()["org"]
    assert entry["head-of-content"]["stuckCards"] == 1
    assert entry["writer"]["stalled"]["why"] == "stuck"


def test_removing_a_lead_moves_its_reports_and_leaves_a_note(space: Any) -> None:
    client, core, ws = space
    lead = next(
        a for a in client.get(f"/workspaces/{ws}/agents").json() if a["name"] == "head-of-content"
    )
    goals.set_vision(core, ws, title="Grow")
    owned = goals.add_goal(core, ws, title="Scripts", owner="head-of-content")
    before = inbox.count(core, ws)
    assert client.delete(f"/workspaces/{ws}/agents/{lead['id']}").status_code == 204
    assert team.get(core, ws, "writer").reports_to == ""  # type: ignore[union-attr]
    [note] = [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "note"
    ]
    assert note["title"] == "@head-of-content left the team: 1 report now report to the Co-Founder"
    assert "@writer" in note["note"]["detail"]
    assert inbox.count(core, ws) == before + 1
    client.post(f"/workspaces/{ws}/inbox/marks", json={"key": note["key"], "mark": "read"})
    assert inbox.count(core, ws) == before
    assert goals._one(core, ws, owned).owner == ""  # its sub-goal has no owner now
    assert "You report to the Co-Founder." in _soul(core, ws, "writer")


# ---- cycles -------------------------------------------------------------------------


def test_a_hire_whose_lead_would_loop_or_is_unknown_is_refused(space: Any) -> None:
    _client, core, ws = space
    hire = whole(
        {
            "name": "researcher",
            "title": "Researcher",
            "role": "Finds sources.",
            "why": "Scripts wait on facts for sub-goal #2; nobody researches.",
        }
    )
    with pytest.raises(ActionError, match="no member named ghost"):
        proposals.propose(core, ws, "hire", {**hire, "reports_to": "ghost"})
    with pytest.raises(ActionError, match="itself"):
        proposals.propose(core, ws, "hire", {**hire, "reports_to": "researcher"})
    made = proposals.propose(core, ws, "hire", {**hire, "reports_to": "writer"})
    assert made["proposed"] is True
    # A pending hire may be a lead; a loop through pending hires (a new round of
    # the first one under the second) is refused.
    proposals.propose(core, ws, "hire", {**hire, "name": "lead-r", "reports_to": "researcher"})
    with pytest.raises(ActionError, match="loop"):
        proposals.propose(core, ws, "hire", {**hire, "reports_to": "lead-r"})


def test_the_guard_refuses_handing_work_back_to_who_delegated_it() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_by TEXT);"
        "CREATE TABLE task_links (parent_id TEXT, child_id TEXT);"
        "INSERT INTO tasks VALUES ('t_root', 'Launch', 'running', 'owner');"
        "INSERT INTO tasks VALUES ('t_a', 'Write the script', 'running', 'a-lead');"
        "INSERT INTO tasks VALUES ('t_b', 'Research', 'running', 'a-writer');"
        "INSERT INTO tasks VALUES ('t_old', 'Old', 'done', 'a-editor');"
        "INSERT INTO task_links VALUES ('t_root', 't_a');"
        "INSERT INTO task_links VALUES ('t_a', 't_b');"
        "INSERT INTO task_links VALUES ('t_old', 't_b');"
    )
    # The writer works t_b (made by itself under t_a, which the lead made for it):
    # handing a child back to the lead is the loop.
    said = delegation.check(
        {"assignee": "a-lead", "parents": []}, me="a-writer", current="t_b", conn=db
    )
    assert "Delegation loop" in said and "t_a" in said and "agos_ask_owner" in said
    said = delegation.check(
        {"assignee": "a-lead", "parents": ["t_b"]}, me="a-writer", current="", conn=db
    )
    assert "Delegation loop" in said
    # Not a loop: another member, itself, the owner's card, a done ancestor's author.
    assert (
        delegation.check({"assignee": "a-researcher"}, me="a-writer", current="t_b", conn=db) == ""
    )
    assert delegation.check({"assignee": "a-writer"}, me="a-writer", current="t_b", conn=db) == ""
    assert delegation.check({"assignee": "owner"}, me="a-writer", current="t_b", conn=db) == ""
    assert delegation.check({"assignee": "a-editor"}, me="a-writer", current="t_b", conn=db) == ""
    # Up to the Co-Founder: allowed (Paperclip refuses nothing about direction).
    assert delegation.check({"assignee": "default"}, me="a-writer", current="t_b", conn=db) == ""


def test_the_guard_hook_blocks_the_loop_through_hermes_board(
    monkeypatch: Any, tmp_path: Path
) -> None:
    import sys
    import types

    from agos_core.hermes_plugin import agos_guard

    board = tmp_path / "kanban.db"
    db = sqlite3.connect(board)
    db.executescript(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, created_by TEXT);"
        "CREATE TABLE task_links (parent_id TEXT, child_id TEXT);"
        "INSERT INTO tasks VALUES ('t_a', 'Script', 'running', 'a-lead');"
    )
    db.commit()
    db.close()
    fake = types.ModuleType("hermes_cli.kanban_db_connect")
    fake.connect = lambda: sqlite3.connect(board)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_connect", fake)
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    sys.modules["hermes_cli"].kanban_db_connect = fake  # type: ignore[attr-defined]
    monkeypatch.setattr(agos_guard.runtime, "_own_profile", lambda: "a-writer")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_a")
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "writer"})
    verdict, _asks = agos_guard._verdict(
        "kanban_create", {"assignee": "a-lead", "title": "x"}, "s1"
    )
    assert (
        verdict is not None
        and verdict["action"] == "block"
        and "Delegation loop" in verdict["message"]
    )


# ---- team design --------------------------------------------------------------------


# ---- the heartbeat and the plugin ----------------------------------------------------


def test_the_cofounders_heartbeat_reads_the_real_goal() -> None:
    from agos_core.actions import heartbeat

    text = heartbeat.prompt_for(None, cofounder_lines=True)
    assert "agos_goals with action status" in text and "'## Goal' line" in text
    assert "agos_goals" not in heartbeat.prompt_for("writer", cofounder_lines=False)


def test_the_goals_tool_is_registered_and_posts_to_agos() -> None:
    registered: list[dict[str, Any]] = []

    class Ctx:
        def register_tool(self, **kw: Any) -> None:
            registered.append(kw)

    sent: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        sent.append((path, body))
        return {"status": "Goal #1: Grow"}

    goals_tool.register(
        Ctx(), member_of=lambda: "editor", post=post, guard=lambda _n: contextlib.nullcontext()
    )
    [tool] = registered
    assert tool["name"] == "agos_goals" and tool["toolset"] == "agos"
    assert json.loads(tool["handler"]({"action": "status"})) == {"status": "Goal #1: Grow"}
    assert sent == [
        (
            "goals",
            {
                "member": "editor",
                "action": "status",
                "kind": "",
                "payload": {},
                "words": "",
                "revises": "",
            },
        )
    ]


# ---- the lost reports_to write -------------------------------------------------------


def test_seven_reports_to_in_a_row_all_stick_even_with_a_stale_writer(env: Any) -> None:  # noqa: F811
    """Live: 7 set_reports_to in a row lost one. A writer that read the member before
    the move (a save of its title, a hire's sync) put the old lead back: team.write
    rewrote ui_meta.agos from what it had read, and Hermes's `profile describe`
    rewrote the whole profile.yaml outside the lock. Now a write keeps a lead it
    didn't change, and every profile.yaml write starts from the file under its lock."""
    client, core, _cron, ws = env
    names = ["topics", "ideas", "research", "voice", "script", "media", "video"]
    for n in [*names, "head-content", "head-production"]:
        _agent(client, ws, n)
    stale = {n: team.get(core, ws, n) for n in names}  # read before the moves
    plan = {n: "head-content" for n in names[:5]} | {n: "head-production" for n in names[5:]}
    for n, boss in plan.items():
        team.set_reports_to(core, ws, n, boss)
    for n in names:  # the stale writers land after the moves
        agent = stale[n]
        assert agent is not None
        team.write(
            core,
            ws,
            n,
            title=agent.title + " (renamed)",
            summary=agent.summary,
            definition=agent.definition,
            local=agent.local,
            reports_before=agent.reports_to,
        )
    assert {n: team.get(core, ws, n).reports_to for n in names} == plan  # type: ignore[union-attr]
    # A save that does change the lead still moves it.
    agent = team.get(core, ws, "media")
    assert agent is not None
    team.write(
        core,
        ws,
        "media",
        title=agent.title,
        summary=agent.summary,
        definition={**agent.definition, "reports_to": ""},
        local=agent.local,
        reports_before=agent.reports_to,
    )
    assert team.get(core, ws, "media").reports_to == ""  # type: ignore[union-attr]


def test_a_profile_yaml_write_never_starts_from_a_kept_parse(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Another process (Hermes, another AGOS) rewrote profile.yaml in a way the kept
    parse's stamp can't see (same size, same tick, a reused inode): the write still
    starts from the file, so what the other writer put there stays."""
    from agos_core.engine import read_cache

    home = tmp_path / "a-media"
    home.mkdir()
    (home / "profile.yaml").write_text("display_name: Media\nui_meta:\n  agos:\n    reads: []\n")
    monkeypatch.setattr(read_cache, "file_stamp", lambda *_p: (1, 1, 1))  # the blind stamp
    assert profile_meta.read(home)["display_name"] == "Media"  # parsed and kept
    (home / "profile.yaml").write_text(
        "display_name: Media\ndescription: Hermes wrote this\nui_meta:\n  agos:\n    reads: []\n"
    )
    with profile_meta.locked(home):
        profile_meta.write(home, agos_facts={"reads": [], "reports_to": "head-production"})
    data = profile_meta.read_fresh(home)
    assert data["description"] == "Hermes wrote this"
    assert data["ui_meta"]["agos"]["reports_to"] == "head-production"
