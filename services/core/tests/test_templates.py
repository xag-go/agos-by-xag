"""Step 56 templates: a workspace as a readable bundle (export, import with collision
strategies, inputs and a fidelity report), the ready-made teams catalog (install,
drift) and each member's revisions (append, diff, restore, the consent rule)."""

from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_automations import MODEL, env  # noqa: F401 - fixture
from test_tool_keys import FakeHermes

from agos_core.actions import agent_revisions, goals, portability, proposals, team, teams_catalog
from agos_core.engine import bundle as fmt
from agos_core.engine import config_file, hermes_redact

KEY = "pk-TEST-4d1c9e7a2b5f8c3e6a0d"
TG = "7012345678:AAH-fake-telegram-token-xyz"
PATTERN = "sk-ant-api03-FAKEFAKEFAKEFAKEFAKE"
SKILL_TEXT = (
    "---\nname: brief-writer\ndescription: Write a one-page brief.\n---\n\nWrite it short.\n"
)


def _hermes_masks(texts: list[str]) -> list[str]:
    """Hermes's redact_sensitive_text as far as these tests go (a secret-shaped
    token is masked); the real one runs in test_command_output_masked_by_hermes."""
    return [re.sub(r"sk-ant-[A-Za-z0-9_-]{10,}", "sk-ant...MASK", t) for t in texts]


@pytest.fixture
def ws_env(env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    client, core, cron, ws = env
    core.engine.tool_keys = FakeHermes()
    from agos_core.actions import hermes_channel

    monkeypatch.setattr(hermes_channel, "restart_gateway", lambda *a, **k: None)
    monkeypatch.setattr(hermes_redact, "mask_many", _hermes_masks)
    return client, core, cron, ws


def _agent(client: Any, ws: str, name: str, **definition: Any) -> int:
    body = {"name": name, "title": name.replace("-", " ").title(), "summary": f"does {name}"}
    r = client.post(
        f"/workspaces/{ws}/agents",
        json={**body, "definition": {"instructions": f"You are {name}.", **definition}},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _filled(client: Any, core: Any, ws: str) -> None:
    """A workspace with a small org chart, a skill, an automation, a Vision, a key."""
    _agent(client, ws, "content-lead", skills=["brief-writer"])
    _agent(client, ws, "script-writer", reports_to="content-lead")
    r = client.post(
        f"/workspaces/{ws}/skills",
        json={"name": "brief-writer", "definition": {"text": SKILL_TEXT}},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/workspaces/{ws}/automations",
        json={
            "name": "Weekly plan",
            "instructions": f"Plan the week. Use the key {KEY} and {PATTERN}.",
            "schedule": "0 9 * * 1",
            "model": MODEL,
            "on": True,
            "agent": "content-lead",
        },
    )
    assert r.status_code == 201, r.text
    goals.set_vision(core, ws, title="Grow the channel", why="Reach", strategy="Short videos")
    goal = goals.add_goal(core, ws, title="1k followers", owner="content-lead")
    goals.add_result(core, ws, goal, title="Followers", start=0, current=120, target=1000)
    goals.add_project(core, ws, goal, title="Reels series", owner="script-writer")
    r = client.post(f"/workspaces/{ws}/tool-keys", json={"app": "Acme", "key": KEY})
    assert r.status_code in (200, 201), r.text
    root = Path(core.engine.profile_home(ws))
    with (root / ".env").open("a") as handle:
        handle.write(f"\nTELEGRAM_BOT_TOKEN={TG}\n")


def _zip(client: Any, ws: str) -> bytes:
    r = client.get(f"/workspaces/{ws}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    return bytes(r.content)


def _files(data: bytes) -> dict[str, str]:
    return fmt.from_zip(data)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# ---- export -----------------------------------------------------------------------------


def test_export_is_a_readable_bundle_with_no_secret(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    _filled(client, core, ws)
    data = _zip(client, ws)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert all(n.startswith(f"{ws}/") for n in names)
    files = _files(data)
    for path in (
        "TEAM.md",
        "settings.yaml",
        "vision.md",
        "agents/content-lead/SOUL.md",
        "agents/content-lead/agent.yaml",
        "agents/script-writer/agent.yaml",
        "skills/brief-writer/SKILL.md",
        "automations/weekly-plan.yaml",
    ):
        assert path in files, path
    head, body = fmt.frontmatter(files["TEAM.md"])
    assert head["schema"] == fmt.SCHEMA and head["members"][0] == "content-lead"
    assert "**Script Writer** (@script-writer), reports to @content-lead" in body
    agent = yaml.safe_load(files["agents/script-writer/agent.yaml"])
    assert agent["reports_to"] == "content-lead" and agent["title"] == "Script Writer"
    assert files["agents/content-lead/SOUL.md"].strip() == "You are content-lead."
    # No secret: no key value, no Telegram token, no Hermes credential file, the
    # secret-shaped text masked by Hermes, the key a named input.
    every = "\n".join(files.values()) + "\n".join(files)
    root = Path(core.engine.profile_home(ws))
    env_values = [v for v in config_file.read_env(root).values() if len(v) >= 8]
    assert env_values and KEY in env_values
    for secret in (KEY, TG, PATTERN, *env_values):
        assert secret not in every, secret
    assert not any(p.rsplit("/", 1)[-1] in (".env", "auth.json", "config.yaml") for p in files)
    assert "${" in files["automations/weekly-plan.yaml"] and "sk-ant...MASK" in every
    settings = yaml.safe_load(files["settings.yaml"])
    inputs = {i["name"]: i for i in settings["env_requires"]}
    assert inputs and all(set(i) >= {"name", "description", "required"} for i in inputs.values())
    assert not any("TELEGRAM" in n for n in inputs)
    [key_input] = [i for i in inputs.values() if i["kind"] == "tool_key"]
    assert key_input["required"] is True and key_input["app"] == "Acme"


def test_export_fails_closed_when_hermes_cant_check_it(
    ws_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _core, _cron, ws = ws_env
    _agent(client, ws, "writer")
    monkeypatch.setattr(
        hermes_redact, "mask_many", lambda texts: [hermes_redact.HIDDEN if t else t for t in texts]
    )
    r = client.get(f"/workspaces/{ws}/export")
    assert r.status_code == 503 and "secrets" in r.text


def test_bundle_inputs_are_hermess_own_env_requires_entries(ws_env: Any) -> None:
    """The inputs parse with Hermes's own EnvRequirement (hermes_cli/profile_distribution.py,
    read from the installed source by AST: Hermes's code, not a copy)."""
    import ast

    source = Path.home() / ".hermes/hermes-agent/hermes_cli/profile_distribution.py"
    if not source.is_file():
        pytest.skip("no Hermes checkout")
    tree = ast.parse(source.read_text())
    keep: list[ast.stmt] = [
        n
        for n in tree.body
        if (isinstance(n, ast.ClassDef) and n.name in ("EnvRequirement", "DistributionError"))
        or (isinstance(n, ast.FunctionDef) and n.name == "_str")
    ]
    from dataclasses import dataclass

    space: dict[str, Any] = {"dataclass": dataclass, "Any": Any, "Optional": Any}
    exec(  # noqa: S102 - Hermes's own code
        compile(ast.Module(body=keep, type_ignores=[]), str(source), "exec"), space
    )
    client, core, _cron, ws = ws_env
    _filled(client, core, ws)
    settings = yaml.safe_load(_files(_zip(client, ws))["settings.yaml"])
    for entry in settings["env_requires"]:
        req = space["EnvRequirement"].from_dict(entry)
        assert req.name == entry["name"] and req.required == entry["required"]


# ---- round trip --------------------------------------------------------------------------


def _shape(client: Any, core: Any, ws: str) -> dict[str, Any]:
    from agos_core.actions import automations, workspace_skills

    top = goals.top(core, ws)
    assert top is not None
    return {
        "agents": sorted(
            (a.name, a.title, a.summary, a.instructions, a.reports_to, tuple(a.skills))
            for a in team.members(core, ws)
        ),
        "skills": sorted(workspace_skills.names(core, ws)),
        "automations": sorted(
            (a.name, a.schedule, a.agent, a.instructions.replace(KEY, "${KEY}"))
            for a in automations.list_all(core, ws)
        ),
        "vision": (top.title, top.why, top.strategy),
        "goals": [
            (
                g.title,
                g.owner,
                [(k.title, k.current, k.target) for k in g.results],
                [(p.title, p.owner) for p in g.children],
            )
            for g in top.children
        ],
    }


def test_round_trip_into_a_fresh_workspace_is_the_same_team(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    _filled(client, core, ws)
    data = _zip(client, ws)
    r = client.post("/import/preview", json={"data": _b64(data)})
    assert r.status_code == 200, r.text
    shown = r.json()
    assert [a["name"] for a in shown["agents"]] == ["content-lead", "script-writer"]
    assert not any(a["exists"] for a in shown["agents"]) and shown["vision"] is True
    assert shown["trust"] == "markdown_only"
    # The tool key is required: no value and not put off -> nothing is written.
    before = {w["id"] for w in client.get("/workspaces").json()}
    r = client.post("/import", json={"data": _b64(data), "name": "Copy", "defaultModel": MODEL})
    assert r.status_code == 400 and "Fill these in" in r.text
    assert {w["id"] for w in client.get("/workspaces").json()} == before
    key_name = next(i["name"] for i in shown["inputs"] if i["kind"] == "tool_key")
    r = client.post(
        "/import",
        json={
            "data": _b64(data),
            "name": "Copy",
            "defaultModel": MODEL,
            "inputs": {key_name: "pk-NEW-value-for-the-copy-1234"},
        },
    )
    assert r.status_code == 200, r.text
    report = r.json()
    new = report["workspaceId"]
    assert new != ws and not report["problems"], report
    results = {(i["kind"], i["name"]): i["result"] for i in report["items"]}
    assert results[("agent", "script-writer")] == "created"
    assert results[("key", key_name)] == "created"
    kinds = {n["kind"] for n in report["needsOwner"]}
    assert "telegram" in kinds and report["notCarried"]
    a, b = _shape(client, core, ws), _shape(client, core, new)
    assert a["agents"] == b["agents"] and a["skills"] == b["skills"]
    assert a["vision"] == b["vision"] and a["goals"] == b["goals"]
    assert [x[:3] for x in a["automations"]] == [x[:3] for x in b["automations"]]
    # The copy's own key, in its own root; the first workspace's key never went over.
    copy_env = config_file.read_env(Path(core.engine.profile_home(new)))
    assert "pk-NEW-value-for-the-copy-1234" in copy_env.values() and KEY not in copy_env.values()
    # Its members' writes are revisions by the import.
    [rev] = agent_revisions.list_for(core, new, "script-writer")
    assert rev.who == "import" and rev.summary == "first version"


def test_collisions_skip_rename_replace(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    _filled(client, core, ws)
    data = _b64(_zip(client, ws))
    later = {"later": ["TOOLS_ACME_API_KEY", "ACME_API_KEY"]}
    r = client.post("/import/preview", json={"data": data, "workspaceId": ws})
    assert all(a["exists"] for a in r.json()["agents"]) and r.json()["visionExists"]
    later = {"later": [i["name"] for i in r.json()["inputs"]]}
    # skip: nothing changes.
    before = _shape(client, core, ws)
    r = client.post(
        "/import",
        json={
            "data": data,
            "workspaceId": ws,
            "strategies": {"agents": "skip", "skills": "skip", "automations": "skip"},
            **later,
        },
    )
    assert r.status_code == 200, r.text
    assert {i["result"] for i in r.json()["items"] if i["kind"] != "key"} == {"skipped"}
    assert _shape(client, core, ws) == before
    # rename: a second copy beside the first, its lead the renamed lead.
    r = client.post(
        "/import",
        json={
            "data": data,
            "workspaceId": ws,
            "strategies": {"agents": "rename", "skills": "rename", "automations": "rename"},
            **later,
        },
    )
    assert r.status_code == 200, r.text
    renamed = {i["name"]: i["asName"] for i in r.json()["items"] if i["result"] == "renamed"}
    assert (
        renamed["content-lead"] == "content-lead-2" and renamed["brief-writer"] == "brief-writer-2"
    )
    assert renamed["Weekly plan"] == "Weekly plan (2)"
    copy = team.get(core, ws, "script-writer-2")
    assert copy is not None and copy.reports_to == "content-lead-2"
    assert copy.skills == [] and team.get(core, ws, "content-lead-2").skills == ["brief-writer-2"]  # type: ignore[union-attr]
    # replace: the member is written again from the bundle (the owner's edit goes).
    lead = team.get(core, ws, "content-lead")
    assert lead is not None
    r = client.put(
        f"/workspaces/{ws}/agents/{lead.id}",
        json={"name": "content-lead", "title": "Changed", "definition": {"instructions": "New."}},
    )
    assert r.status_code == 204, r.text
    r = client.post(
        "/import",
        json={"data": data, "workspaceId": ws, "strategies": {"agents": "replace"}, **later},
    )
    assert r.status_code == 200, r.text
    lead = team.get(core, ws, "content-lead")
    assert (
        lead is not None
        and lead.title == "Content Lead"
        and lead.instructions == "You are content-lead."
    )
    assert lead.id == team.get(core, ws, "content-lead").id  # type: ignore[union-attr]
    assert len([a for a in team.members(core, ws) if a.name.startswith("content-lead")]) == 2


def test_a_bad_bundle_is_refused_before_anything_is_written(ws_env: Any) -> None:
    client, _core, _cron, _ws = ws_env
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("../evil/TEAM.md", "---\nschema: agos/bundle-v1\n---\n")
    r = client.post("/import/preview", json={"data": _b64(out.getvalue())})
    assert r.status_code == 400 and "unsafe" in r.text
    r = client.post("/import/preview", json={"data": _b64(b"not a zip")})
    assert r.status_code == 400
    with pytest.raises(fmt.BundleError):
        fmt.parse({"TEAM.md": "---\nschema: other/v9\n---\n"})


# ---- the teams catalog ----------------------------------------------------------------------


def test_the_catalog_ships_five_teams_that_parse() -> None:
    teams = {t["slug"]: t for t in teams_catalog.teams()}
    assert set(teams) == {
        "content-machine",
        "product-engineering",
        "research-writing",
        "sales-outreach",
        "personal-assistant",
    }
    cm = teams["content-machine"]
    assert cm["lead"] == "content-lead" and len(cm["agents"]) == 5
    assert all(a["reportsTo"] == "content-lead" for a in cm["agents"][1:])
    for slug in teams:
        found = fmt.parse(teams_catalog.team_files(slug))
        assert found.agents and found.skills and found.automations, slug
        assert all(not a.get("on") for a in found.automations)  # installed off


def test_new_workspace_from_a_template_and_drift(ws_env: Any) -> None:
    client, core, _cron, _ws = ws_env
    r = client.post(
        "/templates/content-machine/install",
        json={"name": "Reels", "defaultModel": MODEL, "later": []},
    )
    assert r.status_code == 200, r.text
    new = r.json()["workspaceId"]
    lead = team.get(core, new, "content-lead")
    writer = team.get(core, new, "script-writer")
    assert not r.json()["problems"], r.json()
    assert lead is not None and lead.reports_to == ""
    assert sorted(lead.skills) == ["brand-voice", "content-calendar"]
    assert writer is not None and writer.reports_to == "content-lead"
    assert any(
        n["kind"] == "key" and n["name"] == "OPENROUTER_API_KEY" for n in r.json()["needsOwner"]
    )
    [installed] = client.get(f"/workspaces/{new}/templates").json()
    assert installed["slug"] == "content-machine" and installed["drift"] == []
    assert installed["templateChanged"] is False
    # The owner changes a member, removes one, adds one under the lead: drift says so.
    r = client.put(
        f"/workspaces/{new}/agents/{writer.id}",
        json={
            "name": "script-writer",
            "title": "Script Writer",
            "summary": writer.summary,
            "definition": {**writer.definition, "instructions": "Write longer scripts."},
        },
    )
    assert r.status_code == 204, r.text
    editor = team.get(core, new, "video-editor")
    assert editor is not None
    assert client.delete(f"/workspaces/{new}/agents/{editor.id}").status_code == 204
    _agent(client, new, "thumbnail-artist", reports_to="content-lead")
    [installed] = client.get(f"/workspaces/{new}/templates").json()
    drift = {(d["name"], d["change"]): d["fields"] for d in installed["drift"]}
    assert drift[("script-writer", "changed")] == ["instructions"]
    assert ("video-editor", "removed") in drift and ("thumbnail-artist", "added") in drift


def test_add_team_under_a_lead_of_the_current_workspace(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    _agent(client, ws, "head-of-growth")
    _agent(client, ws, "researcher")  # the template has a researcher too
    r = client.post(
        "/templates/content-machine/install",
        json={"workspaceId": ws, "under": "head-of-growth", "later": []},
    )
    assert r.status_code == 200, r.text
    lead = team.get(core, ws, "content-lead")
    assert lead is not None and lead.reports_to == "head-of-growth"
    renamed = team.get(core, ws, "researcher-2")
    assert renamed is not None and renamed.reports_to == "content-lead"
    original = team.get(core, ws, "researcher")
    assert original is not None and original.reports_to == ""  # untouched
    from agos_core.actions import automations

    scan = {a.name: a for a in automations.list_all(core, ws)}
    assert scan["Trend scan"].agent == "researcher-2" and scan["Trend scan"].on is False
    [installed] = client.get(f"/workspaces/{ws}/templates").json()
    assert installed["drift"] == []
    r = client.post(
        "/templates/content-machine/install", json={"workspaceId": ws, "under": "nobody"}
    )
    assert r.status_code == 404


# ---- revisions ---------------------------------------------------------------------------------


def test_revisions_append_diff_and_restore(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    item = _agent(client, ws, "writer")
    _agent(client, ws, "lead")
    base = f"/workspaces/{ws}/agents/{item}"
    revs = client.get(f"{base}/revisions").json()
    assert [r["n"] for r in revs] == [1] and revs[0]["who"] == "owner"
    body = {"name": "writer", "title": "Writer", "summary": "does writer"}
    r = client.put(
        base, json={**body, "definition": {"instructions": "You are writer.\nBe brief."}}
    )
    assert r.status_code == 204
    r = client.put(f"{base}/reports-to", json={"reportsTo": "lead"})
    assert r.status_code == 204
    # The same save again is not a revision.
    writer = team.get(core, ws, "writer")
    assert writer is not None
    r = client.put(base, json={**body, "definition": writer.definition})
    assert r.status_code == 204
    revs = client.get(f"{base}/revisions").json()
    assert [r["n"] for r in revs] == [3, 2, 1]
    [text] = revs[1]["changes"]
    assert text["field"] == "instructions" and "+Be brief." in text["lines"]
    assert (
        revs[0]["changes"][0]["field"] == "reports_to" and revs[0]["changes"][0]["after"] == "@lead"
    )
    # Restore v1 = a new revision v4, through the team's own write.
    r = client.post(f"{base}/revisions/1/restore")
    assert r.status_code == 200 and r.json()["n"] == 4, r.text
    writer = team.get(core, ws, "writer")
    assert (
        writer is not None and writer.instructions == "You are writer." and writer.reports_to == ""
    )
    revs = client.get(f"{base}/revisions").json()
    assert revs[0]["summary"] == "restored from v1" and revs[0]["restoredFrom"] == 1
    assert client.post(f"{base}/revisions/99/restore").status_code == 404
    # A change made outside AGOS (Hermes's SOUL.md written by the agent after an
    # approved proposal) shows up as a revision by hermes.
    home = team.home(core, ws, "writer")
    assert home is not None
    soul = (home / "SOUL.md").read_text()
    (home / "SOUL.md").write_text(soul.replace("You are writer.", "You are writer. Outside."))
    revs = client.get(f"{base}/revisions").json()
    assert revs[0]["who"] == agent_revisions.OUTSIDE and revs[0]["n"] == 5


def test_a_member_restoring_itself_goes_through_the_consent_gate(ws_env: Any) -> None:
    client, core, _cron, ws = ws_env
    item = _agent(client, ws, "writer")
    body = {"name": "writer", "title": "Writer", "summary": "does writer"}
    r = client.put(
        f"/workspaces/{ws}/agents/{item}", json={**body, "definition": {"instructions": "Changed."}}
    )
    assert r.status_code == 204
    done = agent_revisions.restore(core, ws, "writer", 1, who="writer")
    assert done["proposed"] is True
    writer = team.get(core, ws, "writer")
    assert writer is not None and writer.instructions == "Changed."  # nothing written
    [shown] = proposals.waiting(core, ws)
    assert shown["kind"] == "instructions" and shown["member"] == "writer"
    assert shown["payload"]["target"] == "SOUL.md" and len(shown["payload"]["sha256"]) == 64
    assert "+You are writer." in shown["payload"]["diff"]
    assert [r.n for r in agent_revisions.list_for(core, ws, "writer")] == [2, 1]


def test_cofounder_and_import_writes_say_who(ws_env: Any) -> None:
    _client, core, _cron, ws = ws_env
    with agent_revisions.by("cofounder", "a card"):
        team.save(
            core,
            ws,
            "helper",
            title="Helper",
            summary="",
            definition={"instructions": "Help."},
            new=True,
        )
    [rev] = agent_revisions.list_for(core, ws, "helper")
    assert (rev.who, rev.why) == ("cofounder", "a card")
    assert portability.trust({"skills/x/scripts/run.sh": "echo"}) == "scripts"
