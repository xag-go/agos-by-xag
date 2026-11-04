"""A hire's model, sized to the role's work: the Co-Founder proposes the exact
version and reasoning effort from Hermes's model catalog (the workspace's own
provider only; an unknown id is refused with the ones it can use; a family alone, no
effort, a why or free text inside the model field, or no model at all is refused),
with its why in model_why; the owner may change it in the card's kit editor before
Approve (taking it out is refused), and the approve writes it into the member's
Hermes profile through the team's own code (model.*, agent.reasoning_effort). The card
shows why; the Readiness checklist's Model item shows the one Hermes runs it on."""

from __future__ import annotations

from typing import Any

import pytest
from test_cofounder_actions import _run
from test_hire_kit import HIRE, KIT, fakes  # noqa: F401  (fixture)
from work_env import CATALOG, Env, env, fake_board, fake_models  # noqa: F401  (fixtures)

from agos_core.actions import agent_profiles, cofounder_actions, hire_model, proposals, team
from agos_core.engine import config_file
from agos_core.engine import hire_kit as rules

CLAUDE: list[dict[str, Any]] = CATALOG[0]["models"]
SMALL = {"model": "claude-haiku-4-5-20251001", "effort": "low"}
WHY = "small repetitive work -> Haiku 4.5, low"
SIZED = {"model": SMALL, "model_why": WHY}


def _resolve(raw: Any, models: list[dict[str, Any]] | None = CLAUDE) -> tuple[Any, list[str]]:
    return rules.resolve_model(raw, provider="claude", label="Claude", mode="cli", models=models)


def _config(core: Any, ws: str, member: str) -> dict[str, Any]:
    home = core.engine.profile_home(agent_profiles.key(ws, member))
    found: dict[str, Any] = config_file.read(home)
    return found


def _item(core: Any, ws: str, member: str = "video-editor") -> dict[str, Any]:
    from agos_core.actions import hire_kit

    view = hire_kit.readiness(core, ws, member)
    assert view is not None
    found: dict[str, Any] = next(i for i in view["items"] if i["id"] == "model")
    return found


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_models(monkeypatch)


def test_the_model_is_resolved_against_the_catalog() -> None:
    # A family: its newest version in the catalog (the date suffix doesn't win over 4.5).
    model, problems = _resolve({"model": "haiku", "effort": "low"})
    assert problems == []
    assert model == {
        "provider": "claude",
        "mode": "cli",
        "model": "claude-haiku-4-5-20251001",
        "effort": "low",
    }
    assert _resolve("opus")[0]["model"] == "claude-opus-5-5"
    assert _resolve({"model": "Claude Sonnet 4.5"})[0]["model"] == "claude-sonnet-4-5"
    # An exact id; no effort = the model's own default; Hermes's provider name is fine.
    model, _ = _resolve({"provider": "anthropic", "model": "claude-sonnet-5"})
    assert model is not None and (model["model"], model["effort"]) == ("claude-sonnet-5", "medium")
    # Unknown: refused, with the ones it can use.
    model, problems = _resolve({"model": "claude-opus-9"})
    assert model is None and "claude-opus-9" in problems[0] and "claude-sonnet-5" in problems[0]
    assert "claude-haiku-4-5-20251001" in _resolve({"model": "gpt-5.4"})[1][0]
    # Another provider, an effort the model doesn't take, no catalog.
    assert "workspace's provider" in _resolve({"provider": "openai", "model": "gpt-5.4"})[1][0]
    assert "pick one of low, medium, high" in _resolve({"model": "haiku", "effort": "max"})[1][0]
    assert "didn't list" in _resolve(SMALL, None)[1][0]
    # Missing: the workspace's model (a member's later change, update_agent).
    assert _resolve(None) == (None, []) and _resolve({"effort": "low"}) == (None, [])


def _hire(raw: Any, models: list[dict[str, Any]] | None = CLAUDE) -> tuple[Any, list[str]]:
    return rules.resolve_model(
        raw, provider="claude", label="Claude", mode="cli", models=models, hire=True
    )


def test_a_new_members_model_is_whole() -> None:
    # An exact version and its effort: taken as is.
    model, problems = _hire(SMALL)
    assert problems == [] and model is not None and model["model"] == SMALL["model"]
    assert _hire({"model": "Claude Sonnet 4.5", "effort": "medium"})[0]["model"] == (
        "claude-sonnet-4-5"
    )
    # A family alone is no version: refused with that family's versions, newest first.
    model, problems = _hire({"model": "sonnet", "effort": "medium"})
    assert model is None and "is a family, not a version" in problems[0]
    assert "claude-sonnet-5, claude-sonnet-4-5" in problems[0]
    # No effort, an effort the version doesn't take.
    assert (
        "model effort is missing: pick one of low, medium, high"
        in _hire({"model": "claude-sonnet-5"})[1][0]
    )
    assert "isn't one" in _hire({"model": "claude-sonnet-5", "effort": "max"})[1][0]
    # The why (or anything else) put inside model: sent to its own field.
    model, problems = _hire({"model": "claude-sonnet-5", "effort": "low", "why": "fits"})
    assert model is None and "put the why in model_why" in problems[0]
    # Free text in the version: not in the catalog, and told where the why goes.
    problems = _hire({"model": "sonnet because it writes well", "effort": "low"})[1]
    assert "isn't one Claude offers" in problems[0] and "model_why" in problems[0]
    # No model at all.
    for none in (None, {}, "", {"effort": "low"}):
        assert _hire(none)[1] == [rules.NO_MODEL], none
    # Hermes lists nothing now: no hire falls back on the workspace's model.
    assert "try again" in _hire(SMALL, None)[1][0]
    assert rules.model_family("claude-opus-5-5") == "opus" and rules.model_family("gpt-5.4") == ""
    assert rules.model_line({"model": "claude-haiku-4-5", "effort": "low"}) == (
        "claude-haiku-4-5 · low"
    )


def test_a_hire_proposes_a_model_sized_to_the_role(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],  # noqa: F811
    models: None,
) -> None:
    _client, _fake, core, ws = env
    proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT, **SIZED})
    [shown] = proposals.waiting(core, ws)
    payload = shown["payload"]
    assert payload["model"] == {
        "provider": "claude",
        "mode": "cli",
        "model": "claude-haiku-4-5-20251001",
        "effort": "low",
    }
    assert payload["model_why"] == "small repetitive work -> Haiku 4.5, low"
    # The card's picker: the workspace's provider only, by family, with each one's levels.
    choices = shown["modelChoices"]
    assert choices["provider"] == "claude" and choices["label"] == "Claude"
    assert {m["family"] for m in choices["models"]} == {"haiku", "sonnet", "opus"}
    assert choices["workspace"] == {"model": "claude-sonnet-5", "effort": "high"}
    assert all(m["efforts"] == ["low", "medium", "high", "none"] for m in choices["models"])
    # An unknown id is refused at the door, with the models it can use.
    other = {**HIRE, "name": "other", "kit": KIT, **SIZED}
    with pytest.raises(Exception, match="isn't one Claude offers this workspace") as refused:
        proposals.propose(core, ws, "hire", {**other, "model": {**SMALL, "model": "gpt-5.4"}})
    assert "claude-sonnet-5" in str(refused.value)
    assert "nothing reached the owner" in str(refused.value)
    # Each part of the model the owner's diagnosis named: refused, with what to fix.
    for model, why, said in (
        ({"model": "sonnet", "effort": "medium"}, WHY, "is a family, not a version"),
        ({"model": "claude-sonnet-5"}, WHY, "model effort is missing"),
        ({**SMALL, "why": WHY}, WHY, "put the why in model_why"),
        (SMALL, "", "model_why is missing"),
        (None, WHY, "model is missing"),
        # The Visual Designer's hire, as it was sent (a family, its why inside model).
        ({"effort": "medium", "model": "sonnet", "why": "everyday design"}, "", "model_why"),
    ):
        with pytest.raises(Exception, match=said):
            proposals.propose(core, ws, "hire", {**other, "model": model, "model_why": why})
    assert len(proposals.waiting(core, ws)) == 1  # none of them reached the owner


def test_approve_writes_the_model_and_effort_into_the_members_hermes_profile(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],  # noqa: F811
    models: None,
) -> None:
    client, _fake, core, ws = env
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT, **SIZED})
    r = client.post(f"/workspaces/{ws}/proposals/{made['ask_id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    assert r.json()["editedPayload"] is None  # as proposed
    cfg = _config(core, ws, "video-editor")
    assert config_file.get(cfg, "model.default") == "claude-haiku-4-5-20251001"
    assert config_file.get(cfg, "model.provider") == "anthropic"
    assert config_file.get(cfg, "agent.reasoning_effort") == "low"
    member = team.get(core, ws, "video-editor")
    assert member is not None and member.model is not None
    assert (member.model["model"], member.model["effort"]) == ("claude-haiku-4-5-20251001", "low")
    # Readiness shows the one Hermes runs it on.
    item = _item(core, ws)
    assert item["ok"] and item["label"] == "Model: claude-haiku-4-5-20251001 · low"
    # The Co-Founder's update_agent still sets a member's model (the same path).
    [card] = _run(
        core,
        ws,
        {
            "do": "update_agent",
            "name": "video-editor",
            "model": {
                "provider": "claude",
                "mode": "cli",
                "model": "claude-opus-5-5",
                "effort": "high",
            },
        },
    )
    assert card["status"] == "done", card
    cfg = _config(core, ws, "video-editor")
    assert config_file.get(cfg, "model.default") == "claude-opus-5-5"
    assert config_file.get(cfg, "agent.reasoning_effort") == "high"
    assert _item(core, ws)["label"] == "Model: claude-opus-5-5 · high"
    from agos_core.engine import cofounder_actions as prompt_rules

    assert prompt_rules.unreadable({"do": "update_agent", "name": "a", "model": "haiku"}) == []
    [card] = _run(core, ws, {"do": "update_agent", "name": "video-editor", "model": "gpt-5.4"})
    assert card["status"] == "failed" and "isn't one Claude offers" in str(card["error"])
    [card] = _run(core, ws, {"do": "update_agent", "name": "video-editor", "model": "workspace"})
    assert card["status"] == "done", card
    member = team.get(core, ws, "video-editor")
    assert member is not None and member.model is None


def test_the_owner_changes_the_model_before_approve(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],  # noqa: F811
    models: None,
) -> None:
    client, _fake, core, ws = env
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT, **SIZED})
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    # An id the workspace can't use is refused; the proposal still waits.
    bad = client.post(
        url,
        json={
            "choice": "approve",
            "payload": {"model": {"model": "claude-opus-9", "effort": "high"}},
        },
    )
    assert bad.status_code == 400 and "isn't one Claude offers" in bad.text
    assert proposals.waiting(core, ws)[0]["status"] == "waiting"
    # His pick: Opus 5.5, high.
    r = client.post(
        url,
        json={
            "choice": "approve",
            "payload": {"model": {"model": "claude-opus-5-5", "effort": "high"}},
        },
    )
    assert r.status_code == 200, r.text
    edited = r.json()["editedPayload"]
    assert edited["model"]["model"] == "claude-opus-5-5"
    assert edited["model_why"] == hire_model.OWNERS_CHOICE
    assert r.json()["payload"]["model"]["model"] == "claude-haiku-4-5-20251001"  # as proposed
    cfg = _config(core, ws, "video-editor")
    assert config_file.get(cfg, "model.default") == "claude-opus-5-5"
    assert config_file.get(cfg, "agent.reasoning_effort") == "high"
    assert _item(core, ws)["label"] == "Model: claude-opus-5-5 · high"


def test_a_hire_without_its_own_model_is_never_made(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    fake_models(monkeypatch)
    # He takes the model out in the editor (model null): refused on the card.
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT, **SIZED})
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    r = client.post(url, json={"choice": "approve", "payload": {"model": None}})
    assert r.status_code == 400 and "model is missing" in r.text and "Put it back" in r.text
    assert team.get(core, ws, "video-editor") is None
    assert proposals.waiting(core, ws)[0]["status"] == "waiting"
    # His family pick without a version is refused the same way.
    edit = {"model": {"model": "opus", "effort": "high"}}
    r = client.post(url, json={"choice": "approve", "payload": edit})
    assert r.status_code == 400 and "is a family, not a version" in r.text
    # No model proposed (Hermes listing models or not): refused at the door.
    found: list[dict[str, Any]] | None
    for found in (None, []):
        fake_models(monkeypatch, found)
        with pytest.raises(Exception, match="model is missing"):
            proposals.propose(core, ws, "hire", {**HIRE, "name": "two", "kit": KIT, "model": None})


def test_a_checked_model_stands_while_hermes_cant_list_them(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    fake_models(monkeypatch)
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT, **SIZED})
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    fake_models(monkeypatch, [])  # Hermes lists nothing now
    edit = {"choice": "approve", "payload": {"model": {"model": "opus", "effort": "high"}}}
    assert client.post(url, json=edit).status_code == 400  # his new pick can't be checked
    r = client.post(url, json={"choice": "approve"})  # as proposed: checked already
    assert r.status_code == 200, r.text
    cfg = _config(core, ws, "video-editor")
    assert config_file.get(cfg, "model.default") == "claude-haiku-4-5-20251001"


def test_the_cofounder_is_told_to_size_the_model(env: Env) -> None:  # noqa: F811
    from agos_core.actions import hire_suggestions, team_design
    from agos_core.hermes_plugin.agos_guard import asks

    _client, _fake, core, ws = env

    skill = team_design.text()
    for words in (
        "small repetitive work -> Haiku, low",
        "effort low",
        "(opus)",
        '"model_why"',
        "A family alone",
    ):
        assert words in skill, words
    text = cofounder_actions.instructions(core, ws)
    assert "model (REQUIRED" in text and "model_why (REQUIRED, its own field" in text
    assert 'a family\n  alone like "sonnet" is refused' in text
    said = str(asks.PROPOSE_SCHEMA["description"])
    assert "small repetitive work = small model + low" in said
    assert "model_why (required, its own field" in said and "never a bare family" in said
    assert "model_why in its own field" in hire_suggestions.BODY
