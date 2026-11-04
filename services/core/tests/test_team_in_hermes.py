"""The team is its Hermes profiles: who is on it, each member's job title, what
it's for, role text, model and skills are read from and written to the member's
own profile (actions/team.py). AGOS keeps only a bare id per member; the agent rows
it kept whole before moved into the profiles once."""

import json
from typing import Any

import yaml
from test_engine_sync import profile_dir
from test_library import MODEL, env, ws  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, team


def _meta(home: Any) -> dict[str, Any]:
    return yaml.safe_load((home / "profile.yaml").read_text()) or {}


def _row(core: Any, item_id: int) -> Any:
    return core.db.execute("SELECT * FROM library_items WHERE id = ?", (item_id,)).fetchone()


def test_a_member_lives_only_in_its_hermes_profile(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a = ws(client, "Alpha")
    r = client.post(
        f"/workspaces/{a}/agents",
        json={
            "name": "script-writer",
            "title": "Script Writer",
            "summary": "Writes the video scripts.",
            "definition": {
                "instructions": "You write the scripts.",
                "model": MODEL,
                "skills": ["copywriting"],
            },
        },
    )
    assert r.status_code == 201, r.text
    writer = int(r.json()["id"])
    profile = profile_dir(home, f"agos-{a}--a-script-writer")
    meta = _meta(profile)
    # Title and what it's for: Hermes's own profile fields.
    assert meta["display_name"] == "Script Writer"
    assert meta["description"] == "Writes the video scripts."
    assert meta["ui_meta"]["agos"] == {"reads": [], "own_model": True}
    # Role text: its SOUL.md; model and skills: its config.
    assert "You write the scripts." in (profile / "SOUL.md").read_text()
    config = runner.config[f"agos-{a}--a-script-writer"]
    assert (
        config["model.default"] == "claude-sonnet-5" and config["agent.reasoning_effort"] == "high"
    )
    assert json.loads(config["skills.auto_load"]) == ["copywriting"]
    describe = [c for c in runner.calls if c[1:3] == ["profile", "describe"]]
    assert describe and describe[-1][3] == "a-script-writer"
    # AGOS keeps only its id: no title, text, model or on/off of its own.
    row = _row(core, writer)
    assert (row["title"], row["summary"], row["definition"]) == ("", "", "{}")
    [listed] = client.get(f"/workspaces/{a}/agents").json()
    assert listed["id"] == writer and listed["title"] == "Script Writer"
    assert listed["summary"] == "Writes the video scripts."
    assert listed["definition"]["instructions"] == "You write the scripts."
    assert listed["definition"]["model"]["model"] == "claude-sonnet-5"
    assert listed["usedBy"] == [a]

    # The owner renames its job title: Hermes's display name, and its DM follows.
    dm = client.post(f"/workspaces/{a}/workers/dm", json={"agent": "script-writer"})
    assert dm.status_code in (200, 201), dm.text
    r = client.put(
        f"/workspaces/{a}/agents/{writer}",
        json={
            "name": "script-writer",
            "title": "Lead Script Writer",
            "summary": "Writes the video scripts.",
            "definition": {"instructions": "You write the scripts.", "model": None},
        },
    )
    assert r.status_code == 204, r.text
    meta = _meta(profile)
    assert meta["display_name"] == "Lead Script Writer"
    assert "own_model" not in meta["ui_meta"]["agos"]  # follows the workspace's again
    titles = [c["title"] for c in client.get(f"/workspaces/{a}/workers").json()["members"]]
    assert titles == ["Lead Script Writer"]
    # Its DM holds no copy: its name is the member's Hermes display name.
    dm = core.db.execute(
        "SELECT id, title FROM chats WHERE kind = 'dm' AND agent = 'script-writer'"
    ).fetchone()
    assert dm is None or dm["title"] == ""

    # Changed in Hermes itself (its own profile editor): AGOS shows it from there.
    meta["display_name"] = "Head Writer"
    (profile / "profile.yaml").write_text(yaml.safe_dump(meta))
    assert [c["title"] for c in client.get(f"/workspaces/{a}/agents").json()] == ["Head Writer"]

    # Off the team: Hermes's parked marker (the gateway stops serving it), memory kept.
    r = client.put(f"/workspaces/{a}/connectors/{writer}", json={"on": False, "local": "Short."})
    assert r.status_code == 204, r.text
    assert (profile / "gateway.parked").exists() and (profile / "SOUL.md").is_file()
    assert team.names(core, a) == [] and not agent_profiles.ready(core, a, "script-writer")
    assert "Short." in (profile / "SOUL.md").read_text()  # his notes for it: its SOUL.md
    off = {c["name"]: c for c in client.get(f"/workspaces/{a}/connectors").json()}
    assert off["script-writer"]["on"] is False and off["script-writer"]["local"] == "Short."
    client.put(f"/workspaces/{a}/connectors/{writer}", json={"on": True, "local": "Short."})
    assert not (profile / "gateway.parked").exists() and team.names(core, a) == ["script-writer"]

    # Deleted: Hermes's profile delete; its id goes too.
    assert client.delete(f"/workspaces/{a}/agents/{writer}").status_code == 204
    assert not profile.exists() and _row(core, writer) is None
    assert client.get(f"/workspaces/{a}/agents").json() == []


def test_a_profile_made_in_hermes_is_on_the_team(env: Any) -> None:  # noqa: F811
    """`hermes profile create a-researcher` in the root: AGOS lists it as a member."""
    client, core, _runner, home = env
    a = ws(client, "Alpha")
    core.engine.ensure_profile(f"{a}--a-researcher")
    [member] = client.get(f"/workspaces/{a}/agents").json()
    assert member["name"] == "researcher" and member["title"] == "Researcher"
    assert team.names(core, a) == ["researcher"]
    # Gone from Hermes: gone from the team, its id too.
    import shutil

    shutil.rmtree(profile_dir(home, f"agos-{a}--a-researcher"))
    assert client.get(f"/workspaces/{a}/agents").json() == []
    assert _row(core, int(member["id"])) is None
    # A fresh `hermes profile create` has no config.yaml yet (only .env, SOUL.md).
    fresh = profile_dir(home, f"agos-{a}--a-analyst")
    fresh.mkdir(parents=True)
    (fresh / ".env").write_text("")
    assert team.names(core, a) == ["analyst"]
    core.engine.ensure_profile(f"{a}--a-analyst")  # never made a second time
    assert not [c for c in _runner.calls if c[1:4] == ["profile", "create", "a-analyst"]]


def test_off_the_team_is_hermess_gateway_stop_while_the_root_runs(env: Any) -> None:  # noqa: F811
    """`hermes -p <member> gateway stop|start` parks or unparks the member and the
    root's running gateway (un)serves it at once (multi-profile-gateways.md). With
    the root's gateway down Hermes leaves the marker alone, so AGOS sets it."""
    client, core, runner, home = env
    a = ws(client, "Alpha")
    r = client.post(
        f"/workspaces/{a}/agents",
        json={"name": "editor", "title": "Editor", "definition": {"instructions": "Edit."}},
    )
    assert r.status_code == 201, r.text
    item = int(r.json()["id"])
    profile = profile_dir(home, f"agos-{a}--a-editor")
    core.engine.is_running = lambda workspace_id: True
    client.put(f"/workspaces/{a}/connectors/{item}", json={"on": False, "local": ""})
    assert (profile / "gateway.parked").exists()
    assert [v for _, v in runner.gateway_verbs] == ["stop"]
    client.put(f"/workspaces/{a}/connectors/{item}", json={"on": True, "local": ""})
    assert not (profile / "gateway.parked").exists()
    assert [v for _, v in runner.gateway_verbs] == ["stop", "start"]
    # The root's gateway is down: no Hermes call can park it, the marker is set.
    core.engine.is_running = lambda workspace_id: False
    client.put(f"/workspaces/{a}/connectors/{item}", json={"on": False, "local": ""})
    assert (profile / "gateway.parked").exists() and len(runner.gateway_verbs) == 2


def test_only_team_park_sets_the_parked_marker() -> None:
    """The marker is Hermes's `gateway stop|start`: AGOS writes it itself only in
    team.park (root's gateway down)."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "agos_core"
    calls = {
        p.relative_to(src).as_posix(): p.read_text().count("set_parked(")
        for p in src.rglob("*.py")
        if "set_parked(" in p.read_text()
    }
    assert calls == {"engine/profile_meta.py": 1, "actions/team.py": 1}, calls
    text = (src / "actions" / "team.py").read_text()
    assert '"gateway", "stop" if value else "start"' in text
