"""Every hire is a card in the owner's Inbox, whole, and only his Approve makes it.

The owner's diagnosis of the 'Visual Designer' hire (2026-11-02, live): the
Co-Founder was in Direct mode, so the member was made on the spot with no card; its
kit was empty (AGOS refused the `kit` field it sent, so it sent the hire again
without it); its model was a bare family with the why inside the model field; and
the old create_agent was still a way to a new agent. Now:
- every hire becomes a card, in every autonomy mode and from every place (a chat, a
  card's worker, an automation's run; a subagent acts from its parent's place);
- a hire is refused (told the agent, which sends it again) unless it carries its
  whole kit (tools, skills, docs, onboarding) and its whole model (an exact version
  of Hermes's catalog, an effort, its why in model_why);
- the approve is refused the same way when the owner's edit took a part out;
- create_agent and update_agent never make a new agent; the owner's own New agent
  (POST /workspaces/{id}/hires) asks for the same kit and model.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run
from work_env import WHOLE_KIT, fake_models, library_skill

from agos_core.actions import (
    agent_profiles,
    cofounder_actions,
    hermes_channel,
    hire_kit,
    proposals,
    team,
)
from agos_core.engine import cofounder_actions as action_rules
from agos_core.engine import config_file

HIRE: dict[str, Any] = {
    "do": "hire_agent",
    "name": "visual-designer",
    "title": "Visual Designer",
    "role": "Designs the carousels and story frames; never writes the text.",
    "why": "Story and carousel ideas wait in todo; nobody on the team makes visuals.",
    "skills": ["writing"],
    "model": {"model": "claude-sonnet-4-5", "effort": "medium"},
    "model_why": "everyday design work -> Sonnet 4.5, medium",
    "kit": WHOLE_KIT,
}
# The live hire as the Co-Founder sent it the second time (after `kit` was refused).
VISUAL_DESIGNER: dict[str, Any] = {
    "do": "hire_agent",
    "goal_id": "2",
    "skills": ["writing"],
    "model": {"effort": "medium", "model": "sonnet", "why": "everyday design -> Sonnet, medium"},
    "name": "visual-designer",
    "reports_to": "",
    "role": "Designs Sam's still and story visuals.",
    "title": "Visual Designer",
    "why": "No member makes visuals: the Script Writer writes, the Video Editor edits video.",
}


@pytest.fixture
def space(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, cron, ws = env
    library_skill(core, ws)  # "writing", in the workspace's library
    fake_models(monkeypatch)  # Hermes's model catalog
    return client, core, cron, ws


def _cofounder_chat(core: Any, ws: str) -> int:
    from agos_core.actions.workers import open_dm

    return int(open_dm(core, ws, None))


def config_of(core: Any, ws: str, member: str) -> dict[str, Any]:
    found: dict[str, Any] = config_file.read(
        core.engine.profile_home(agent_profiles.key(ws, member))
    )
    return found


def _no_member(core: Any, ws: str) -> None:
    assert team.get(core, ws, "visual-designer") is None


# ---- every hire is a card ----------------------------------------------------------------


@pytest.mark.parametrize("mode", ["direct", "ask"])
def test_a_hire_from_a_chat_is_a_card_in_every_mode(space: Any, mode: str) -> None:
    _client, core, cron, ws = space
    cofounder_actions.set_mode(core, mode)  # type: ignore[arg-type]
    # Never an Allow / Deny card from Hermes for it: the hire card is the question.
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [dict(HIRE)]})["ask"] is False
    [card] = _run(core, ws, HIRE)
    assert card["status"] == "done" and card["canUndo"] is False, card
    assert "Nothing is created before your Approve" in card["detail"]
    _no_member(core, ws)
    assert not [j for j in cron.jobs.values() if "hire-review" in j["spec"].name]
    [shown] = proposals.waiting(core, ws)
    assert shown["kind"] == "hire" and shown["payload"]["kit"]["tools"][0]["name"] == "Google Drive"
    assert shown["payload"]["model"]["model"] == "claude-sonnet-4-5"
    assert shown["modelChoices"] is not None  # the card's model picker


@pytest.mark.parametrize("address", ["kanban:t_e545e37b", "cron:abc123def456"])
@pytest.mark.parametrize("mode", ["direct", "ask"])
def test_a_hire_from_a_card_worker_or_an_automation_is_a_card(
    space: Any, address: str, mode: str
) -> None:
    _client, core, _cron, ws = space
    _cofounder_chat(core, ws)
    cofounder_actions.set_mode(core, mode)  # type: ignore[arg-type]
    said = hermes_channel.run_actions(core, ws, address, [dict(HIRE)])
    [result] = said["results"]
    # Done = the card is made (never "waiting" for an Approve of the action itself).
    assert result["status"] == "done", said
    _no_member(core, ws)
    assert [p["kind"] for p in proposals.waiting(core, ws)] == ["hire"]


def test_a_subagent_hires_from_its_parents_place_through_the_same_path(space: Any) -> None:
    # The plugin names a subagent's call by its parent's place (test_run_actions):
    # the core sees the same address, so the same card.
    _client, core, _cron, ws = space
    _cofounder_chat(core, ws)
    hermes_channel.run_actions(core, ws, "kanban:t_parent1", [dict(HIRE)])
    hermes_channel.run_actions(core, ws, "kanban:t_parent1", [{**HIRE, "name": "second-designer"}])
    assert [p["payload"]["name"] for p in proposals.waiting(core, ws)] == [
        "visual-designer",
        "second-designer",
    ]
    assert team.members(core, ws) == []


def test_the_owners_approve_makes_the_member_with_its_kit_and_model(space: Any) -> None:
    client, core, cron, ws = space
    _run(core, ws, HIRE)
    [shown] = proposals.waiting(core, ws)
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    member = team.get(core, ws, "visual-designer")
    assert member is not None and member.skills == ["writing"]
    assert member.model is not None and member.model["model"] == "claude-sonnet-4-5"
    cfg = config_of(core, ws, "visual-designer")
    assert config_file.get(cfg, "model.default") == "claude-sonnet-4-5"
    assert config_file.get(cfg, "agent.reasoning_effort") == "medium"
    kit = hire_kit.kit_of(core, ws, "visual-designer")
    assert kit is not None and kit["docs"][0]["url"] == "https://example.com/style"
    assert kit["onboarding"]["criteria"] == ["short"]
    assert [j for j in cron.jobs.values() if j["spec"].name == "agos-hire-review-visual-designer"]


# ---- what a hire must carry ------------------------------------------------------------


def _refused(core: Any, ws: str, item: dict[str, Any]) -> str:
    [card] = _run(core, ws, item)
    assert card["status"] == "failed", card
    assert proposals.waiting(core, ws) == []
    _no_member(core, ws)
    error: str = card["error"]
    assert "nothing reached the owner" in error and "Send the hire again" in error
    return error


@pytest.mark.parametrize(
    ("kit", "said"),
    [
        ({**WHOLE_KIT, "tools": []}, "kit.tools is empty"),
        ({**WHOLE_KIT, "docs": []}, "kit.docs is empty"),
        ({**WHOLE_KIT, "onboarding": {}}, "kit.onboarding.task is missing"),
        ({**WHOLE_KIT, "onboarding": {"task": "Do it."}}, "kit.onboarding.criteria is empty"),
        ({}, "kit is missing"),
        (None, "kit is missing"),
    ],
)
def test_each_missing_part_of_the_kit_is_refused_with_what_is_missing(
    space: Any, kit: Any, said: str
) -> None:
    _client, core, _cron, ws = space
    item = (
        {**HIRE, "kit": kit} if kit is not None else {k: v for k, v in HIRE.items() if k != "kit"}
    )
    assert said in _refused(core, ws, item)


def test_a_hire_with_no_skill_of_the_library_is_refused(space: Any) -> None:
    _client, core, _cron, ws = space
    kit = {**WHOLE_KIT, "skills": [{"name": "design", "source": "find"}]}
    error = _refused(core, ws, {**HIRE, "skills": [], "kit": kit})
    assert "at least one skill this workspace's library has" in error
    # AGOS's own shared skill is no skill of the role.
    error = _refused(core, ws, {**HIRE, "skills": ["task"], "kit": kit})
    assert "at least one skill" in error
    # A skill the library lacks, named in skills: refused as today.
    assert "install each first" in _refused(core, ws, {**HIRE, "skills": ["ghost"]})


@pytest.mark.parametrize(
    ("model", "why", "said"),
    [
        ({"model": "sonnet", "effort": "medium"}, "w", "is a family, not a version"),
        ({"model": "claude-sonnet-9", "effort": "medium"}, "w", "isn't one Claude offers"),
        ({"model": "claude-sonnet-4-5"}, "w", "model effort is missing"),
        ({"model": "claude-sonnet-4-5", "effort": "medium"}, "", "model_why is missing"),
        ({"model": "claude-sonnet-4-5", "effort": "low", "why": "w"}, "w", "in model_why"),
        ({"model": "sonnet, everyday work", "effort": "low"}, "w", "the why goes in model_why"),
        (None, "w", "model is missing"),
    ],
)
def test_each_wrong_model_is_refused_with_what_to_fix(
    space: Any, model: Any, why: str, said: str
) -> None:
    _client, core, _cron, ws = space
    assert said in _refused(core, ws, {**HIRE, "model": model, "model_why": why})


def test_the_visual_designer_hire_as_sent_is_refused_with_all_of_it(space: Any) -> None:
    _client, core, _cron, ws = space
    error = _refused(core, ws, VISUAL_DESIGNER)
    for said in ("put the why in model_why", "kit is missing"):
        assert said in error, said
    # The first time it sent its kit: AGOS reads the field now (it refused it before).
    assert action_rules.unreadable({**VISUAL_DESIGNER, "kit": WHOLE_KIT}) == []
    action = action_rules._clean({**VISUAL_DESIGNER, "kit": WHOLE_KIT})
    assert action is not None and action.fields["kit"]["tools"][0]["name"] == "Google Drive"


def test_an_owner_edit_that_takes_a_part_out_is_refused_on_the_card(space: Any) -> None:
    client, core, _cron, ws = space
    _run(core, ws, HIRE)
    [shown] = proposals.waiting(core, ws)
    url = f"/workspaces/{ws}/proposals/{shown['id']}"
    for edit, said in (
        ({"kit": {**WHOLE_KIT, "tools": []}}, "kit.tools is empty"),
        ({"kit": {**WHOLE_KIT, "docs": []}}, "kit.docs is empty"),
        ({"kit": {**WHOLE_KIT, "onboarding": {}}}, "kit.onboarding.task is missing"),
        ({"model": None}, "model is missing"),
        ({"model": {"model": "haiku", "effort": "low"}}, "is a family, not a version"),
    ):
        r = client.post(url, json={"choice": "approve", "payload": edit})
        assert r.status_code == 400, edit
        assert said in r.text and "Can't approve as edited" in r.text, r.text
        _no_member(core, ws)
    # His whole edit goes through.
    edit = {"kit": {**WHOLE_KIT, "tools": [{"name": "Canva"}]}}
    r = client.post(url, json={"choice": "approve", "payload": edit})
    assert r.status_code == 200, r.text
    kit = hire_kit.kit_of(core, ws, "visual-designer")
    assert kit is not None and [t["name"] for t in kit["tools"]] == ["Canva"]


# ---- no other road to a new agent --------------------------------------------------------


def test_create_agent_is_the_same_hire_path(space: Any) -> None:
    client, core, _cron, ws = space
    old = {"do": "create_agent", "name": "designer", "instructions": "Designs."}
    [card] = _run(core, ws, old)
    assert card["status"] == "failed"
    assert "create_agent makes no agent any more" in card["error"]
    assert "hire_agent" in card["error"] and "kit is missing" in card["error"]
    assert client.get(f"/workspaces/{ws}/agents").json() == []
    # Sent with everything a hire needs: the same hire card.
    whole = {**HIRE, "do": "create_agent", "name": "designer"}
    assert action_rules.unreadable(whole) == []
    [card] = _run(core, ws, whole)
    assert card["status"] == "done" and card["canUndo"] is False, card
    assert "Nothing is created before your Approve" in card["detail"]
    [shown] = proposals.waiting(core, ws)
    assert shown["payload"]["name"] == "designer" and team.get(core, ws, "designer") is None
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 409  # decided in the Inbox


def test_update_agent_never_makes_a_new_agent(space: Any) -> None:
    client, core, _cron, ws = space
    [card] = _run(core, ws, {"do": "update_agent", "name": "ghost", "instructions": "x"})
    assert card["status"] == "failed" and "a new agent is a hire" in card["error"]
    assert client.get(f"/workspaces/{ws}/agents").json() == []


def test_the_cofounder_is_told_the_rule(space: Any) -> None:
    from agos_core.actions import hire_suggestions, team_design
    from agos_core.hermes_plugin.agos_guard import asks

    _client, core, _cron, ws = space
    text = cofounder_actions.instructions(core, ws)
    assert "- create_agent:" not in text and "create_agent\n  makes no agent" in text
    assert "In EVERY mode (Direct too) this makes a PROPOSAL card" in text
    assert "The kit is REQUIRED and whole" in text
    assert "never is: it is always a card in his Inbox" in text
    skill = team_design.text()
    assert "Every new agent is a hire, in every autonomy mode" in skill
    assert "Every hire carries its WHOLE kit" in skill
    said = str(asks.PROPOSE_SCHEMA["description"])
    assert "the ONLY way to a new agent" in said and "kit (required and whole" in said
    assert "none of them empty" in hire_suggestions.BODY


# ---- the owner's own New agent ---------------------------------------------------------


def _own(**definition: Any) -> dict[str, Any]:
    return {
        "name": "designer",
        "title": "Designer",
        "summary": "Makes the visuals.",
        "definition": {
            "instructions": "Designs the carousels.",
            "model": {"provider": "claude", "model": "claude-haiku-4-5-20251001", "effort": "low"},
            "kit": WHOLE_KIT,
            "reads": [{"path": "flow.md", "mode": "always"}],
            **definition,
        },
    }


def test_the_owners_new_agent_asks_for_the_same_kit_and_model(space: Any) -> None:
    client, core, _cron, ws = space
    url = f"/workspaces/{ws}/hires"
    for definition, said in (
        ({"kit": {}}, "kit is missing"),
        ({"kit": {**WHOLE_KIT, "tools": []}}, "kit.tools is empty"),
        ({"kit": {**WHOLE_KIT, "onboarding": {}}}, "kit.onboarding.task is missing"),
        ({"model": None}, "model is missing"),
        ({"model": {"model": "haiku", "effort": "low"}}, "is a family, not a version"),
    ):
        r = client.post(url, json=_own(**definition))
        assert r.status_code == 400 and said in r.text and "Not created yet" in r.text, r.text
    assert client.get(f"/workspaces/{ws}/agents").json() == []
    # Whole: made at once (his click is his Approve), no card, its kit and model given.
    r = client.post(url, json=_own())
    assert r.status_code == 201, r.text
    assert proposals.waiting(core, ws) == []
    member = team.get(core, ws, "designer")
    assert member is not None and member.model is not None
    assert member.model["model"] == "claude-haiku-4-5-20251001" and member.skills == ["writing"]
    assert [r["path"] for r in member.reads] == ["flow.md"]
    kit = hire_kit.kit_of(core, ws, "designer")
    assert kit is not None and kit["tools"][0]["name"] == "Google Drive"
    revision = core.db.execute(
        "SELECT who, why FROM agent_revisions WHERE workspace_id = ? AND name = 'designer'",
        (ws,),
    ).fetchone()
    assert (revision["who"], revision["why"]) == ("owner", "created by the owner")
    # The same name again: refused, never a second one.
    r = client.post(url, json=_own())
    assert r.status_code == 400 and "already on the team" in r.text
