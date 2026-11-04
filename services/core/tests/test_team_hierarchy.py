"""The Co-Founder hires from a chat: in every mode (Direct and Ask) it is a proposal
card the owner decides in his Inbox; only his Approve creates the member (Undo
there removes it).
The team is an org chart: who reports to whom lives in each member's Hermes
profile, never a loop, and a leaving member's reports go to the Co-Founder."""

from __future__ import annotations

from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run
from work_env import WHOLE_KIT, fake_models

from agos_core.actions import cofounder_actions, proposals, team
from agos_core.actions.services.cofounder import agent_tools
from agos_core.engine import cofounder_actions as rules

HIRE = {
    "do": "hire_agent",
    "name": "script-writer",
    "title": "Script Writer",
    "role": "Writes the scripts.",
    "skills": ["writing"],
    "model": {"provider": "anthropic", "model": "claude-sonnet-4-5", "effort": "medium"},
    "model_why": "everyday writing -> Sonnet, medium",
    "kit": WHOLE_KIT,
    "telegram_topic": False,
    "coding_engine": "codex",
    "why": "We need scripts every week.",
}


@pytest.fixture(autouse=True)
def _models(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_models(monkeypatch)  # the hire's model is checked against Hermes's catalog


def _writing(core: Any, ws: str) -> None:
    """The skill the hire asks for, in this workspace's library (AGOS refuses a hire
    whose skill the workspace lacks)."""
    from agos_core.actions import workspace_skills
    from agos_core.engine import library as lib

    workspace_skills.create(
        core,
        ws,
        "writing",
        title="Writing",
        given={"text": lib.skill_template("writing", "Use when writing a script.", "# Writing")},
    )


def test_the_cofounder_learns_to_hire_propose_and_use_real_titles(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    text = cofounder_actions.instructions(core, ws)
    for words in (
        "hire_agent",
        "agos_propose",
        "agos_ask_owner",
        "@<member name>: <what you need>",
        "reports_to",
        "job title",
        "revises",
        "SOUL.md",
    ):
        assert words in text, words
    [action] = [a for a in (rules._clean(dict(HIRE)),) if a is not None]
    assert (
        action.fields["skills"] == ["writing"]
        and action.fields["model"]["model"] == "claude-sonnet-4-5"
    )
    assert rules.title_of(action) == "Hire “Script Writer” (@script-writer)"
    assert rules.unreadable(dict(HIRE)) == []


def test_direct_mode_makes_a_card_and_only_the_approve_hires(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    assert cofounder_actions.mode(core) == "direct"
    [card] = _run(core, ws, HIRE)
    assert card["status"] == "failed" and "writing" in card["error"]  # not in the library
    assert "install each first" in card["error"]
    _writing(core, ws)
    [card] = _run(core, ws, HIRE)
    # Direct mode too: a card in his Inbox, nothing made, nothing to undo here.
    assert card["status"] == "done" and card["canUndo"] is False, card
    assert "Nothing is created before your Approve" in card["detail"]
    assert team.get(core, ws, "script-writer") is None
    assert not [j for j in cron.jobs.values() if "hire-review" in j["spec"].name]
    [shown] = proposals.waiting(core, ws)
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 409  # decided in the Inbox
    # His Approve hires it, with its kit and model.
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    # The Co-Founder's review of the hire, a week out, in its own cron.
    [review] = [j for j in cron.jobs.values() if j["spec"].name == "agos-hire-review-script-writer"]
    assert review["home"] == str(core.engine.profile_home(ws))
    hired = team.get(core, ws, "script-writer")
    assert hired is not None and hired.title == "Script Writer" and hired.skills == ["writing"]
    assert hired.model is not None and hired.model["model"] == "claude-sonnet-4-5"
    from agos_core.actions import hire_kit

    kit = hire_kit.kit_of(core, ws, "script-writer")
    assert kit is not None and [t["name"] for t in kit["tools"]] == ["Google Drive"]
    assert kit["onboarding"]["task"] == WHOLE_KIT["onboarding"]["task"]
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert team.get(core, ws, "script-writer") is None
    assert review["id"] not in cron.jobs  # its review went with it


def test_ask_mode_proposes_a_card_instead_of_creating(env: Any) -> None:  # noqa: F811
    from agos_core.actions import hermes_channel

    client, core, _cron, ws = env
    _writing(core, ws)
    cofounder_actions.set_mode(core, "ask")
    # No Allow / Deny card from Hermes for a hire: the proposal is the question.
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [dict(HIRE)]})["ask"] is False
    both = {
        "actions": [
            dict(HIRE),
            {"do": "create_skill", "name": "s", "description": "d", "instructions": "i"},
        ]
    }
    check = hermes_channel.tool_check(core, "agos_action", both)
    assert check["ask"] is True and "Hire" not in check["message"]
    [card] = _run(core, ws, HIRE)
    assert card["status"] == "done" and card["canUndo"] is False
    assert "Inbox" in card["detail"] and "Nothing is created" in card["detail"]
    assert team.get(core, ws, "script-writer") is None
    [shown] = proposals.waiting(core, ws)
    assert shown["kind"] == "hire" and shown["payload"]["coding_engine"] == "codex"
    assert shown["member"] == ""  # the Co-Founder proposed
    # The card is Hermes's, unassigned (no worker claims it) and blocked for him.
    hermes_card = core.engine.runner.kanban[core.engine.profile(ws)][shown["card"]]
    assert hermes_card["status"] == "blocked" and hermes_card["assignee"] is None
    assert "```agos-proposal" in str(hermes_card["body"]) and "We need scripts" in str(
        hermes_card["body"]
    )
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 409  # a proposal is decided in the Inbox, not undone
    # Approving it in the Inbox makes the member.
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    assert team.get(core, ws, "script-writer") is not None


# ---- the org chart ---------------------------------------------------------------------


def _agent(client: Any, ws: str, name: str, **definition: Any) -> int:
    r = client.post(
        f"/workspaces/{ws}/agents",
        json={
            "name": name,
            "title": name.title(),
            "definition": {"instructions": "x", **definition},
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_reports_to_lives_in_the_profile_and_never_loops(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    lead = _agent(client, ws, "lead")
    writer = _agent(client, ws, "writer", reports_to="lead")
    assert team.get(core, ws, "writer").reports_to == "lead"  # type: ignore[union-attr]
    assert team.get(core, ws, "lead").reports_to == ""  # type: ignore[union-attr]
    # In Hermes's profile metadata, nowhere else.
    from agos_core.engine import profile_meta

    home = team.home(core, ws, "writer")
    assert home is not None
    assert profile_meta.agos(profile_meta.read(home))["reports_to"] == "lead"
    assert core.db.execute("PRAGMA table_info(library_items)").fetchall()
    assert not any(
        c["name"] == "reports_to" for c in core.db.execute("PRAGMA table_info(library_items)")
    )
    # The web reads it with the agent.
    [found] = [a for a in client.get(f"/workspaces/{ws}/agents").json() if a["name"] == "writer"]
    assert found["definition"]["reports_to"] == "lead"
    # Loops: itself, a direct loop, a longer one.
    r = client.put(f"/workspaces/{ws}/agents/{lead}/reports-to", json={"reportsTo": "lead"})
    assert r.status_code == 400 and "itself" in r.text
    r = client.put(f"/workspaces/{ws}/agents/{lead}/reports-to", json={"reportsTo": "writer"})
    assert r.status_code == 400 and "loop" in r.text
    _agent(client, ws, "junior", reports_to="writer")
    r = client.put(f"/workspaces/{ws}/agents/{lead}/reports-to", json={"reportsTo": "junior"})
    assert r.status_code == 400 and "loop" in r.text
    # Unknown, or another workspace's member: refused.
    r = client.put(f"/workspaces/{ws}/agents/{lead}/reports-to", json={"reportsTo": "ghost"})
    assert r.status_code == 404
    assert team.get(core, ws, "lead").reports_to == ""  # type: ignore[union-attr]
    # A real move, and back to the Co-Founder.
    r = client.put(f"/workspaces/{ws}/agents/{writer}/reports-to", json={"reportsTo": ""})
    assert r.status_code == 204
    assert team.get(core, ws, "writer").reports_to == ""  # type: ignore[union-attr]
    r = client.put(f"/workspaces/{ws}/agents/{writer}/reports-to", json={"reportsTo": "lead"})
    assert r.status_code == 204
    assert team.get(core, ws, "writer").reports_to == "lead"  # type: ignore[union-attr]


def test_deleting_a_member_moves_its_reports_to_the_cofounder(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    lead = _agent(client, ws, "lead")
    _agent(client, ws, "writer", reports_to="lead")
    _agent(client, ws, "editor", reports_to="lead")
    _agent(client, ws, "junior", reports_to="writer")
    assert client.delete(f"/workspaces/{ws}/agents/{lead}").status_code == 204
    assert team.get(core, ws, "writer").reports_to == ""  # type: ignore[union-attr]
    assert team.get(core, ws, "editor").reports_to == ""  # type: ignore[union-attr]
    assert team.get(core, ws, "junior").reports_to == "writer"  # type: ignore[union-attr]


def test_update_agent_moves_a_member_in_the_org_chart_and_undo_moves_it_back(
    env: Any,  # noqa: F811
) -> None:
    client, core, _cron, ws = env
    _agent(client, ws, "content-lead")
    _agent(client, ws, "production-lead")
    _agent(client, ws, "intake", reports_to="production-lead")
    move = {"do": "update_agent", "name": "intake", "reports_to": "@content-lead"}
    assert rules.unreadable(dict(move)) == []
    [card] = _run(core, ws, move)
    assert card["status"] == "done" and card["canUndo"], card
    moved = team.get(core, ws, "intake")
    assert moved is not None and moved.reports_to == "content-lead"
    assert moved.instructions == "x"  # nothing else of it changed
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 200 and r.json()["status"] == "undone", r.text
    assert team.get(core, ws, "intake").reports_to == "production-lead"  # type: ignore[union-attr]
    # "cofounder" = straight under the Co-Founder; another update keeps the lead.
    [card] = _run(core, ws, {"do": "update_agent", "name": "intake", "reports_to": "cofounder"})
    assert card["status"] == "done" and team.get(core, ws, "intake").reports_to == ""  # type: ignore[union-attr]
    _run(core, ws, {"do": "update_agent", "name": "intake", "reports_to": "content-lead"})
    [card] = _run(core, ws, {"do": "update_agent", "name": "intake", "title": "Media Intake"})
    assert card["status"] == "done"
    assert team.get(core, ws, "intake").reports_to == "content-lead"  # type: ignore[union-attr]
    # A loop or a member that isn't there: failed, never a "done" that moved nothing.
    [card] = _run(core, ws, {"do": "update_agent", "name": "content-lead", "reports_to": "intake"})
    assert card["status"] == "failed" and "loop" in str(card["error"]), card
    [card] = _run(core, ws, {"do": "update_agent", "name": "intake", "reports_to": "ghost"})
    assert card["status"] == "failed", card
    assert team.get(core, ws, "intake").reports_to == "content-lead"  # type: ignore[union-attr]


def test_a_field_update_agent_does_not_read_is_refused_not_done(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    from agos_core.actions import hermes_channel

    assert rules.unreadable({"do": "update_agent", "name": "a", "manager": "b"}) == ["manager"]
    assert rules.unreadable({"do": "update_agent", "name": "a", "skills": ["s"]}) == ["skills"]
    assert rules.unreadable({"do": "update_mcp", "name": "a", "reports_to": "b"}) == ["reports_to"]
    assert rules.unreadable({"do": "update_skill", "name": "a", "files": {"x": "y"}}) == []
    assert rules.unreadable({"do": "create_mcp", "name": "a", "url": "https://x"}) == []
    # Other actions keep their own (wider) fields.
    assert rules.unreadable({"do": "create_automation", "name": "a", "schedule": "x"}) == []
    _client, core, _cron, ws = env
    text = cofounder_actions.instructions(core, ws)
    assert "reports_to (agent only" in text
    _agent(_client, ws, "intake")
    monkeypatch.setattr(agent_tools, "_chat_turn", lambda *_a: (1, 1))
    out = hermes_channel.run_actions(
        core, ws, "agos:1", [{"do": "update_agent", "name": "intake", "manager": "x"}]
    )
    [refused] = out["results"]
    assert refused["status"] == "failed" and "manager" in refused["error"]
    assert "reports_to" in refused["error"]  # it lists the fields it does read
