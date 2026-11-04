"""Library → Tools, Hermes's own tool list: whether a tool really works as Hermes says,
a tool Hermes adds shows up by itself, a tool's service set up once into every Hermes,
a server added in Hermes shows while a host command never runs, and descriptions read
the way Hermes folds them.

Split out of test_library.py (skills, MCP servers and turning tools on stay there)."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_library import env, skill, ws  # noqa: F401

from agos_core.config import EngineConfig
from agos_core.engine import library as lib


def test_a_tool_shows_whether_it_really_works_as_hermes_says(env: Any) -> None:  # noqa: F811
    """A tool that needs a service (pictures, voice…) is on but may not work: the
    Capabilities page shows what the workspace's Hermes really gives the agent."""
    client, core, _runner, _home = env
    w = ws(client, "Alpha")
    asked: list[str] = []

    def readiness(workspace_id: str) -> dict[str, bool]:
        asked.append(workspace_id)
        return {"image_gen": False, "tts": True}

    core.engine.tool_readiness = readiness
    tools = {c["name"]: c for c in client.get(f"/workspaces/{w}/connectors").json()}
    assert tools["image_gen"]["on"] and tools["image_gen"]["works"] is False
    assert tools["tts"]["works"] is True
    assert tools["browser"]["works"] is None  # needs no service
    assert asked == [w]
    # Off: not shown as broken.
    client.put(f"/workspaces/{w}/connectors/{tools['image_gen']['itemId']}", json={"on": False})
    tools = {c["name"]: c for c in client.get(f"/workspaces/{w}/connectors").json()}
    assert tools["image_gen"]["works"] is None


def test_hermess_own_tool_list_shows_up_by_itself(env: Any) -> None:  # noqa: F811
    """The tools come from Hermes's own list: one Hermes adds appears in Settings
    and in every workspace, on; locked ones stay locked; services come along."""
    from agos_core.actions import library
    from agos_core.engine import hermes_tools

    client, core, runner, _home = env
    w = ws(client, "Alpha")
    listed = [
        *[t for t in hermes_tools.FALLBACK if t["key"] != "video_gen"],
        {
            "key": "video_gen",
            "label": "Video Generation",
            "about": "Make videos.",
            "providers": [
                {
                    "name": "FAL",
                    "badge": "paid",
                    "about": "x",
                    "nous": False,
                    "env": [{"key": "FAL_KEY", "prompt": "FAL API key", "url": "u"}],
                }
            ],
        },
    ]
    core.engine.tools_catalog = lambda: listed
    library.refresh_tools(core)
    try:
        tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
        assert tools["video_gen"]["title"] == "Video Generation"
        assert tools["video_gen"]["services"][0]["env"][0]["key"] == "FAL_KEY"
        assert tools["connections"]["locked"] and tools["memory"]["always"]
        mine = {c["name"]: c for c in client.get(f"/workspaces/{w}/connectors").json()}
        assert mine["video_gen"]["on"] is True  # new from Hermes: on
        sets = json.loads(runner.config[f"agos-{w}"]["platform_toolsets.agos"])
        assert "video_gen" in sets
        # Hermes's list is not saved in AGOS (memory only; a restart asks again).
        saved = core.db.execute("SELECT key FROM app_settings WHERE key LIKE 'hermes.tools%'")
        assert saved.fetchall() == []
    finally:
        hermes_tools._current["list"] = hermes_tools.FALLBACK


def test_a_tools_service_is_set_up_once_from_agos_into_every_hermes(env: Any) -> None:  # noqa: F811
    """Settings → Tools: pick a service from Hermes's list and give its key once;
    Hermes's own selection runs in the connectors home and every workspace's
    profile (members too). AGOS keeps only which one and the key's last 4."""
    from agos_core.engine import hermes_tools

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    jobs: list[tuple[str, dict[str, Any]]] = []
    active: dict[str, dict[str, str | None]] = {}  # each home's Hermes: what it uses

    def hermes_takes(where: Any, job: dict[str, Any]) -> str | None:
        jobs.append((str(where), job))
        active.setdefault(str(where), {})[job["toolset"]] = job["provider"]
        (where / "config.yaml").touch()
        env_file = where / ".env"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        old = env_file.read_text() if env_file.exists() else ""
        env_file.write_text(old + "".join(f"{k}={v}\n" for k, v in job["env"].items()))
        return "ddgs" if job.get("install") else None

    core.engine.set_tool_service = hermes_takes
    core.engine.tool_services_in = lambda home: dict(active.get(str(home), {}))
    installs: list[str] = []
    core.engine.tools_install = lambda _home, step, _log: installs.append(step)
    hermes_tools._current["list"] = [
        *[t for t in hermes_tools.FALLBACK if t["key"] != "image_gen"],
        {
            "key": "image_gen",
            "label": "Image Generation",
            "about": "x",
            "providers": [
                {
                    "name": "FAL.ai",
                    "badge": "paid",
                    "about": "x",
                    "nous": False,
                    "env": [{"key": "FAL_KEY", "prompt": "FAL API key", "url": "https://fal.ai"}],
                },
                {"name": "Nous Subscription", "badge": "", "about": "", "nous": True, "env": []},
            ],
        },
    ]
    try:
        url = "/library/tools/image_gen/service"
        assert client.put(url, json={"provider": "FAL.ai", "keys": {}}).status_code == 400
        assert client.put(url, json={"provider": "Nous Subscription"}).status_code == 409
        key = "fal-" + "k" * 30 + "WXYZ"
        r = client.put(url, json={"provider": "FAL.ai", "keys": {"FAL_KEY": key}})
        assert r.status_code == 200, r.text
        places = [w for w, _ in jobs]
        assert places[0].endswith("system/connectors")  # the one source
        assert any(p.endswith(f"hermes/agos-{a}") for p in places)
        assert all(j["provider"] == "FAL.ai" and j["env"]["FAL_KEY"] == key for _, j in jobs)
        tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
        assert tools["image_gen"]["service"] == {"provider": "FAL.ai", "keys": {"FAL_KEY": "WXYZ"}}
        assert key not in client.get("/library", params={"kind": "tool"}).text
        assert installs == ["ddgs"]  # Hermes's own install, once
        # AGOS keeps no copy of the choice: it is read back from each profile.
        from agos_core.actions import tool_services

        assert (
            core.db.execute(
                "SELECT 1 FROM app_settings WHERE key = ?", (tool_services.OLD_SETTING,)
            ).fetchone()
            is None
        )
        # A change made in Hermes itself shows (here: one profile moved to Nous).
        home_a = next(w for w in active if w.endswith(f"hermes/agos-{a}"))
        active[home_a]["image_gen"] = "Nous Subscription"
        tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
        assert tools["image_gen"]["service"]["provider"] == "Nous Subscription"
        # A new workspace gets it too.
        active[home_a]["image_gen"] = "FAL.ai"
        jobs.clear()
        b = ws(client, "Beta")
        assert any(w.endswith(f"hermes/agos-{b}") and j["env"]["FAL_KEY"] == key for w, j in jobs)
        # Profiles that differ: the most common one, and where each is used.
        home_b = next(w for w in active if w.endswith(f"hermes/agos-{b}"))
        active[home_b]["image_gen"] = "Nous Subscription"
        active.setdefault(str(core.engine.profile_home(a)), {})
        tools = {i["name"]: i for i in client.get("/library", params={"kind": "tool"}).json()}
        assert {s["provider"] for s in tools["image_gen"]["service"]["spread"]} == {
            "FAL.ai",
            "Nous Subscription",
        }
    finally:
        hermes_tools._current["list"] = hermes_tools.FALLBACK


def test_a_server_added_in_hermes_shows_and_a_host_command_never_runs(env: Any) -> None:  # noqa: F811
    """The root's Hermes config is the source: a server added there (hermes mcp add)
    shows in AGOS; one that would run a command on this machine is left out."""
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    runner.config[f"agos-{a}"]["mcp_servers"] = json.dumps(
        {
            "wiki": {"url": "https://wiki.example.com/mcp"},
            "shell": {"command": "npx", "args": ["evil"]},
        }
    )
    runner._write_yaml(f"agos-{a}")
    names = {c["name"]: c for c in client.get(f"/workspaces/{a}/connectors").json()}
    assert names["wiki"]["on"] and names["wiki"]["kind"] == "mcp"
    from agos_core.actions.library import apply_workspace

    (core.engine.profile_home(a) / ".agos-connectors").unlink()
    assert apply_workspace(core, a) is None
    servers = json.loads(runner.config[f"agos-{a}"]["mcp_servers"])
    assert "wiki" in servers and "shell" not in servers


FOLDED = (
    "---\nname: replica-recon\ndescription: >-\n  Reverse-engineers any app into a recon map:\n"
    '  screens, flows. Use when the user says "clone this app".\n---\n\n# Recon\n\nSteps.\n'
)


# A new skill's description fits Hermes's 60-character budget (its create refuses more).
FOLDED_NEW = (
    "---\nname: replica-recon\ndescription: >-\n  Reverse-engineers any app\n"
    "  into a recon map.\n---\n\n# Recon\n\nSteps.\n"
)


def test_folded_descriptions_read_like_hermes_reads_them(env: Any) -> None:  # noqa: F811
    """A hub skill's `description: >-` block is one text (Hermes reads YAML), and a
    summary saved as `>-` by the old line reader is read again."""
    import shutil

    from agos_core.engine.skill_frontmatter import HermesFrontmatter

    client, core, _runner, _home = env
    hermes = shutil.which("hermes")
    if not hermes:
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    real = EngineConfig(
        hermes_bin=hermes,
        docker_bin="docker",
        hermes_home=_home / "real-hermes",
        profile_prefix="agos-",
        sandbox_image="x",
        host_home=Path.home(),
        roots_dir=_home / "roots",
        runtime_dir=tools if tools.is_dir() else None,
    )
    lib.use_hermes_reader(HermesFrontmatter(real))  # Hermes's own parse_frontmatter
    head, body = lib.parse_skill(FOLDED)
    assert head["description"] == (
        "Reverse-engineers any app into a recon map: screens, flows. "
        'Use when the user says "clone this app".'
    )
    assert body.strip().startswith("# Recon")
    assert (
        lib.parse_skill("---\nname: a-b\ndescription: x: y: z\n---\nok\n")[0]["description"]
        == "x: y: z"
    )
    w = ws(client, "Alpha")
    sid = skill(client, w, "replica-recon", FOLDED_NEW)
    core.db.execute("UPDATE library_items SET summary = '>-' WHERE id = ?", (sid,))
    listed = {i["id"]: i for i in client.get(f"/workspaces/{w}/skills").json()}
    assert listed[sid]["summary"].startswith("Reverse-engineers any app")
