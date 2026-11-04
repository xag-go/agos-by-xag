"""The library, each workspace's own items and its connectors, written into Hermes."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner, profile_dir

from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import library as lib

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}
SKILL = "---\nname: invoice-check\ndescription: Check invoices for mistakes.\n---\n\n1. Read it.\n"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, FakeRunner, Path]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        runner = FakeRunner(hermes_home)
        core.engine.runner = runner
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        # Like the core's start: Hermes's managed scope gets the owner's values.
        from agos_core.actions import hermes_managed

        hermes_managed.at_start(core)
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, core, runner, hermes_home


def ws(client: TestClient, name: str) -> str:
    return str(client.post("/workspaces", json={"name": name, "defaultModel": MODEL}).json()["id"])


def item(client: TestClient, kind: str, name: str, definition: dict[str, Any], **extra: Any) -> int:
    r = client.post(f"/library/{kind}", json={"name": name, "definition": definition, **extra})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def skill(client: TestClient, w: str, name: str = "invoice-check", text: str = SKILL) -> int:
    """A skill is made inside ONE workspace (on there at once)."""
    r = client.post(f"/workspaces/{w}/skills", json={"name": name, "definition": {"text": text}})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def mcp(client: TestClient, w: str, name: str, definition: dict[str, Any]) -> int:
    """An MCP server is made inside ONE workspace (on there at once)."""
    r = client.post(f"/workspaces/{w}/mcp", json={"name": name, "definition": definition})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def turn_on(client: TestClient, w: str, item_id: int, **extra: Any) -> int:
    return int(
        client.put(f"/workspaces/{w}/connectors/{item_id}", json={"on": True, **extra}).status_code
    )


def turn_off(client: TestClient, w: str, item_id: int) -> int:
    return int(client.put(f"/workspaces/{w}/connectors/{item_id}", json={"on": False}).status_code)


def all_tools_off(client: TestClient, w: str) -> None:
    """Tools are on by default: a test that needs them off turns them off."""
    for t in client.get("/library", params={"kind": "tool"}).json():
        if t["locked"] is None:
            turn_off(client, w, t["id"])


def test_hermes_tools_are_listed_with_locked_ones(env: Any) -> None:
    client, *_ = env
    tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
    assert tools["code_execution"]["locked"] is None
    assert tools["connections"]["locked"].startswith("Locked")
    w = ws(client, "Alpha")
    assert turn_on(client, w, tools["connections"]["id"]) == 409
    assert (
        client.delete(
            f"/library/items/{tools['web' if 'web' in tools else 'tts']['id']}"
        ).status_code
        == 400
    )


def test_a_skill_belongs_to_its_workspace(env: Any) -> None:
    """A skill is made inside one workspace: its folder is that root's
    skills/agos-library (the Co-Founder's local skills), on there at once; the other
    workspace has nothing of it, and no profile reads AGOS's old shared folder."""
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    sid = skill(client, a)
    root_a = profile_dir(home, f"agos-{a}")
    assert (root_a / "skills" / "agos-library" / "invoice-check" / "SKILL.md").read_text() == SKILL
    listed = client.get(f"/workspaces/{a}/skills").json()
    assert [(i["name"], i["summary"], i["usedBy"]) for i in listed] == [
        ("invoice-check", "Check invoices for mistakes.", [a])
    ]
    assert client.get(f"/workspaces/{b}/skills").json() == []
    assert client.get("/library", params={"kind": "skill"}).json() == []
    assert "invoice-check" not in json.loads(runner.config[f"agos-{a}"]["skills.disabled"])
    for w in (a, b):
        dirs = json.loads(runner.config[f"agos-{w}"]["skills.external_dirs"])
        assert str(core.layout.global_dir / "skills") not in dirs
        # A Co-Founder has its workspace's skills as its own: never an external folder.
        assert not any(d.endswith("/skills/agos-library") for d in dirs)
    assert not (
        profile_dir(home, f"agos-{b}") / "skills" / "agos-library" / "invoice-check"
    ).exists()
    # Off and on: Hermes's own skills.disabled; out of another workspace's reach.
    assert turn_off(client, a, sid) == 204
    assert "invoice-check" in json.loads(runner.config[f"agos-{a}"]["skills.disabled"])
    assert turn_on(client, a, sid) == 204
    assert "invoice-check" not in json.loads(runner.config[f"agos-{a}"]["skills.disabled"])
    assert turn_on(client, b, sid) == 404
    assert client.delete(f"/workspaces/{b}/skills/{sid}").status_code == 404
    # The same name in another workspace is its own skill.
    other = skill(client, b)
    assert other != sid
    assert client.post("/library/skill", json={"name": "x", "definition": {}}).status_code == 400


def test_bad_skills_are_refused(env: Any) -> None:
    client, *_ = env
    w = ws(client, "Alpha")
    bad = [
        "no frontmatter",
        "---\nname: other\ndescription: x\n---\nbody",
        "---\nname: invoice-check\n---\nbody",
        "---\nname: invoice-check\ndescription: x\n---\n",
    ]
    for text in bad:
        r = client.post(
            f"/workspaces/{w}/skills", json={"name": "invoice-check", "definition": {"text": text}}
        )
        assert r.status_code == 400, text


def test_mcp_on_in_a_only_with_its_own_secret(env: Any) -> None:
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    mid = mcp(
        client,
        a,
        "crm",
        {
            "url": "https://crm.example.com/mcp",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer",
        },
    )
    assert turn_on(client, a, mid, allowedTools=["find_client", " "]) == 204
    r = client.put(
        f"/workspaces/{a}/connectors/{mid}/secret", json={"value": "sk-very-secret-1234"}
    )
    assert r.status_code == 204
    servers_a = json.loads(runner.config[f"agos-{a}"]["mcp_servers"])
    assert servers_a == {
        "crm": {
            "url": "https://crm.example.com/mcp",
            "headers": {"Authorization": "Bearer ${AGOS_MCP_CRM}"},
            "tools": {"include": ["find_client"]},
            "enabled": True,
            "agos": {"auth_header": "Authorization", "auth_scheme": "Bearer"},
        }
    }
    # The server lives in Hermes only: AGOS's row is its id and name, no copy.
    row = core.db.execute("SELECT definition FROM library_items WHERE id = ?", (mid,)).fetchone()
    assert row["definition"] == "{}"
    assert json.loads(runner.config.get(f"agos-{b}", {}).get("mcp_servers", "{}")) == {}
    env_a = (profile_dir(home, f"agos-{a}") / ".env").read_text()
    assert "AGOS_MCP_CRM=sk-very-secret-1234" in env_a and "API_SERVER_KEY" in env_a
    assert "AGOS_MCP" not in (profile_dir(home, f"agos-{b}") / ".env").read_text()
    # The secret is never sent back: only its last 4.
    listed = {c["name"]: c for c in client.get(f"/workspaces/{a}/connectors").json()}
    assert listed["crm"]["secret"] == "••••1234"  # noqa: S105 - masked value
    assert listed["crm"]["needsSecret"]
    assert "sk-very" not in client.get(f"/workspaces/{a}/connectors").text
    client.put(f"/workspaces/{a}/connectors/{mid}/secret", json={"value": None})
    assert "AGOS_MCP_CRM" not in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    # Beta never sees Alpha's MCP server, can't use it, set its key or test it.
    assert "crm" not in {c["name"] for c in client.get(f"/workspaces/{b}/connectors").json()}
    assert [m["name"] for m in client.get(f"/workspaces/{b}/mcp").json()] == []
    assert turn_on(client, b, mid) == 404
    r = client.put(f"/workspaces/{b}/connectors/{mid}/secret", json={"value": "x"})
    assert r.status_code == 404
    assert client.post(f"/workspaces/{b}/mcp/{mid}/test").status_code == 404
    assert client.delete(f"/workspaces/{b}/mcp/{mid}").status_code == 404
    # It is in Settings' shared list too: its definition only, never its key.
    listed_mcp = client.get("/library", params={"kind": "mcp"})
    assert [(i["name"], i["usedBy"]) for i in listed_mcp.json()] == [("crm", [a])]
    assert "sk-ver" not in listed_mcp.text
    # Beta can have its own "crm": a different server, its own key.
    other = mcp(client, b, "crm", {"url": "https://crm2.example.com/mcp"})
    assert other != mid
    assert json.loads(runner.config[f"agos-{b}"]["mcp_servers"])["crm"]["url"].startswith(
        "https://crm2."
    )
    shared_now = {i["name"]: i for i in client.get("/library", params={"kind": "mcp"}).json()}
    assert shared_now["crm"]["usedBy"] == [a] and shared_now["crm-2"]["usedBy"] == [b]
    assert shared_now["crm-2"]["definition"]["url"] == "https://crm2.example.com/mcp"
    # Deleting Alpha's leaves Beta's.
    assert client.delete(f"/workspaces/{a}/mcp/{mid}").status_code == 204
    assert "crm" in json.loads(runner.config[f"agos-{b}"]["mcp_servers"])


def test_unsafe_mcp_servers_are_refused(env: Any) -> None:
    client, *_ = env
    a = ws(client, "Alpha")
    for definition in (
        {"transport": "carrier-pigeon", "url": "https://crm.example.com/mcp"},
        {"url": "http://localhost:8080/mcp"},
        {"url": "http://127.0.0.1:9/mcp"},
        {"url": "http://192.168.1.4/mcp"},
        {"url": "https://user:pw@crm.example.com/mcp"},
        {"url": "ftp://crm.example.com"},
    ):
        r = client.post(f"/workspaces/{a}/mcp", json={"name": "bad", "definition": definition})
        assert r.status_code == 400, definition


def test_safe_tool_and_plugin_follow_the_workspace(env: Any) -> None:
    client, _core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    tools = {i["name"]: i["id"] for i in client.get("/library", params={"kind": "tool"}).json()}
    pid = item(client, "plugin", "notes-sync", {"plugin": "notes_sync"})
    all_tools_off(client, a)
    all_tools_off(client, b)
    turn_on(client, a, tools["code_execution"])
    turn_on(client, a, pid)
    disabled_a = json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])
    disabled_b = json.loads(runner.config[f"agos-{b}"]["agent.disabled_toolsets"])
    assert "code_execution" not in disabled_a and "code_execution" in disabled_b
    assert {"browser", "vision"} <= set(disabled_a)
    # agos-guard (the owner's Autonomy rules) is always on in every workspace.
    assert json.loads(runner.config[f"agos-{a}"]["plugins.enabled"]) == ["agos-guard", "notes_sync"]
    assert json.loads(runner.config[f"agos-{b}"]["plugins.enabled"]) == ["agos-guard"]


def test_cronjob_is_always_on(env: Any) -> None:
    """Hermes's cron is how agents come back to him and keep an eye on things."""
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
    assert tools["cronjob"]["always"] is True  # shown, with no switch
    assert "cronjob" not in json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])


def test_vision_and_video_can_be_turned_on_without_a_screen(env: Any) -> None:
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
    assert tools["vision"]["locked"] is None and tools["video"]["locked"] is None
    all_tools_off(client, a)
    turn_on(client, a, tools["vision"]["id"])
    turn_on(client, a, tools["video"]["id"])
    config = runner.config[f"agos-{a}"]
    disabled = json.loads(config["agent.disabled_toolsets"])
    assert "vision" not in disabled and "video" not in disabled
    assert {"browser", "computer_use"} <= set(disabled)
    assert config["bot_desktop.placement"] == "terminal"
    # A new profile gets the workspace's model, not Hermes's template default.
    assert config["model.default"] == MODEL["model"]
    assert config["model.provider"] in ("anthropic", "openai-codex", "openai-api")


def test_screen_off_and_on_never_stops_the_gateway_of_a_team_whose_model_moved(
    env: Any,
) -> None:
    """The e2e's Screen step (Bravo, 2 members): each Browser / Computer use switch
    re-syncs the members (in the background live). The workspace's model changed
    before, and the members follow it at that re-sync: a new model alone is no reason
    to stop the root's one gateway (Hermes reads model.* for each turn), so it runs on
    through all four switches. (It was stopped and started once per member, so an
    MCP server added in the next seconds missed Hermes's own reconcile.)"""
    import types

    from test_agent_profiles import add_agent

    from agos_core.actions import engine as engine_actions

    client, core, runner, _home = env
    a = ws(client, "Bravo")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    pick = types.SimpleNamespace(provider="openrouter", mode="api", model="x/two", effort="high")
    engine_actions.set_model(core, a, pick)  # Workspace settings -> its model
    verbs: list[tuple[str, str]] = []
    core.engine.is_running = lambda workspace_id: True
    core.engine.stop = lambda workspace_id, **_: verbs.append(("stop", workspace_id))
    core.engine.start = lambda workspace_id, **_: verbs.append(("start", workspace_id))
    tools = {i["name"]: i["id"] for i in client.get("/library", params={"kind": "tool"}).json()}
    for on in (False, True):
        for name in ("browser", "computer_use"):
            put = client.put(f"/workspaces/{a}/connectors/{tools[name]}", json={"on": on})
            assert put.status_code == 204
    assert verbs == []
    for agent in ("writer", "editor"):  # each member runs on the workspace's model now
        assert runner.config[f"agos-{a}--a-{agent}"]["model.default"] == "x/two"


def test_a_folder_click_restarts_a_team_s_gateway_once_and_every_member_mounts_it(
    env: Any, tmp_path: Path
) -> None:
    """C2 (members): the folder click's background restart writes the root's and
    each member's sandbox keys inside ONE stop and start of the root's one gateway,
    so every member has the new folder at once; a Library switch afterwards finds
    every setup applied and stops nothing (each member's re-sync used to stop and
    start it once more)."""
    from test_agent_profiles import add_agent

    client, core, runner, _home = env
    a = ws(client, "Bravo")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    up = {"on": True}
    verbs: list[str] = []

    def stop(workspace_id: str, **_: Any) -> None:
        verbs.append("stop")
        up["on"] = False

    def start(workspace_id: str, **_: Any) -> None:
        verbs.append("start")
        up["on"] = True

    core.engine.is_running = lambda workspace_id: up["on"]
    core.engine.stop, core.engine.start = stop, start
    reports = tmp_path / "Reports"
    reports.mkdir()
    assert client.post(f"/workspaces/{a}/folders", json={"path": str(reports)}).status_code == 201
    assert verbs == ["stop", "start"]
    for profile in (f"agos-{a}", f"agos-{a}--a-writer", f"agos-{a}--a-editor"):
        vols = json.loads(runner.config[profile]["terminal.docker_volumes"])
        assert f"{reports.resolve()}:/shared/reports:ro" in vols, profile
    verbs.clear()
    tools = {i["name"]: i["id"] for i in client.get("/library", params={"kind": "tool"}).json()}
    put = client.put(f"/workspaces/{a}/connectors/{tools['browser']}", json={"on": False})
    assert put.status_code == 204
    assert verbs == []


def test_browser_gives_only_that_workspace_a_screen_in_its_sandbox(env: Any) -> None:
    """The screen is Hermes's: every sandbox has the desktop stack (Hermes's own
    default image), Hermes starts the screen inside it when a tool needs it, and
    the browser / computer use switch is only Hermes's agent.disabled_toolsets."""
    client, core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
    assert tools["browser"]["locked"] is None and tools["computer_use"]["locked"] is None
    all_tools_off(client, a)
    all_tools_off(client, b)
    image = runner.config[f"agos-{a}"]["terminal.docker_image"]
    assert image.endswith(":desktop")
    assert client.get(f"/workspaces/{a}/screen").json()["enabled"] is False
    removed = sum(1 for c in runner.calls if c[1:3] == ["rm", "-f"])
    assert turn_on(client, a, tools["browser"]["id"]) == 204
    ca, cb = runner.config[f"agos-{a}"], runner.config[f"agos-{b}"]
    assert ca["terminal.docker_image"] == image == cb["terminal.docker_image"]
    assert ca["bot_desktop.placement"] == "terminal"  # never the machine itself
    assert "browser" not in json.loads(ca["agent.disabled_toolsets"])
    assert "browser" in json.loads(cb["agent.disabled_toolsets"])
    # Nothing is rebuilt: the same sandbox, the same mounts and network.
    assert sum(1 for c in runner.calls if c[1:3] == ["rm", "-f"]) == removed
    assert ca["terminal.docker_volumes"] == cb["terminal.docker_volumes"].replace(b, a)
    # The Screen tab reads Hermes's config: on for Alpha only.
    assert client.get(f"/workspaces/{a}/screen").json()["enabled"] is True
    assert client.get(f"/workspaces/{b}/screen").json()["enabled"] is False
    # When Hermes stops an unused screen: its own bot_desktop.idle_stop_minutes
    # (Hermes's default from its settings list while the workspace sets none).
    from agos_core.engine.hermes_schema import Field

    core.engine.config_schema = lambda: [Field("bot_desktop.idle_stop_minutes", "number", "", 30)]
    assert client.get(f"/workspaces/{a}/screen").json()["idleStopMinutes"] == 30
    core.engine._hermes(a, "config", "set", "bot_desktop.idle_stop_minutes", "12")
    assert client.get(f"/workspaces/{a}/screen").json()["idleStopMinutes"] == 12
    # No screen running in Hermes (no bot-desktop record): no picture, no docker call.
    assert client.get(f"/workspaces/{a}/screen.jpg").status_code == 204
    # Turning it off is Hermes's switch again.
    assert turn_off(client, a, tools["browser"]["id"]) == 204
    assert "browser" in json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])
    assert client.get(f"/workspaces/{a}/screen").json()["enabled"] is False
    assert core.engine is not None
    assert not (core.engine.profile_home(a) / ".agos-screen").exists()


def test_local_mcp_runs_in_the_workspace_container_never_on_the_machine(env: Any) -> None:
    client, _core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    r = client.post(
        f"/workspaces/{a}/mcp",
        json={
            "name": "files",
            "definition": {
                "transport": "command",
                "command": "npx -y @modelcontextprotocol/server-filesystem /workspace",
            },
        },
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]  # made in Alpha: on there at once
    on = {c["itemId"]: c["on"] for c in client.get(f"/workspaces/{a}/connectors").json()}
    assert on[mid] is True
    servers_a = json.loads(runner.config[f"agos-{a}"]["mcp_servers"])
    # Hermes gets a loopback HTTP address + its relay's bearer, never a command (AGOS's note).
    assert set(servers_a["files"]) <= {"url", "headers", "tools", "enabled", "agos"}
    assert servers_a["files"]["headers"] == {"Authorization": "Bearer ${AGOS_MCP__RELAY_FILES}"}
    assert "command" not in servers_a["files"] and servers_a["files"]["agos"]["command"]
    assert servers_a["files"]["url"].startswith("http://127.0.0.1:")
    started = [
        c
        for c in runner.calls
        if Path(c[0]).name == "docker" and c[1] == "run" and f"agos-mcp-agos-{a}-files" in c
    ]
    assert started, "the server container was not started"
    run = started[0]
    assert run[run.index("--network") + 1] == f"agos-net-agos-{a}"
    mounts = [run[i + 1] for i, part in enumerate(run) if part == "-v"]
    assert len(mounts) == 1 and mounts[0].endswith(f"/{a}/files:/workspace")
    assert not any("docker.sock" in part for part in run)
    # The other workspace gets nothing.
    assert "files" not in json.loads(runner.config[f"agos-{b}"].get("mcp_servers", "{}"))
    # Turning it off is Hermes's own switch.
    assert turn_off(client, a, mid) == 204
    assert json.loads(runner.config[f"agos-{a}"]["mcp_servers"])["files"]["enabled"] is False


def test_local_mcp_command_is_checked(env: Any) -> None:
    client, *_ = env
    a = ws(client, "Alpha")
    for command in ("", "npx 'unclosed", "a\nb"):
        r = client.post(
            f"/workspaces/{a}/mcp",
            json={"name": "bad", "definition": {"transport": "command", "command": command}},
        )
        assert r.status_code == 400, command


def test_a_deleted_skill_is_archived_by_hermes_s_curator(env: Any) -> None:
    client, _core, runner, home = env
    a = ws(client, "Alpha")
    sid = skill(client, a)
    copy = client.post(f"/workspaces/{a}/skills/{sid}/duplicate", json={"name": "invoice-check-2"})
    assert copy.status_code == 201, copy.text
    names = {i["name"] for i in client.get(f"/workspaces/{a}/skills").json()}
    assert names == {"invoice-check", "invoice-check-2"}
    folder = profile_dir(home, f"agos-{a}") / "skills"
    assert (
        "name: invoice-check-2"
        in (folder / "agos-library" / "invoice-check-2" / "SKILL.md").read_text()
    )
    assert client.delete(f"/workspaces/{a}/skills/{sid}").status_code == 204
    assert not (folder / "agos-library" / "invoice-check").exists()
    assert (folder / ".archive" / "invoice-check" / "SKILL.md").is_file()  # recoverable
    assert ["curator-archived", f"agos-{a}", "invoice-check"] in runner.calls
    names = {i["name"] for i in client.get(f"/workspaces/{a}/skills").json()}
    assert names == {"invoice-check-2"}


def test_agent_role_is_added_only_where_it_is_on(env: Any) -> None:
    client, core, *_ = env
    from agos_core.actions.library import agent_text

    a, b = ws(client, "Alpha"), ws(client, "Beta")
    r = client.post(
        f"/workspaces/{a}/agents",
        json={
            "name": "reviewer",
            "title": "Reviewer",
            "definition": {"instructions": "Review with care."},
        },
    )
    aid = int(r.json()["id"])
    turn_on(client, a, aid, local="Focus on invoices.")
    # Another workspace can't turn on (or even see) this team's agent.
    assert turn_on(client, b, aid) == 404
    assert client.get(f"/workspaces/{b}/agents").json() == []
    assert (
        client.post(
            "/library/agent", json={"name": "x", "definition": {"instructions": "y"}}
        ).status_code
        == 400
    )
    text = agent_text(core, a, "reviewer")
    assert (
        text and "Reviewer" in text and "Review with care." in text and "Focus on invoices." in text
    )
    assert agent_text(core, b, "reviewer") is None


def test_mcp_entry_without_secret_has_no_header() -> None:
    entry = lib.mcp_entry(
        "wiki",
        {"url": "https://x/mcp", "auth_header": "Authorization", "auth_scheme": ""},
        has_secret=False,
        allowed_tools=[],
    )
    assert entry == {"url": "https://x/mcp"}


def test_an_mcp_key_goes_as_bearer_when_no_header_is_set() -> None:
    entry = lib.mcp_entry("tracker", {"url": "https://x/mcp"}, has_secret=True, allowed_tools=[])
    assert entry["headers"] == {"Authorization": "Bearer ${" + lib.env_name("tracker") + "}"}
    custom = lib.mcp_entry(
        "wiki",
        {"url": "https://x/mcp", "auth_header": "X-Api-Key", "auth_scheme": ""},
        has_secret=True,
        allowed_tools=[],
    )
    assert custom["headers"] == {"X-Api-Key": "${" + lib.env_name("wiki") + "}"}


def test_an_oauth_sign_in_made_in_hermes_is_kept(tmp_path: Path) -> None:
    from agos_core.actions.library import oauth_signed_in, profile_settings

    tokens = tmp_path / "mcp-tokens"
    tokens.mkdir()
    for f in ("tracker.json", "tracker.client.json", "tracker.meta.json"):
        (tokens / f).write_text("{}")
    assert oauth_signed_in(tmp_path) == {"tracker"}
    servers = {"tracker": {"url": "https://x/mcp", "auth": "oauth", "enabled": True}}
    # What the workspace's Hermes has is written as it is.
    assert json.loads(profile_settings([], servers)["mcp_servers"]) == servers


def test_every_hermes_feature_is_on_by_default(env: Any) -> None:
    """A new workspace has every tool AGOS can give safely, on every place it works
    (chats, Telegram, automations), and Hermes's learning: skills, memory, past
    conversations, the curator merging its skills. The owner turns off what he
    doesn't want; locked ones stay off."""
    client, core, runner, _home = env
    w = ws(client, "Fresh")
    config = runner.config[f"agos-{w}"]
    off = json.loads(config["agent.disabled_toolsets"])
    assert "browser" not in off and "computer_use" not in off and "tts" not in off
    assert "connections" in off  # locked
    for place in ("agos", "telegram", "cron"):
        sets = json.loads(config[f"platform_toolsets.{place}"])
        for name in ("skills", "memory", "session_search", "computer_use", "tts", "video", "agos"):
            assert name in sets, (place, name)
        assert "connections" not in sets
    assert "kanban" in json.loads(config["platform_toolsets.agos"])
    assert config["curator.consolidate"] == "true"
    # Turned off by the owner: off everywhere, and not turned on again.
    tool = next(
        i for i in client.get("/library", params={"kind": "tool"}).json() if i["name"] == "tts"
    )
    client.put(f"/workspaces/{w}/connectors/{tool['id']}", json={"on": False})
    from agos_core.actions import library

    library.apply_workspace(core, w)
    (core.engine.profile_home(w) / ".agos-connectors").unlink()
    library.apply_workspace(core, w)
    config = runner.config[f"agos-{w}"]
    assert "tts" in json.loads(config["agent.disabled_toolsets"])
    assert "tts" not in json.loads(config["platform_toolsets.agos"])


def test_strangers_get_hermes_pairing_code_on_telegram() -> None:
    """With an allowlist, Hermes ignores strangers unless Telegram's own key says
    pair (gateway/authz_mixin.py _get_unauthorized_dm_behavior)."""
    from agos_core.actions.library import profile_settings

    settings = profile_settings([])
    assert settings["unauthorized_dm_behavior"] == "pair"
    assert settings["platforms.telegram.extra.unauthorized_dm_behavior"] == "pair"
