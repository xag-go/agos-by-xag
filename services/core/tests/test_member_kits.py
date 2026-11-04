"""A kit for a member already on the team (actions/member_kits.py): members hired
before kits (or with a kit missing a part) are found; "Suggest kit" puts ONE card on
the Co-Founder per member (never two while one is open or its proposal waits); the
Co-Founder's 'Kit for @x' proposal is checked like a hire's kit; Approve writes it
through the hire's own code (the model and skills through the team's save, the kit
through hire_kit.provision) and keeps the member's memory; Reject leaves it as it
was; Undo puts it back; the Co-Founder can do the same from a chat (always a card)."""

from __future__ import annotations

from typing import Any

import pytest
from work_env import (  # noqa: F401  (fixtures)
    WHOLE_KIT,
    WHOLE_MODEL,
    Env,
    agent,
    env,
    fake_board,
    fake_models,
    kanban_of,
)

from agos_core.actions import (
    agent_profiles,
    cofounder_more,
    hire_kit,
    member_kits,
    proposals,
    team,
)
from agos_core.actions.errors import ActionError
from agos_core.actions.services.hire import kit_rules as hire_kit_rules
from agos_core.actions.services.hire import readiness as hire_readiness
from agos_core.actions.services.proposals import hire_checks as proposal_checks
from agos_core.engine import cofounder_parity as parity
from agos_core.engine import hire_kit as rules
from agos_core.engine import identity
from agos_core.engine import proposals as proposal_rules


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[str]]:
    """What Hermes has, as the checks read it: library skills, connectors, keys."""
    have: dict[str, set[str]] = {"skills": {"writing"}, "apps": set(), "keys": set()}
    fake_models(monkeypatch)
    # hire_kit looks it up in the facade, the hire checks in their own module.
    for mod in (proposals, proposal_checks):
        monkeypatch.setattr(mod, "_skill_here", lambda core, ws, name: name in have["skills"])
    monkeypatch.setattr(hire_kit_rules, "_catalog", lambda core: {"google-drive": "Google Drive"})
    monkeypatch.setattr(hire_readiness, "_connected", lambda core, ws: set(have["apps"]))
    monkeypatch.setattr(hire_readiness, "_keys", lambda core, ws: set(have["keys"]))
    return have


def _kit_payload(member: str = "writer", **more: Any) -> dict[str, Any]:
    return {
        "member": member,
        "kit": WHOLE_KIT,
        **WHOLE_MODEL,
        "why": "It writes the scripts every week but has no style guide or test.",
        **more,
    }


def _workers(client: Any, ws: str) -> dict[str, dict[str, Any]]:
    r = client.get(f"/workspaces/{ws}/workers")
    assert r.status_code == 200, r.text
    return {m["name"]: m for m in r.json()["members"]}


def _memory(core: Any, ws: str, member: str) -> list[str]:
    home = core.engine.profile_home(agent_profiles.key(ws, member))
    return list(identity.read_memory(home, "memory").entries)


# ---- detection -------------------------------------------------------------------------


def test_members_without_a_whole_kit_are_found(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    for name in ("writer", "editor", "designer"):
        agent(client, ws, name)
    # writer: hired before kits (none). editor: a kit with no tools or test.
    # designer: a whole kit.
    hire_kit.save_kit(core, ws, "editor", {"skills": [{"name": "writing"}], "docs": []})
    hire_kit.save_kit(core, ws, "designer", WHOLE_KIT)
    assert member_kits.state(core, ws, "writer") == "none"
    assert member_kits.state(core, ws, "editor") == "incomplete"
    assert member_kits.state(core, ws, "designer") == "whole"
    assert sorted(member_kits.lacking(core, ws)) == ["editor", "writer"]
    shown = _workers(client, ws)
    assert {n: m["kit"] for n, m in shown.items()} == {
        "writer": "none",
        "editor": "incomplete",
        "designer": "whole",
    }
    assert all(m["kitCard"] is None for m in shown.values())
    # The same whole-kit rule a hire meets: no library skill = incomplete.
    fakes["skills"].clear()
    assert member_kits.state(core, ws, "designer") == "incomplete"
    # The pure rule.
    assert rules.kit_state(None, 0) == "none"
    assert rules.kit_state({"tools": []}, 0) == "none"
    assert rules.kit_state(rules.clean_kit(WHOLE_KIT), 1) == "whole"
    assert rules.kit_state(rules.clean_kit(WHOLE_KIT), 0) == "incomplete"


# ---- the ask -----------------------------------------------------------------------------


def test_suggest_kit_makes_one_card_per_member(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    from agos_core.actions import kanban_board

    monkeypatch.setattr(
        kanban_board,
        "latest_of",
        lambda core, ws, member, limit=10: [
            {"id": "t_9", "title": "Script for reel 4", "status": "done", "result": "sent"}
        ],
    )
    url = f"/workspaces/{ws}/workers/writer/suggest-kit"
    r = client.post(url, json={"note": "It keeps missing our tone."})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["created"] is True and first["card"]
    card = kanban_of(core, ws)[first["card"]]
    assert card["assignee"] == core.engine.hermes_name(ws)  # the Co-Founder
    assert card["title"] == "Suggest a kit for @writer"
    assert str(card["key"]).startswith(f"{member_kits.KEY}writer:")
    body = str(card["body"])
    for words in (
        "hired before kits existed",
        "You are writer.",  # its role
        "t_9 [done] Script for reel 4",  # what it has done
        "team-design skill",
        'kind "kit"',
        "model_why in its own field",
        "source_card",
        "Change nothing of the member yourself",
        "It keeps missing our tone.",
    ):
        assert words in body, words
    # Pressed again while it is open: the same card, nothing new.
    again = client.post(url, json={}).json()
    assert again == {"card": first["card"], "created": False}
    assert len(kanban_of(core, ws)) == 1
    assert _workers(client, ws)["writer"]["kitCard"] == first["card"]
    # The Co-Founder proposed; its ask is done; the proposal now waits: still one.
    made = proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    card["status"] = "done"
    assert client.post(url, json={}).json() == {"card": made["card"], "created": False}
    assert _workers(client, ws)["writer"]["kitCard"] == made["card"]
    # A second kit for the same member while one waits is refused (no duplicate).
    with pytest.raises(ActionError, match="already waits for the owner"):
        proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    # Unknown member / a whole kit already: no card.
    assert client.post(f"/workspaces/{ws}/workers/ghost/suggest-kit", json={}).status_code == 404
    hire_kit.save_kit(core, ws, "writer", WHOLE_KIT)
    core.db.execute("UPDATE kanban_asks SET status = 'rejected' WHERE kind = 'kit'")
    assert client.post(url, json={}).status_code == 409
    assert client.post("/workspaces/nope/workers/writer/suggest-kit", json={}).status_code == 404


def test_suggest_kits_for_all_one_card_each_one_after_the_other(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    for name in ("a1", "a2", "a3", "a4", "done-one"):
        agent(client, ws, name)
    hire_kit.save_kit(core, ws, "done-one", WHOLE_KIT)
    member_kits.ask(core, ws, "a1")  # asked for already
    monkeypatch.setattr(member_kits, "MAX_ALL", 2)
    r = client.post(f"/workspaces/{ws}/team/suggest-kits", json={})
    assert r.status_code == 200, r.text
    made = r.json()
    assert [a["member"] for a in made["asked"]] == ["a2", "a3"]
    assert [a["member"] for a in made["already"]] == ["a1"]
    assert made["left"] == 1
    cards = kanban_of(core, ws)
    first, second = (cards[a["card"]] for a in made["asked"])
    # Sequential: each waits on the one before (the open a1 ask first).
    opened = [c for c in cards.values() if str(c["key"]).startswith(f"{member_kits.KEY}a1:")]
    assert list(first.get("parents") or []) == [opened[0]["id"]]
    assert list(second.get("parents") or []) == [first["id"]]
    # The next press asks for the rest; then nothing is left; never a second card each.
    again = client.post(f"/workspaces/{ws}/team/suggest-kits", json={}).json()
    assert [a["member"] for a in again["asked"]] == ["a4"] and again["left"] == 0
    last = client.post(f"/workspaces/{ws}/team/suggest-kits", json={}).json()
    assert last["asked"] == [] and len(last["already"]) == 4
    keys = [
        str(c["key"])
        for c in kanban_of(core, ws).values()
        if str(c["key"]).startswith(member_kits.KEY)
    ]
    assert len(keys) == 4 and len({k.rsplit(":", 1)[0] for k in keys}) == 4


# ---- the proposal, approve, reject, undo -----------------------------------------------------


def _waiting(core: Any, ws: str) -> dict[str, Any]:
    [shown] = proposals.waiting(core, ws)
    return shown


def test_a_kit_proposal_is_checked_like_a_hire_kit(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    for payload, said in (
        (_kit_payload("ghost"), "no member named ghost"),
        (_kit_payload(kit={**WHOLE_KIT, "tools": []}), "kit.tools is empty"),
        (_kit_payload(kit={}), "kit is missing"),
        (_kit_payload(model=None), "model is missing"),
        (_kit_payload(model_why=""), "model_why is missing"),
        (_kit_payload(model={"model": "sonnet", "effort": "medium"}), "a family, not a version"),
    ):
        with pytest.raises(ActionError, match="This kit was not proposed") as err:
            proposals.propose(core, ws, "kit", payload, by_tool=True)
        assert said in str(err.value), (said, str(err.value))
    assert proposals.waiting(core, ws) == []
    made = proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    shown = _waiting(core, ws)
    assert shown["kind"] == "kit" and shown["label"] == "Kit for @writer"
    assert shown["card"] == made["card"] and shown["problems"] == []
    assert shown["payload"]["model"]["model"] == "claude-sonnet-4-5"
    assert shown["modelChoices"] is not None  # the owner may pick its model
    # Google Drive is mapped to Hermes's connector, like a hire's tool.
    assert shown["payload"]["kit"]["tools"][0]["connector"] == "google-drive"
    assert kanban_of(core, ws)[made["card"]]["title"] == "Kit for @writer"
    # Nothing of the member changed yet.
    assert hire_kit.kit_of(core, ws, "writer") is None


def test_approve_writes_the_kit_through_the_hire_path_and_undo_restores(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    home = core.engine.profile_home(agent_profiles.key(ws, "writer"))
    identity.write_memory(home, "memory", ["The owner likes short hooks."])
    before = team.get(core, ws, "writer")
    assert before is not None and before.skills == [] and not before.model
    made = proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    # The owner's edit that takes a part out is refused, like a hire's.
    r = client.post(url, json={"choice": "approve", "payload": {"kit": {**WHOLE_KIT, "docs": []}}})
    assert r.status_code == 400 and "kit.docs is empty" in r.text, r.text
    assert hire_kit.kit_of(core, ws, "writer") is None
    # His edit (Edit kit: another tool, the model picker) goes through.
    edit = {
        "kit": {**WHOLE_KIT, "tools": [{"name": "Notion", "key": "NOTION_TOKEN"}]},
        "model": {"model": "claude-haiku-4-5-20251001", "effort": "low"},
    }
    r = client.post(url, json={"choice": "approve", "payload": edit})
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["status"] == "approved" and shown["canUndo"] is True
    # Written into its Hermes profile the hire's way: the kit fact, the library
    # skill and the model through the team's save, its SOUL's 'Your team'.
    kit = hire_kit.kit_of(core, ws, "writer")
    assert kit is not None and [t["name"] for t in kit["tools"]] == ["Notion"]
    member = team.get(core, ws, "writer")
    assert member is not None and member.skills == ["writing"]
    assert member.model is not None and member.model["model"] == "claude-haiku-4-5-20251001"
    assert member.instructions == before.instructions  # its role stays
    soul = (home / "SOUL.md").read_text()
    assert rules.TEAM_START in soul
    # Its memory stays, plus one kit entry.
    entries = _memory(core, ws, "writer")
    assert "The owner likes short hooks." in entries
    assert sum(1 for e in entries if e.startswith(hire_kit.MEMORY_MARK)) == 1
    # Readiness runs now (a key the owner must add: not ready yet).
    view = client.get(f"/workspaces/{ws}/workers/writer/readiness").json()
    assert view is not None and view["state"] == "not_ready"
    assert _workers(client, ws)["writer"]["kit"] == "whole"
    # A revision of the member, by the owner, naming the card.
    from agos_core.db import agent_revisions as revisions

    found = revisions.list_revisions(core.db, ws, "writer")
    assert any("approved its kit" in str(r.why) for r in found)
    # The card is done on Hermes's board.
    assert kanban_of(core, ws)[made["card"]]["status"] == "done"
    # Undo: back to no kit, its model and skills as before; its memory kept.
    r = client.post(f"{url}/undo")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "undone"
    assert hire_kit.kit_of(core, ws, "writer") is None
    member = team.get(core, ws, "writer")
    assert member is not None and member.skills == [] and not member.model
    assert rules.TEAM_START not in (home / "SOUL.md").read_text()
    entries = _memory(core, ws, "writer")
    assert entries == ["The owner likes short hooks."]
    assert client.get(f"/workspaces/{ws}/workers/writer/readiness").json() is None
    assert hire_kit.held(core, ws, "writer") is False
    assert client.post(f"{url}/undo").status_code == 409


def test_undo_puts_back_an_earlier_incomplete_kit(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    old = {"skills": [{"name": "writing"}], "team": {"project": "Weekly reels"}}
    hire_kit.save_kit(core, ws, "writer", old)
    assert member_kits.state(core, ws, "writer") == "incomplete"
    made = proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    assert client.post(url, json={"choice": "approve"}).status_code == 200
    assert member_kits.state(core, ws, "writer") == "whole"
    assert client.post(f"{url}/undo").status_code == 200
    kit = hire_kit.kit_of(core, ws, "writer")
    assert kit is not None and kit["tools"] == [] and kit["team"]["project"] == "Weekly reels"


def test_reject_leaves_the_member_unchanged(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    home = core.engine.profile_home(agent_profiles.key(ws, "writer"))
    soul = (home / "SOUL.md").read_text()
    profile = (home / "profile.yaml").read_text() if (home / "profile.yaml").exists() else ""
    made = proposals.propose(core, ws, "kit", _kit_payload(), by_tool=True)
    r = client.post(
        f"/workspaces/{ws}/proposals/{made['ask_id']}",
        json={"choice": "reject", "note": "Not now."},
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected", r.text
    assert r.json()["canUndo"] is False
    assert hire_kit.kit_of(core, ws, "writer") is None
    assert (home / "SOUL.md").read_text() == soul
    assert ((home / "profile.yaml").read_text() if (home / "profile.yaml").exists() else "") == (
        profile
    )
    member = team.get(core, ws, "writer")
    assert member is not None and member.skills == [] and not member.model
    assert kanban_of(core, ws)[made["card"]]["status"] == "done"
    # Rejected: a new ask makes a new card.
    card, created = member_kits.ask(core, ws, "writer")
    assert created is True and card != made["card"]


# ---- the Co-Founder can do the same from a chat --------------------------------------------


def test_the_cofounder_suggests_kits_only_as_cards(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    agent(client, ws, "writer")
    agent(client, ws, "editor")
    assert parity.DO["suggestKit"] == "do:suggest_member_kit"
    assert parity.DO["suggestKits"] == "do:suggest_member_kit"
    assert parity.KINDS["suggest_member_kit"].gate == "once"
    assert "suggest_member_kit" in cofounder_more.DOES
    assert "suggest_member_kit" not in cofounder_more.UNDOES  # it writes nothing
    # One member: the same card the button makes (and the same again while open).
    said = cofounder_more.do(core, ws, "suggest_member_kit", {"member": "@writer"})
    assert "propose the kit there" in said["report"]
    again = cofounder_more.do(core, ws, "suggest_member_kit", {"member": "writer"})
    assert "already asked" in again["report"]
    # "all": one card for each member still without one.
    every = cofounder_more.do(core, ws, "suggest_member_kit", {"member": "all"})
    assert "@editor" in every["report"] and "@writer" not in every["report"]
    assert len(kanban_of(core, ws)) == 2
    # Its own kit: a proposal card the owner approves, never written on the spot.
    own = cofounder_more.do(
        core, ws, "suggest_member_kit", {**_kit_payload("editor"), "member": "editor"}
    )
    assert own["proposed"] is True
    assert hire_kit.kit_of(core, ws, "editor") is None
    assert _waiting(core, ws)["payload"]["member"] == "editor"
    # The Co-Founder's agos_propose knows the kind.
    from agos_core.hermes_plugin.agos_guard import asks

    enum = asks.PROPOSE_SCHEMA["parameters"]["properties"]["kind"]["enum"]  # type: ignore[index]
    assert "kit" in enum
    assert "kit" in proposal_rules.KINDS
