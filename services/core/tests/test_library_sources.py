"""Step 6a: library sources (this machine, the web) and agents in runs."""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from chat_rig import CLIENT, FakeHermes, settle
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import chat as chat_actions
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import sources

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}
SKILL = (
    "---\nname: brand-voice\ndescription: Write in the brand's voice.\n---\n\nShort sentences.\n"
)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, FakeHermes, Path]]:
    hermes_home = tmp_path / "home" / ".hermes"
    (hermes_home / "skills" / "writing" / "brand-voice").mkdir(parents=True)
    (hermes_home / "skills" / "writing" / "brand-voice" / "SKILL.md").write_text(SKILL)
    (hermes_home / "skills" / "writing" / "brand-voice" / ".env").write_text("KEY=nope")
    (hermes_home / "skills" / "writing" / "brand-voice" / "notes.md").write_text("ok")
    # A fake Hermes checkout with an approved MCP catalog.
    checkout = tmp_path / "hermes-agent"
    checkout.mkdir()
    (checkout / "hermes_constants.py").write_text("")
    for name, auth in (("context7", "none"), ("airtable", "oauth")):
        (checkout / "optional-mcps" / name).mkdir(parents=True)
        (checkout / "optional-mcps" / name / "manifest.yaml").write_text(
            f"manifest_version: 1\nname: {name}\ndescription: >-\n  {name} docs.\n"
            f"transport:\n  type: http\n  url: https://mcp.{name}.com/mcp\nauth:\n  type: {auth}\n"
        )
    # Hermes's runtime command (H: hermes_cli/_launchers.py runtime_command): its
    # checkout on sys.path, then the module run AGOS asks for.
    boot = (
        f"import sys, runpy; sys.path.insert(0, {str(checkout)!r}); "
        "runpy.run_module('agos_goal_judge', run_name='__main__', alter_sys=True)"
    )
    printed = json.dumps([sys.executable, "-I", "-c", boot])
    (checkout / "hermes").write_text(f"#!/bin/sh\ncat <<'EOF'\n{printed}\nEOF\n")
    (checkout / "hermes").chmod(0o755)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin=str(checkout / "hermes"),
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    from agos_core.actions import apps as apps_actions

    # The fake checkout has no Hermes app catalog to run (test_apps covers it).
    apps_actions._catalog_cache["apps"] = {}
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        core.engine.runner = FakeRunner(hermes_home)
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        fake = FakeHermes()
        core.engine.runs_client = fake
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        CLIENT["client"] = client
        yield client, core, fake, tmp_path
    apps_actions._catalog_cache.pop("apps", None)


def _ws(client: Any) -> str:
    return str(
        client.post("/workspaces", json={"name": "Alpha", "defaultModel": MODEL}).json()["id"]
    )


def test_import_a_skill_from_this_machine_without_secrets(env: Any) -> None:
    client, core, _fake, _tmp = env
    w = _ws(client)
    found = client.get(f"/workspaces/{w}/skills/machine").json()
    (brand,) = [f for f in found if f["name"] == "brand-voice"]
    assert brand["importable"] and not brand["inLibrary"]
    r = client.post(f"/workspaces/{w}/skills/machine", json={"origin": brand["origin"]})
    assert r.status_code == 201, r.text
    folder = core.engine.profile_home(w) / "skills" / "agos-library" / "brand-voice"
    assert (folder / "SKILL.md").read_text() == SKILL and (folder / "notes.md").exists()
    assert not (folder / ".env").exists()  # never copies secrets
    item = client.get(f"/workspaces/{w}/skills").json()[0]
    assert item["source"] == "machine" and item["definition"]["hash"].startswith("sha256:")
    assert client.get(f"/workspaces/{w}/skills/machine").json()[0]["inLibrary"]
    # Paths outside Hermes's skills are refused; Settings has no skills any more.
    r = client.post(f"/workspaces/{w}/skills/machine", json={"origin": "/etc"})
    assert r.status_code == 400
    assert client.get("/library/skill/machine").status_code == 400


def test_updates_from_this_machine_apply_only_on_click(env: Any) -> None:
    client, core, _fake, _tmp = env
    w = _ws(client)
    origin = client.get(f"/workspaces/{w}/skills/machine").json()[0]["origin"]
    r = client.post(f"/workspaces/{w}/skills/machine", json={"origin": origin})
    item_id = r.json()["id"]
    assert client.get(f"/workspaces/{w}/skills/updates").json()[0]["hasUpdate"] is False
    changed = SKILL.replace("Short sentences.", "Very short sentences.")
    (Path(origin) / "SKILL.md").write_text(changed)
    update = client.get(f"/workspaces/{w}/skills/updates").json()[0]
    assert update["hasUpdate"] is True
    copy = core.engine.profile_home(w) / "skills" / "agos-library" / "brand-voice" / "SKILL.md"
    assert "Very short" not in copy.read_text()  # nothing until the click
    assert client.post(f"/workspaces/{w}/skills/{item_id}/update").status_code == 204
    assert "Very short" in copy.read_text()
    assert client.get(f"/workspaces/{w}/skills/updates").json()[0]["hasUpdate"] is False


def test_mcp_catalog_lists_remote_servers_including_oauth_ones(env: Any) -> None:
    client, *_ = env
    w = client.post("/workspaces", json={"name": "Alpha", "defaultModel": MODEL}).json()["id"]
    found = {f["name"]: f for f in client.get(f"/workspaces/{w}/mcp/machine").json()}
    assert found["context7"]["importable"] and found["context7"]["trust"] == "Nous-approved"
    # OAuth servers are added like the rest; each workspace signs in on its own.
    assert found["airtable"]["importable"] and found["airtable"]["locked"] is None
    assert "Sign in per workspace" in found["airtable"]["summary"]
    r = client.post(f"/workspaces/{w}/mcp/machine", json={"origin": found["context7"]["origin"]})
    assert r.status_code == 201, r.text
    item = next(i for i in client.get(f"/workspaces/{w}/mcp").json())
    assert item["definition"]["url"] == "https://mcp.context7.com/mcp"
    oauth = client.post(
        f"/workspaces/{w}/mcp/machine", json={"origin": found["airtable"]["origin"]}
    )
    assert oauth.status_code == 201, oauth.text


def test_a_chat_runs_as_an_agent_only_where_it_is_on(env: Any) -> None:
    client, core, fake, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    agent = client.post(
        f"/workspaces/{ws}/agents",
        json={
            "name": "reviewer",
            "title": "Reviewer",
            "definition": {"instructions": "Check twice."},
        },
    ).json()["id"]
    client.put(f"/workspaces/{ws}/connectors/{agent}", json={"on": False})
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "c"}).json()["id"]
    assert (
        client.put(f"/workspaces/{ws}/chats/{chat}", json={"agent": "reviewer"}).status_code == 400
    )
    client.put(f"/workspaces/{ws}/connectors/{agent}", json={"on": True, "local": "Invoices only."})
    assert (
        client.put(f"/workspaces/{ws}/chats/{chat}", json={"agent": "reviewer"}).status_code == 204
    )
    client.post(f"/workspaces/{ws}/chats/{chat}/messages", json={"body": "hi"})
    settle(core, lambda: bool(fake.bodies))
    instructions = fake.bodies[0]["instructions"]
    assert "Reviewer" in instructions and "Check twice." in instructions
    assert "Invoices only." in instructions
    fake.push("run_1", {"event": "run.completed", "output": "ok"})
    settle(core, lambda: not client.get(f"/workspaces/{ws}/chats/{chat}").json()["working"])
    # Clearing it: back to the workspace's own agent.
    assert client.put(f"/workspaces/{ws}/chats/{chat}", json={"agent": ""}).status_code == 204
    assert client.get(f"/workspaces/{ws}/chats/{chat}").json()["agent"] is None
    for live in chat_actions._state(core).live.values():
        live.stop = True


def test_identifier_and_yaml_helpers() -> None:
    with pytest.raises(sources.SourceError):
        sources._check_identifier("../../etc/passwd")
    sources._check_identifier("openai/skills/skills/.curated/pdf")
    text = "name: x\ndescription: >-\n  Line one\n  line two.\ntransport:\n  type: http\n  url: https://a/mcp\n"
    assert sources._yaml_folded(text, "description") == "Line one line two."
    assert sources._yaml_block_value(text, "transport", "url") == "https://a/mcp"
    assert json.loads(json.dumps(sources.as_dict(sources.Found("skill", "a", "a", "", "o"))))


def test_github_token_routes_go_through_hermes(env: Any, monkeypatch: Any) -> None:
    """Settings → Tools: GET/PUT/DELETE reach the Hermes token code (not /library/{kind})."""
    client, _core, _fake, _tmp = env
    from agos_core.engine import github_token as gt

    calls: list[str] = []
    state = gt.TokenStatus(True, "pat", 5000, 4990, 1792180000, False, None)

    def status(self: Any) -> Any:
        calls.append("status")
        return state

    monkeypatch.setattr(gt.GithubToken, "status", status)

    def save(self: Any, token: str) -> Any:
        calls.append(f"save:{token}")
        if token == "bad":  # noqa: S105 - a test value
            raise gt.TokenProblem("GitHub refused this token. Check it and paste it again.")
        return state

    monkeypatch.setattr(gt.GithubToken, "save", save)
    monkeypatch.setattr(gt.GithubToken, "remove", lambda self: calls.append("remove"))
    got = client.get("/library/github-token")
    assert got.status_code == 200, got.text
    assert got.json()["method"] == "pat" and got.json()["remaining"] == 4990
    assert "token" not in json.dumps(got.json()).lower().replace("github-token", "")
    put = client.put("/library/github-token", json={"token": "github_pat_ok"})
    assert put.status_code == 200 and put.json()["saved"] is True
    bad = client.put("/library/github-token", json={"token": "bad"})
    assert bad.status_code == 400 and "refused" in bad.text
    assert client.delete("/library/github-token").status_code == 204
    assert calls == ["status", "save:github_pat_ok", "save:bad", "remove"]


def test_install_says_when_githubs_hourly_limit_is_the_reason(env: Any, monkeypatch: Any) -> None:
    client, _core, _fake, _tmp = env
    from agos_core.engine import github_token as gt

    w = _ws(client)
    monkeypatch.setattr(
        sources.Sources,
        "inspect_skill",
        lambda self, identifier: "Error: Could not find 'a/b/c' in any source.",
    )
    empty = gt.TokenStatus(False, "anonymous", 60, 0, 1792180000, False, None)
    monkeypatch.setattr(gt.GithubToken, "status", lambda self: empty)
    r = client.post(f"/workspaces/{w}/skills/web/install", json={"identifier": "a/b/c"})
    assert r.status_code == 400
    assert "60 an hour" in r.text and "Settings" in r.text
    # Quota left: Hermes's own words, not a naming problem.
    left = gt.TokenStatus(False, "anonymous", 60, 30, 1792180000, False, None)
    monkeypatch.setattr(gt.GithubToken, "status", lambda self: left)
    r = client.post(f"/workspaces/{w}/skills/web/install", json={"identifier": "a/b/c"})
    assert "Could not find" in r.text and "name this skill" not in r.text


def test_a_scan_blocked_skill_installs_only_with_the_owners_install_anyway(
    env: Any, monkeypatch: Any
) -> None:
    """Hermes's scan blocks it: 423 with Hermes's finding; Install anyway runs
    Hermes's own --force (and nothing else)."""
    client, core, _fake, _tmp = env
    w = _ws(client)
    calls: list[list[str]] = []
    root = core.engine.profile_home(w)

    def hermes(self: Any, args: list[str], **_: Any) -> str:
        calls.append(args)
        if args[:2] == ["skills", "inspect"]:
            return "Name: replica-launch\nDescription: Writes the launch.\n"
        if "--force" not in args:
            raise sources.SourceError(
                "Not installed: the security scan found 1 high-risk pattern(s). Re-run with "
                '--force. Finding: HIGH injection listing.py:50 "U+200D (zero-width joiner)"'
            )
        folder = root / "skills" / "agos-library" / "replica-launch"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text(
            "---\nname: replica-launch\ndescription: Writes the launch.\n---\n\nSteps.\n"
        )
        return "Decision: ALLOWED (forced)\n"

    monkeypatch.setattr(sources.Sources, "_hermes", hermes)
    body = {"identifier": "Jakeschincariol/replica-skill/replica-launch"}
    blocked = client.post(f"/workspaces/{w}/skills/web/install", json=body)
    assert blocked.status_code == 423, blocked.text
    assert (
        "zero-width joiner" in blocked.text and "Not installed: Not installed" not in blocked.text
    )
    assert not [
        i for i in client.get(f"/workspaces/{w}/skills").json() if i["name"] == "replica-launch"
    ]
    forced = client.post(f"/workspaces/{w}/skills/web/install", json=body | {"force": True})
    assert forced.status_code == 201, forced.text
    installs = [a for a in calls if a[:2] == ["skills", "install"]]
    assert "--force" not in installs[0] and installs[-1][-1] == "--force"
    names = [i["name"] for i in client.get(f"/workspaces/{w}/skills").json()]
    assert "replica-launch" in names
