"""Step 62: a hire's kit (tools, skills, docs, team context, onboarding test), edited
before Approve; on approve AGOS provisions what it can (library skills through the
team's own code, files copied into the member's folder, ONE 'Your team' section in its
SOUL.md, a memory entry); the Readiness checklist is derived from real checks (fakes
here for connectors and keys); what is missing goes on ONE Co-Founder card; the
onboarding test is graded (a fake grader) with a fix-and-retry loop and the owner's
Start anyway / Not needed / Skip test choices."""

from __future__ import annotations

from typing import Any

import pytest
from work_env import (  # noqa: F401  (fixtures)
    WHOLE_MODEL,
    Env,
    agent,
    create_ws,
    env,
    fake_board,
    fake_models,
    kanban_of,
)

from agos_core.actions import agent_profiles, hire_kit, proposals, team
from agos_core.actions.services.hire import kit_rules as hire_kit_rules
from agos_core.actions.services.hire import onboarding as hire_onboarding
from agos_core.actions.services.hire import readiness as hire_readiness
from agos_core.actions.services.proposals import hire_checks as proposal_checks
from agos_core.engine import hire_kit as rules
from agos_core.engine import identity
from agos_core.storage.layout import workspace_paths

KIT: dict[str, Any] = {
    "tools": [
        {"name": "Instagram", "why": "posts the reels"},
        {"name": "Meta Ads", "key": "meta_ads_token"},
        {"name": "CapCut", "why": "edits the clips"},
    ],
    "skills": [
        {"name": "writing", "source": "library"},
        {"name": "video-editing", "source": "find"},
    ],
    "docs": [
        {"title": "Style guide", "path": "brand/style.md"},
        {"title": "A good reel", "path": "brand/good-reel.md", "kind": "example"},
        {"title": "Brand book", "url": "https://example.com/brand"},
    ],
    "team": {"works_with": ["writer", "@Ghost name"], "project": "Weekly reels"},
    "onboarding": {
        "task": "Edit this 30 s clip in our style.",
        "criteria": ["cuts on the beat", "our captions font"],
    },
}
HIRE: dict[str, Any] = {
    "name": "video-editor",
    "title": "Video Editor",
    "role": "Edits the reels from the scripts. Hands them to the writer for captions.",
    "why": "Reels for the weekly goal wait days; nobody on the team edits video.",
    "reports_to": "",
    **WHOLE_MODEL,  # every hire names its model (checked against Hermes's catalog)
}


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[str]]:
    """What Hermes has, as the checks read it: library skills, connectors on, keys."""
    have: dict[str, set[str]] = {"skills": {"writing"}, "apps": set(), "keys": set()}
    fake_models(monkeypatch)
    # hire_kit looks it up in the facade, the hire checks in their own module.
    for mod in (proposals, proposal_checks):
        monkeypatch.setattr(mod, "_skill_here", lambda core, ws, name: name in have["skills"])
    monkeypatch.setattr(hire_kit_rules, "_catalog", lambda core: {"instagram": "Instagram"})
    monkeypatch.setattr(hire_readiness, "_connected", lambda core, ws: set(have["apps"]))
    monkeypatch.setattr(hire_readiness, "_keys", lambda core, ws: set(have["keys"]))
    return have


def _files(core: Any, ws: str) -> Any:
    return workspace_paths(core.layout, ws).files


def _approve(client: Any, core: Any, ws: str, payload: dict[str, Any], **body: Any) -> Any:
    made = proposals.propose(core, ws, "hire", payload)
    r = client.post(
        f"/workspaces/{ws}/proposals/{made['ask_id']}", json={"choice": "approve", **body}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _hired(client: Any, core: Any, ws: str, kit: dict[str, Any] | None = None) -> dict[str, Any]:
    agent(client, ws, "writer")
    folder = _files(core, ws) / "brand"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "style.md").write_text("Short cuts. Yellow captions.")
    shown: dict[str, Any] = _approve(
        client, core, ws, {**HIRE, "kit": kit if kit is not None else KIT}
    )
    return shown


def _view(client: Any, ws: str, member: str = "video-editor") -> dict[str, Any]:
    r = client.get(f"/workspaces/{ws}/workers/{member}/readiness")
    assert r.status_code == 200, r.text
    found: dict[str, Any] = r.json()
    return found


def _item(view: dict[str, Any], id_: str) -> dict[str, Any]:
    return next(i for i in view["items"] if i["id"] == id_)


def _soul(core: Any, ws: str, member: str = "video-editor") -> str:
    text: str = (core.engine.profile_home(agent_profiles.key(ws, member)) / "SOUL.md").read_text()
    return text


# ---- the kit's shape ------------------------------------------------------------------


def test_the_kit_is_cleaned_and_checked() -> None:
    kit = rules.clean_kit(
        {
            "tools": [
                "Instagram",
                {"name": "instagram"},
                {"name": ""},
                {"name": "X", "key": "x-1"},
            ],
            "skills": ["Video-Editing", {"name": "hooks", "source": "nope"}],
            "docs": ["https://e.com/a", "brand/a.md", {"path": "../secret", "title": "S"}],
            "team": {"works_with": ["@Writer", "bad name"], "project": " the  reels "},
            "onboarding": {"task": "Do it", "criteria": []},
            "extra": 1,
        }
    )
    assert [t["name"] for t in kit["tools"]] == ["Instagram", "X"]  # deduped by name
    assert kit["tools"][1]["key"] == ""  # not an env name
    assert kit["skills"] == [
        {"name": "video-editing", "source": "library", "why": ""},
        {"name": "hooks", "source": "library", "why": ""},
    ]
    assert [d.get("url") or d["path"] for d in kit["docs"]] == [
        "https://e.com/a",
        "brand/a.md",
        "../secret",
    ]
    assert kit["team"] == {"works_with": ["writer"], "project": "the reels"}
    problems = rules.kit_problems(kit)
    assert any("../secret" in p for p in problems)
    assert any("criteria" in p for p in problems)
    assert rules.is_empty(rules.clean_kit({})) and not rules.is_empty(kit)
    routes = rules.parse_routes(
        'Done.\n```agos-kit-routes\n[{"item": "`tool:capcut`", "path": "alternative", '
        '"text": "Use DaVinci with its API"}, {"bad": 1}]\n```'
    )
    assert routes == {"tool:capcut": {"path": "alternative", "text": "Use DaVinci with its API"}}
    assert rules.parse_routes("no block") == {}


def test_a_hire_proposal_carries_its_kit_mapped_to_connectors(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    _client, _fake, core, ws = env
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT})
    [shown] = proposals.waiting(core, ws)
    assert shown["id"] == made["ask_id"]
    kit = shown["payload"]["kit"]
    tools = {t["name"]: t for t in kit["tools"]}
    assert tools["Instagram"]["connector"] == "instagram"  # Hermes's catalog
    assert tools["Meta Ads"] == {**tools["Meta Ads"], "connector": "", "key": "META_ADS_TOKEN"}
    assert tools["CapCut"]["connector"] == "" and tools["CapCut"]["key"] == ""
    skills = {s["name"]: s["source"] for s in kit["skills"]}
    assert skills == {"writing": "library", "video-editing": "find"}
    # A doc path that leaves the workspace's files is refused at the door.
    with pytest.raises(Exception, match="no \\.\\."):
        proposals.propose(
            core, ws, "hire", {**HIRE, "name": "other", "kit": {"docs": [{"path": "../x"}]}}
        )


def test_the_owner_edits_the_kit_before_approve(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    made = proposals.propose(core, ws, "hire", {**HIRE, "kit": KIT})
    url = f"/workspaces/{ws}/proposals/{made['ask_id']}"
    # Only the kit is edited before approving; the rest goes back with a revise.
    bad = client.post(url, json={"choice": "approve", "payload": {"role": "x"}})
    assert bad.status_code == 400 and "kit" in bad.text
    # His edit took the onboarding test out: refused on the card, nothing is made.
    edited = {
        **KIT,
        "tools": KIT["tools"][:2],
        "docs": [{"title": "Notes", "url": "https://example.com/notes"}],
        "onboarding": {},
    }
    r = client.post(url, json={"choice": "approve", "payload": {"kit": edited}})
    assert r.status_code == 400
    assert "kit.onboarding.task is missing" in r.text and "Put it back" in r.text
    assert team.get(core, ws, "video-editor") is None
    assert [p["status"] for p in proposals.waiting(core, ws)] == ["waiting"]
    # The same with every other part taken out.
    for part in ("tools", "docs"):
        r = client.post(url, json={"choice": "approve", "payload": {"kit": {**KIT, part: []}}})
        assert r.status_code == 400 and f"kit.{part} is empty" in r.text
    no_skill = {**KIT, "skills": [{"name": "video-editing", "source": "find"}]}
    r = client.post(url, json={"choice": "approve", "payload": {"kit": no_skill}})
    assert r.status_code == 400 and "at least one skill" in r.text
    # His edit: CapCut out, a doc of his own in, the test kept.
    edited = {**edited, "onboarding": KIT["onboarding"]}
    r = client.post(url, json={"choice": "approve", "payload": {"kit": edited}})
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["status"] == "approved"
    assert [t["name"] for t in shown["editedPayload"]["kit"]["tools"]] == ["Instagram", "Meta Ads"]
    assert [t["name"] for t in shown["payload"]["kit"]["tools"]] == [
        "Instagram",
        "Meta Ads",
        "CapCut",
    ]
    # The member got the edited kit.
    kit = hire_kit.kit_of(core, ws, "video-editor")
    assert kit is not None and [t["name"] for t in kit["tools"]] == ["Instagram", "Meta Ads"]
    assert kit["onboarding"]["task"] == KIT["onboarding"]["task"]


# ---- provisioning ----------------------------------------------------------------------


def test_approve_provisions_skills_docs_soul_and_memory(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    shown = _hired(client, core, ws)
    assert shown["status"] == "approved"
    member = team.get(core, ws, "video-editor")
    assert member is not None
    # The library skill went in through the team's own code (skills.auto_load).
    assert member.skills == ["writing"]
    # The workspace's file was copied into the member's folder; the missing one wasn't.
    files = _files(core, ws)
    assert (files / "team/video-editor/docs/style.md").read_text() == "Short cuts. Yellow captions."
    assert not (files / "team/video-editor/examples/good-reel.md").exists()
    # ONE 'Your team' section: its lead, who it works with, the project, its files.
    soul = _soul(core, ws)
    assert soul.count(rules.TEAM_START) == 1 and soul.count(rules.TEAM_END) == 1
    section = soul.split(rules.TEAM_START, 1)[1].split(rules.TEAM_END, 1)[0]
    assert "Your lead: the Co-Founder." in section
    assert "@writer (Writer)" in section and "ghost" not in section.lower()
    assert "Weekly reels" in section and "/workspace/team/video-editor/" in section
    assert "Brand book (https://example.com/brand)" in section
    # Its role is still read back as written (the section sits outside the role block).
    assert member.instructions.startswith("Edits the reels")
    # Rewritten again (a project rename, a sync): still one copy.
    agent_profiles.write_texts(core, ws)
    assert _soul(core, ws).count(rules.TEAM_START) == 1
    # One memory entry, kept to one on a second provision.
    home = core.engine.profile_home(agent_profiles.key(ws, "video-editor"))
    kit = hire_kit.kit_of(core, ws, "video-editor")
    assert kit is not None
    hire_kit.provision(core, ws, "video-editor", kit, fresh=False)
    entries = identity.read_memory(home, "memory").entries
    assert sum(1 for e in entries if e.startswith(hire_kit.MEMORY_MARK)) == 1
    # Members hired without a kit get no section and are never held.
    assert rules.TEAM_START not in _soul(core, ws, "writer")
    assert client.get(f"/workspaces/{ws}/workers/writer/readiness").json() is None


# ---- readiness, item by item ---------------------------------------------------------


def test_readiness_is_derived_from_real_checks(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    _hired(client, core, ws)
    view = _view(client, ws)
    assert view["state"] == "not_ready"
    assert _item(view, "model")["ok"] is True
    assert _item(view, "team")["ok"] is True
    assert _item(view, "skill:writing")["ok"] is True
    skill = _item(view, "skill:video-editing")
    assert skill["state"] == "missing" and skill["action"] == "find_skill" and not skill["owner"]
    insta = _item(view, "tool:instagram")
    assert (
        insta["action"] == "connect"
        and insta["owner"]
        and insta["href"].endswith("/settings/connectors")
    )
    key = _item(view, "tool:meta ads")
    assert key["action"] == "add_key" and "META_ADS_TOKEN" in key["how"]
    assert _item(view, "tool:capcut")["action"] == "alternative"
    assert _item(view, "doc:brand/style.md")["ok"] is True
    missing_doc = _item(view, "doc:brand/good-reel.md")
    assert missing_doc["action"] == "answer" and missing_doc["owner"]
    assert _item(view, "doc:https://example.com/brand")["ok"] is True
    # Each one turns ready from the real thing, not a flag.
    fakes["apps"].add("instagram")
    fakes["keys"].add("META_ADS_TOKEN")
    fakes["skills"].add("video-editing")
    (_files(core, ws) / "brand/good-reel.md").write_text("cut, cut, caption")
    after = client.post(f"/workspaces/{ws}/workers/video-editor/readiness").json()
    assert _item(after, "tool:instagram")["ok"] and _item(after, "tool:meta ads")["ok"]
    # In the library now: AGOS gave it to the member through the team's code.
    assert _item(after, "skill:video-editing")["ok"]
    member = team.get(core, ws, "video-editor")
    assert member is not None and "video-editing" in member.skills
    # The file the owner gave: copied in.
    assert _item(after, "doc:brand/good-reel.md")["ok"]
    assert (_files(core, ws) / "team/video-editor/examples/good-reel.md").is_file()
    # CapCut has no connector or API: only the owner's Not needed (with his reason) closes it.
    assert after["state"] == "not_ready"
    r = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice",
        json={"item": "tool:capcut", "choice": "not_needed", "reason": "I edit in Premiere"},
    )
    closed = r.json()
    assert _item(closed, "tool:capcut")["state"] == "not_needed"
    assert _item(closed, "tool:capcut")["reason"] == "I edit in Premiere"
    assert closed["state"] == "onboarding"
    # Undo of his choice: missing again.
    undone = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice",
        json={"item": "tool:capcut", "choice": "clear"},
    ).json()
    assert undone["state"] == "not_ready"
    bad = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice",
        json={"item": "nope", "choice": "not_needed"},
    )
    assert bad.status_code == 400


def test_one_cofounder_card_for_what_is_missing_and_its_routes(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    _hired(client, core, ws)
    cards = [
        c
        for c in kanban_of(core, ws).values()
        if str(c.get("key") or "").startswith(hire_kit.READY_KEY)
    ]
    assert len(cards) == 1
    card = cards[0]
    assert card["assignee"] == core.engine.hermes_name(ws)
    assert card["title"] == "Make @video-editor ready"
    body = str(card["body"])
    for words in (
        "`skill:video-editing`",
        "`tool:instagram`",
        "`tool:capcut`",
        "agos_ask_owner",
        "hermes skills search",
        rules.ROUTES_FENCE,
    ):
        assert words in body, words
    assert "`skill:writing`" not in body  # ready already
    # Looked at again with nothing changed: the same card.
    hire_kit.advance(core, ws, "video-editor")
    hire_kit.sweep(core, ws)
    assert (
        len(
            [
                c
                for c in kanban_of(core, ws).values()
                if str(c.get("key") or "").startswith(hire_kit.READY_KEY)
            ]
        )
        == 1
    )
    assert _view(client, ws)["gapCard"] == card["id"]
    # The Co-Founder's routes come back from its card's result.
    card["status"] = "done"
    card["result"] = (
        "Done.\n```agos-kit-routes\n"
        '[{"item": "tool:capcut", "path": "alternative", "text": "Use DaVinci Resolve (API)"}]\n```'
    )
    fakes["apps"].add("instagram")  # something changed: a new missing set, a new card
    view = client.post(f"/workspaces/{ws}/workers/video-editor/readiness").json()
    assert _item(view, "tool:capcut")["route"] == {
        "path": "alternative",
        "text": "Use DaVinci Resolve (API)",
    }
    assert (
        len(
            [
                c
                for c in kanban_of(core, ws).values()
                if str(c.get("key") or "").startswith(hire_kit.READY_KEY)
            ]
        )
        == 2
    )


def test_a_member_not_ready_gets_no_work(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    _hired(client, core, ws)
    editor = core.engine.hermes_name(agent_profiles.key(ws, "video-editor"))
    writer = core.engine.hermes_name(agent_profiles.key(ws, "writer"))
    listed = agent_profiles.dispatch_list(core, ws)
    assert editor not in listed and writer in listed
    # The team view says so (the Hierarchy chip), and so does the Co-Founder's roster.
    workers = client.get(f"/workspaces/{ws}/workers").json()
    states = {m["name"]: m["readiness"] for m in workers["members"]}
    assert states == {"video-editor": "not_ready", "writer": None}
    from agos_core.actions import cofounder_actions

    assert "NOT READY" in cofounder_actions.instructions(core, ws)
    # Its heartbeat can't go on yet.
    from agos_core.actions import heartbeat
    from agos_core.actions.errors import ActionError

    with pytest.raises(ActionError, match="isn't ready for work"):
        heartbeat.set_heartbeat(core, ws, "video-editor", on=True, interval="1h")
    # Start anyway: on the dispatcher's list again.
    started = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice", json={"choice": "start_anyway"}
    ).json()
    assert started["state"] == "ready" and started["startedAnyway"] is True
    assert editor in agent_profiles.dispatch_list(core, ws)


# ---- the onboarding test ---------------------------------------------------------------


def _ready_but_test(client: Any, core: Any, ws: str, fakes: dict[str, set[str]]) -> dict[str, Any]:
    kit = {**KIT, "tools": KIT["tools"][:1], "skills": KIT["skills"][:1], "docs": KIT["docs"][:1]}
    fakes["apps"].add("instagram")
    _hired(client, core, ws, kit)
    view = _view(client, ws)
    assert view["state"] == "onboarding", view
    return view


def _tries(core: Any, ws: str) -> list[dict[str, Any]]:
    return sorted(
        (
            c
            for c in kanban_of(core, ws).values()
            if str(c.get("key") or "").startswith(hire_kit.ONBOARD_KEY)
        ),
        key=lambda c: str(c["key"]),
    )


def test_onboarding_test_passes_and_the_member_is_ready(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    _ready_but_test(client, core, ws, fakes)
    [first] = _tries(core, ws)
    assert first["key"] == f"{hire_kit.ONBOARD_KEY}video-editor:1"
    assert first["assignee"] == core.engine.hermes_name(agent_profiles.key(ws, "video-editor"))
    assert "Edit this 30 s clip in our style." in str(first["body"])
    assert "- cuts on the beat" in str(first["body"])
    # Onboarding: the dispatcher starts its card (its test), the Co-Founder gives no work.
    editor = core.engine.hermes_name(agent_profiles.key(ws, "video-editor"))
    assert editor in agent_profiles.dispatch_list(core, ws)
    graded: list[dict[str, str]] = []

    def grade(core: Any, ws: str, job: dict[str, str]) -> tuple[bool | None, str]:
        graded.append(job)
        return True, "On the beat, right font."

    monkeypatch.setattr(hire_onboarding, "_grade", grade)
    hire_kit.sweep(core, ws)
    assert graded == []  # still running: nothing to grade
    first["status"], first["result"] = "done", "clip.mp4: 30 s, cuts on beats, yellow captions"
    hire_kit.sweep(core, ws)
    assert (
        graded[0]["output"].startswith("clip.mp4")
        and "- our captions font" in graded[0]["checklist"]
    )
    view = _view(client, ws)
    assert view["state"] == "ready"
    assert view["onboarding"]["passed"] is True
    assert view["onboarding"]["tries"][0]["grade"] == "passed"
    hire_kit.sweep(core, ws)
    assert len(graded) == 1  # graded once


def test_onboarding_test_fails_gets_fixed_retried_then_escalates(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _fake, core, ws = env
    _ready_but_test(client, core, ws, fakes)
    monkeypatch.setattr(
        hire_onboarding, "_grade", lambda core, ws, job: (False, "Captions in the wrong font.")
    )
    for n in range(1, rules.MAX_TRIES + 1):
        tries = _tries(core, ws)
        assert len(tries) == n
        tries[-1]["status"], tries[-1]["result"] = "done", f"try {n}"
        hire_kit.advance(core, ws, "video-editor")
        fixes = [
            c
            for c in kanban_of(core, ws).values()
            if str(c.get("key") or "").startswith(hire_kit.FIX_KEY)
        ]
        if n < rules.MAX_TRIES:
            # The Co-Founder's fix card, and the next try waiting on it.
            assert len(fixes) == n
            fix = fixes[-1]
            assert fix["assignee"] == core.engine.hermes_name(ws)
            assert "Captions in the wrong font." in str(fix["body"])
            nxt = _tries(core, ws)[-1]
            assert nxt["parents"] == [fix["id"]]
            fix["status"] = "done"
            nxt["status"] = "ready"
    view = _view(client, ws)
    assert view["state"] == "onboarding" and view["onboarding"]["escalated"] is True
    assert len(_tries(core, ws)) == rules.MAX_TRIES  # no more tries by itself
    # The owner is asked in his Inbox.
    inbox = client.get(f"/workspaces/{ws}/inbox").json()["items"]
    [item] = [i for i in inbox if i["type"] == "readiness"]
    assert "failed 3 times" in item["title"] and item["readiness"]["member"] == "video-editor"
    # Retry: one more try; Skip test: ready.
    retried = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice", json={"choice": "retry"}
    ).json()
    assert retried["onboarding"]["escalated"] is False and len(_tries(core, ws)) == 4
    busy = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice", json={"choice": "retry"}
    )
    assert busy.status_code == 409
    skipped = client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice", json={"choice": "skip_test"}
    ).json()
    assert skipped["state"] == "ready" and skipped["onboarding"]["skipped"] is True


def test_a_member_without_a_test_is_ready_once_its_kit_is_there(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    # Every hire comes with its test now; a member's kit without one is the owner's
    # own (Readiness → kit), e.g. on a member made before kits.
    agent(client, ws, "writer")
    agent(client, ws, "video-editor")
    r = client.put(
        f"/workspaces/{ws}/workers/video-editor/kit",
        json={"kit": {"skills": ["writing"], "team": {"project": "Reels"}}},
    )
    assert r.status_code == 200, r.text
    assert _view(client, ws)["state"] == "ready"
    assert _tries(core, ws) == []
    # The owner's own kit for a member hired without one (his own hire).
    r = client.put(
        f"/workspaces/{ws}/workers/writer/kit",
        json={
            "kit": {
                "tools": [{"name": "Instagram"}],
                "onboarding": {"task": "t", "criteria": ["c"]},
            }
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "not_ready"
    assert _item(r.json(), "tool:instagram")["action"] == "connect"
    assert rules.TEAM_START in _soul(core, ws, "writer")
    inbox = client.get(f"/workspaces/{ws}/inbox").json()["items"]
    [item] = [i for i in inbox if i["type"] == "readiness"]
    assert item["title"] == "@writer isn't ready yet: 1 thing need you"


def test_kits_and_choices_stay_in_their_workspace(
    env: Env,  # noqa: F811
    fake_board: None,  # noqa: F811
    fakes: dict[str, set[str]],
) -> None:
    client, _fake, core, ws = env
    _hired(client, core, ws)
    other = create_ws(client, "Other")
    assert client.get(f"/workspaces/{other}/workers/video-editor/readiness").json() is None
    r = client.post(
        f"/workspaces/{other}/workers/video-editor/readiness/choice",
        json={"choice": "start_anyway"},
    )
    assert r.status_code == 404
    assert client.get("/workspaces/nope/workers/video-editor/readiness").status_code == 404
    assert [
        i
        for i in client.get(f"/workspaces/{other}/inbox").json()["items"]
        if i["type"] == "readiness"
    ] == []
    client.post(
        f"/workspaces/{ws}/workers/video-editor/readiness/choice", json={"choice": "start_anyway"}
    )
    rows = core.db.execute("SELECT workspace_id FROM member_readiness").fetchall()
    assert {str(r["workspace_id"]) for r in rows} == {ws}
