"""Goals and hires: the team-design skill a hire needs (always the shipped text, kept in
the background), and a new hire naming the open goal it serves, refused for a skill the
workspace lacks, its review scheduled on approval and taken back by Undo.

Split out of test_goals_org.py (the vision, goals, projects and reporting lines stay there)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_goals_org import space  # noqa: F401
from work_env import WHOLE_KIT, whole

from agos_core.actions import goals, proposals, team, team_design
from agos_core.actions.errors import ActionError
from agos_core.engine import proposals as rules_proposals


def test_the_team_design_skill_is_installed_and_a_hire_needs_its_why(space: Any) -> None:  # noqa: F811
    _client, core, ws = space
    from agos_core.actions import workspace_skills

    hire = {"name": "researcher", "title": "Researcher", "role": "Finds sources."}
    with pytest.raises(ActionError, match="why is missing"):
        proposals.propose(core, ws, "hire", hire)
    with pytest.raises(ActionError, match="why is missing"):
        proposals.propose(core, ws, "hire", {**hire, "why": "need help"})  # too thin
    found = workspace_skills.existing_dir(core, ws, team_design.NAME)
    assert found is not None
    text = (found / "SKILL.md").read_text(encoding="utf-8")
    for rule in (
        "exact gap",
        "Start small",
        "One clear role",
        "reports_to",
        "Prefer moving reports_to",
    ):
        assert rule in text, rule
    assert team_design.ensure(core, ws) is False  # once per start
    # The Co-Founder's hire action follows the same rule in direct mode.
    from test_cofounder_actions import _run

    [card] = _run(
        core, ws, {"do": "hire_agent", "name": "researcher", "title": "Researcher", "role": "r"}
    )
    assert card["status"] == "failed" and "why is missing" in card["error"]


def _skill_text(core: Any, ws: str) -> str:
    from agos_core.actions import workspace_skills

    found = workspace_skills.existing_dir(core, ws, team_design.NAME)
    assert found is not None
    return (found / "SKILL.md").read_text(encoding="utf-8")


def _install(core: Any, ws: str, text: str) -> None:
    """The workspace's team-design skill as it was left (by AGOS or the owner)."""
    from agos_core.actions import workspace_skills

    team_design.ensure(core, ws)
    workspace_skills._write(core, ws, team_design.NAME, text)
    team_design._done.clear()  # a new start of the core


def test_the_skill_is_always_kept_at_the_shipped_text(space: Any) -> None:  # noqa: F811
    _client, core, ws = space
    from agos_core.actions import skill_versions

    older = team_design.text().replace("## Before you send the hire", "## Old section")
    _install(core, ws, older)  # an older AGOS's text
    assert team_design.ensure(core, ws) is True
    text = _skill_text(core, ws)
    assert text.strip() == team_design.text().strip()
    for rule in (
        "Before you send the hire",
        "short paragraph",
        "Wider reach",
        "No heartbeat or routines",
        "No secrets",
        "goal_id",
        "source_card",
        "7 days",
        "exact gap",
        "Prefer moving reports_to",
        "3 or more members",
    ):
        assert rule in text, rule
    # A version AGOS wrote (Hermes's skill_manage, labelled as AGOS's).
    assert any(label[1] == "agos" for labels in skill_versions._labels.values() for label in labels)
    team_design._done.clear()
    assert team_design.ensure(core, ws) is False  # already the shipped text: nothing written
    # An edit (the Co-Founder's, or one made before it went to the background): AGOS's
    # own skill goes back to the shipped text at the next start.
    edited = team_design.text().rstrip() + "\n\nMy own rule: hire writers only on Mondays.\n"
    _install(core, ws, edited)
    assert team_design.ensure(core, ws) is True
    assert _skill_text(core, ws).strip() == team_design.text().strip()


def test_the_skill_stays_in_the_background(space: Any) -> None:  # noqa: F811
    client, core, ws = space
    from agos_core.actions import workspace_skills

    team_design.ensure(core, ws)
    # The space's own skill "writing" is there already (the hires' kit names it).
    assert workspace_skills.existing_dir(core, ws, "writing") is not None
    # Still on disk, in the Co-Founder's own skill folder (Hermes's index reads it).
    assert workspace_skills.existing_dir(core, ws, team_design.NAME) is not None
    assert team_design.NAME in workspace_skills.names(core, ws)
    # Never on the owner's Skills page, his switches, his copy lists or the exports.
    names = [s["name"] for s in client.get(f"/workspaces/{ws}/skills").json()]
    assert names == ["writing"]
    connectors = client.get(f"/workspaces/{ws}/connectors").json()
    assert team_design.NAME not in {c["name"] for c in connectors if c["kind"] == "skill"}
    assert "writing" in {c["name"] for c in connectors if c["kind"] == "skill"}
    from agos_core.actions import cofounder_actions, portability
    from agos_core.db import library as repo

    row = repo.find_item(core.db, "skill", team_design.NAME, ws)
    assert row is not None and workspace_skills.hidden(row)
    r = client.put(f"/workspaces/{ws}/connectors/{row['id']}", json={"on": False})
    assert r.status_code == 404  # the owner can't switch it off either
    assert team_design.NAME not in {s.name for s in portability._skills(core, ws)}
    assert team_design.NAME not in {
        str(r["name"]) for r in cofounder_actions._mine(core, ws, "skill")
    }


def _old_hire(**more: Any) -> dict[str, Any]:
    return {
        "name": "researcher",
        "title": "Researcher",
        "role": "Finds the sources the scripts need; never writes them; hands to @writer.",
        "why": "Scripts wait on facts; nobody on the team researches.",
        **more,
    }


def _hire(**more: Any) -> dict[str, Any]:
    """A hire as it is sent now: with its whole kit and model."""
    return whole(_old_hire(**more))


def test_a_new_hire_names_the_open_goal_it_serves(space: Any) -> None:  # noqa: F811
    client, core, ws = space
    # No goals at all: goal_id may be left out, but a made-up one is refused.
    with pytest.raises(ActionError, match="has none"):
        proposals.propose(core, ws, "hire", _hire(goal_id=7))
    vision = goals.set_vision(core, ws, title="Grow to 10k")
    reach = goals.add_goal(core, ws, title="Reach 10k")
    old = goals.add_goal(core, ws, title="Old launch")
    goals.update_item(core, ws, old, {"status": "done"})
    reels = goals.add_project(core, ws, reach, title="Reels")
    with pytest.raises(ActionError, match="goal_id is missing") as missing:
        proposals.propose(core, ws, "hire", _hire())
    assert f"#{reach} Reach 10k" in missing.value.message
    assert f"#{old}" not in missing.value.message  # done: not offered
    for bad in (999, vision, old):
        with pytest.raises(ActionError, match="not an open goal"):
            proposals.propose(core, ws, "hire", _hire(goal_id=bad))
    made = proposals.propose(core, ws, "hire", _hire(goal_id=f"#{reels}", source_card="t_42"))
    [shown] = proposals.waiting(core, ws)
    assert shown["card"] == made["card"]
    assert shown["payload"]["goal_id"] == reels and shown["payload"]["source_card"] == "t_42"
    assert shown["serves"] == {
        "id": reels,
        "title": "Reels",
        "level": "project",
        "status": "active",
    }
    # The Inbox's read carries it (the hire card's "Serves" line).
    [item] = client.get(f"/workspaces/{ws}/inbox").json()["items"]
    assert item["proposal"]["serves"]["title"] == "Reels"
    # A paused goal still counts as open.
    goals.update_item(core, ws, reach, {"status": "paused"})
    proposals.propose(core, ws, "hire", _hire(name="r2", goal_id=reach))
    # The goal goes: the waiting card says so (one goals read for the whole list).
    goals.delete_item(core, ws, reach)
    assert [p["serves"]["title"] for p in proposals.waiting(core, ws)] == [None, None]


def test_a_hire_asking_for_a_skill_the_workspace_lacks_is_refused(space: Any) -> None:  # noqa: F811
    _client, core, ws = space
    with pytest.raises(ActionError, match="skills not in this workspace's library: ghost-skill"):
        proposals.propose(core, ws, "hire", _hire(skills=["task", "ghost-skill"]))
    team_design.ensure(core, ws)
    # The Co-Founder's background skill is never given to a hire.
    with pytest.raises(ActionError, match="only the Co-Founder uses"):
        proposals.propose(core, ws, "hire", _hire(skills=["task", team_design.NAME]))
    # AGOS's own skills (/task) are fine.
    made = proposals.propose(core, ws, "hire", _hire(skills=["task"]))
    assert made["proposed"] is True


def test_an_old_waiting_hire_without_goal_id_is_still_decided(space: Any) -> None:  # noqa: F811
    client, core, ws = space
    goals.set_vision(core, ws, title="Grow to 10k")
    goals.add_goal(core, ws, title="Reach 10k")
    # Recorded before the hire checks: no goal_id, a skill nobody has, no kit, no model.
    payload = rules_proposals.clean("hire", _old_hire(skills=["old-skill"]))
    body = rules_proposals.block("hire", payload)
    card = json.loads(core.engine._hermes(ws, "kanban", "create", "P", "--json", "--body", body))
    ask = proposals.record(core, ws, str(card["id"]), "", "hire", payload)
    assert ask is not None
    [shown] = proposals.waiting(core, ws)
    assert shown["problems"] == [] and shown["serves"] is None
    assert rules_proposals.digest("hire", shown["payload"]) == rules_proposals.digest(
        "hire", payload
    )
    # It stays as it is; its approve needs what every hire needs now.
    r = client.post(f"/workspaces/{ws}/proposals/{ask}", json={"choice": "approve"})
    assert r.status_code == 400 and "kit is missing" in r.text and "model is missing" in r.text
    assert team.get(core, ws, "researcher") is None
    # He fills its kit and picks its model in the card: approved.
    edits = {"kit": WHOLE_KIT, "model": {"model": "claude-haiku-3-5", "effort": "low"}}
    r = client.post(
        f"/workspaces/{ws}/proposals/{ask}", json={"choice": "approve", "payload": edits}
    )
    assert r.status_code == 200, r.text
    hired = team.get(core, ws, "researcher")
    assert hired is not None and hired.model is not None
    assert hired.model["model"] == "claude-haiku-3-5"


def test_approving_a_hire_schedules_its_review_and_undo_removes_it(space: Any) -> None:  # noqa: F811
    client, core, ws = space
    from datetime import datetime

    from agos_core.actions import hire_review

    cron = core.engine.cron_bridge
    goals.set_vision(core, ws, title="Grow to 10k")
    reach = goals.add_goal(core, ws, title="Reach 10k")
    made = proposals.propose(
        core, ws, "hire", _hire(goal_id=reach, reports_to="writer", source_card="t_9")
    )
    r = client.post(f"/workspaces/{ws}/proposals/{made['ask_id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    [job] = [j for j in cron.jobs.values() if j["spec"].name == "agos-hire-review-researcher"]
    spec = job["spec"]
    assert job["home"] == str(core.engine.profile_home(ws))  # the Co-Founder's own cron
    due = datetime.fromisoformat(spec.schedule)  # a one-shot: an ISO time
    days = (due - datetime.now(due.tzinfo)).total_seconds() / 86400
    assert hire_review.REVIEW_AFTER_DAYS - 0.01 < days <= hire_review.REVIEW_AFTER_DAYS
    assert spec.deliver == "agos" and spec.failure_deliver == "agos"
    for words in (
        "@researcher (Researcher)",
        f"sub-goal #{reach} 'Reach 10k'",
        "Scripts wait on facts",
        "[SILENT]",
        "agos_propose",
        "reports_to move",
        "whether to remove the member",
    ):
        assert words in spec.prompt, words
    row = core.db.execute(
        "SELECT result FROM kanban_asks WHERE id = ?", (made["ask_id"],)
    ).fetchone()
    assert json.loads(row["result"])["review_job"] == job["id"]
    # Undo of the hire: the review goes too.
    r = client.post(f"/workspaces/{ws}/proposals/{made['ask_id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert job["id"] not in cron.jobs


def test_a_review_job_hermes_refuses_never_fails_the_hire(space: Any) -> None:  # noqa: F811
    client, core, ws = space
    cron = core.engine.cron_bridge
    made = proposals.propose(core, ws, "hire", _hire())
    cron.down = True  # Hermes's cron refuses everything
    r = client.post(f"/workspaces/{ws}/proposals/{made['ask_id']}", json={"choice": "approve"})
    cron.down = False
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    assert team.get(core, ws, "researcher") is not None
    row = core.db.execute(
        "SELECT result FROM kanban_asks WHERE id = ?", (made["ask_id"],)
    ).fetchone()
    assert "review_job" not in json.loads(row["result"])
    assert client.post(f"/workspaces/{ws}/proposals/{made['ask_id']}/undo").status_code == 200
