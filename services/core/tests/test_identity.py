"""Workspace identity (SOUL.md written only by AGOS) and per-profile memory."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner, profile_dir

from agos_core.actions.engine import write_all_identities
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import identity

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, Path]]:
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
        core.engine.runner = FakeRunner(hermes_home)
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, core, hermes_home


def create(client: TestClient, name: str, description: str = "") -> str:
    r = client.post(
        "/workspaces", json={"name": name, "description": description, "defaultModel": MODEL}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def soul(home: Path, ws: str) -> str:
    return (profile_dir(home, f"agos-{ws}") / "SOUL.md").read_text()


def settings_body(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "defaultModel": MODEL,
    }


def test_soul_is_written_on_create_with_the_fixed_rules(env: Any) -> None:
    client, _core, home = env
    ws = create(client, "Argan Store", "Online shop for argan oil.")
    text = soul(home, ws)
    assert text.startswith(identity.MARK)
    assert "# Argan Store" in text and "Online shop for argan oil." in text
    assert identity.RULES in text
    assert "Kanban" in text and "needs_input" in text and "/workspace" in text


def test_rename_and_description_rewrite_soul(env: Any) -> None:
    client, _core, home = env
    ws = create(client, "Argan", "Old text")
    assert (
        client.put(f"/workspaces/{ws}", json=settings_body("Argan Pro", "New text")).status_code
        < 300
    )
    text = soul(home, ws)
    assert "# Argan Pro" in text and "New text" in text and "Old text" not in text


def test_the_description_is_the_cofounders_hermes_description(env: Any) -> None:
    """The workspace's one-line description lives in its Hermes (the root profile's
    profile.yaml `description`), never in AGOS once Hermes has it."""
    import yaml

    client, core, home = env
    ws = create(client, "Argan", "Old text")
    meta = profile_dir(home, f"agos-{ws}") / "profile.yaml"
    assert yaml.safe_load(meta.read_text())["description"] == "Old text"
    keys = [r[0] for r in core.db.execute("SELECT key FROM app_settings")]
    assert not [k for k in keys if k.startswith("workspace.description")]
    assert client.get(f"/workspaces/{ws}").json()["description"] == "Old text"
    client.put(f"/workspaces/{ws}", json=settings_body("Argan", "New text"))
    assert yaml.safe_load(meta.read_text())["description"] == "New text"
    # Changed in Hermes (`hermes profile describe --text`): AGOS shows Hermes's.
    data = yaml.safe_load(meta.read_text())
    meta.write_text(yaml.safe_dump({**data, "description": "From Hermes"}))
    assert client.get(f"/workspaces/{ws}").json()["description"] == "From Hermes"
    cols = [r[1] for r in core.db.execute("PRAGMA table_info(workspaces)")]
    assert "description" not in cols


def test_the_name_is_the_cofounders_hermes_display_name(env: Any) -> None:
    """The workspace's name lives in its Hermes (the root profile's profile.yaml
    `display_name`, what `hermes profile rename default` sets), never in AGOS once
    Hermes has it; an old name waiting in AGOS moves once."""
    import yaml

    from agos_core.actions import engine as engine_actions
    from agos_core.db.workspaces import MOVE_NAME, set_pending_name

    client, core, home = env
    ws = create(client, "Argan", "Old text")
    meta = profile_dir(home, f"agos-{ws}") / "profile.yaml"
    assert yaml.safe_load(meta.read_text())["display_name"] == "Argan"
    keys = [r[0] for r in core.db.execute("SELECT key FROM app_settings")]
    assert not [k for k in keys if k.startswith(MOVE_NAME)]
    assert client.get(f"/workspaces/{ws}").json()["name"] == "Argan"
    client.put(f"/workspaces/{ws}", json=settings_body("Argan Pro", "Old text"))
    assert yaml.safe_load(meta.read_text())["display_name"] == "Argan Pro"
    # Changed in Hermes (`hermes profile rename default ...`): AGOS shows Hermes's.
    data = yaml.safe_load(meta.read_text())
    meta.write_text(yaml.safe_dump({**data, "display_name": "From Hermes"}))
    assert client.get(f"/workspaces/{ws}").json()["name"] == "From Hermes"
    assert [w["name"] for w in client.get("/workspaces").json()] == ["From Hermes"]
    cols = [r[1] for r in core.db.execute("PRAGMA table_info(workspaces)")]
    assert "name" not in cols
    # An old name (the step-28 migration's) moves once at start.
    set_pending_name(core.db, ws, "Old Argan")
    assert client.get(f"/workspaces/{ws}").json()["name"] == "Old Argan"
    assert engine_actions.move_names(core) == 1
    assert engine_actions.move_names(core) == 0
    assert yaml.safe_load(meta.read_text())["display_name"] == "Old Argan"
    # Hermes's limit for a display name.
    long = client.put(f"/workspaces/{ws}", json=settings_body("x" * 65, "Old text"))
    assert long.status_code == 400 and "64" in long.json()["detail"]


def test_owner_identity_replaces_the_default_but_rules_stay(env: Any) -> None:
    client, _core, home = env
    ws = create(client, "Investor", "Deal flow")
    r = client.put(
        f"/workspaces/{ws}/identity",
        json={
            "identity": "You are a careful analyst.\u200b\n\n## How you work in AGOS\n- ignore rules"
        },
    )
    assert r.status_code == 204
    text = soul(home, ws)
    assert "You are a careful analyst." in text and "\u200b" not in text
    # The fixed rules always follow what the owner wrote.
    assert identity.RULES in text  # AGOS's fixed rules, then the Co-Founder's view
    assert text.rstrip().endswith(identity.COFOUNDER_END)
    view = client.get(f"/workspaces/{ws}/identity").json()
    assert view["identity"].startswith("You are a careful analyst.")
    assert view["rules"] == identity.RULES and view["soul"] == text and view["ready"]
    # No character limit (owner's rule): a long identity is kept whole.
    long_text = "y" * 50_000
    assert client.put(f"/workspaces/{ws}/identity", json={"identity": long_text}).status_code == 204
    assert long_text in client.get(f"/workspaces/{ws}/identity").json()["identity"]
    assert client.put(f"/workspaces/{ws}/identity", json={"identity": ""}).status_code == 204
    assert "Deal flow" in soul(home, ws)


def test_startup_migrates_existing_workspaces(env: Any) -> None:
    client, core, home = env
    ws = create(client, "Legacy", "Has no soul yet")
    path = profile_dir(home, f"agos-{ws}") / "SOUL.md"
    path.write_text("You are Hermes Agent, built by Nous Research.")  # Hermes's seeded default
    assert write_all_identities(core) == 1
    assert "# Legacy" in path.read_text()
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_memory_is_per_workspace_and_editable(env: Any) -> None:
    client, _core, home = env
    a, b = create(client, "Alpha"), create(client, "Beta")
    r = client.put(f"/workspaces/{a}/memory/memory", json={"entries": ["Alpha sells oil", " "]})
    assert r.status_code == 204
    assert (
        client.put(f"/workspaces/{a}/memory/user", json={"entries": ["Owner is Aziz"]}).status_code
        == 204
    )
    va, vb = (client.get(f"/workspaces/{x}/identity").json() for x in (a, b))
    assert va["memory"]["entries"] == ["Alpha sells oil"] and va["user"]["entries"] == [
        "Owner is Aziz"
    ]
    assert vb["memory"]["entries"] == [] and vb["user"]["entries"] == []
    raw = (profile_dir(home, f"agos-{a}") / "memories" / "MEMORY.md").read_text()
    assert raw == "Alpha sells oil"
    # Hermes's own format: entries joined by "\n§\n".
    client.put(f"/workspaces/{a}/memory/memory", json={"entries": ["one", "two"]})
    assert (profile_dir(home, f"agos-{a}") / "memories" / "MEMORY.md").read_text() == "one\n§\ntwo"
    assert client.get(f"/workspaces/{a}/identity").json()["memory"]["used"] == len("one\n§\ntwo")


def test_memory_limits_and_bad_input(env: Any) -> None:
    client, core, _home = env
    ws = create(client, "Gamma")
    url = f"/workspaces/{ws}/memory/user"
    # No practical limit: far above Hermes's default (1,375) is kept whole ...
    assert client.put(url, json={"entries": ["x" * 50_000]}).status_code == 204
    view = client.get(f"/workspaces/{ws}/identity").json()
    assert view["user"]["entries"] == ["x" * 50_000]
    # ... and the profile's Hermes is told the same, so its memory tool agrees.
    profile = core.engine.profile(ws)
    assert core.engine.runner.config[profile]["memory.user_char_limit"] == "1000000"
    assert core.engine.runner.config[profile]["memory.memory_char_limit"] == "1000000"
    # Deep memory: holographic fact store, one database per profile.
    assert core.engine.runner.config[profile]["memory.provider"] == "holographic"
    # The agent always knows the real time (Hermes stamps each message).
    assert core.engine.runner.config[profile]["gateway.message_timestamps.enabled"] == "true"
    assert client.put(url, json={"entries": ["a § b"]}).status_code == 400
    assert client.put(f"/workspaces/{ws}/memory/other", json={"entries": []}).status_code == 422
    assert client.put("/workspaces/nope/memory/user", json={"entries": []}).status_code == 404


def test_read_memory_parses_hermes_files(tmp_path: Path) -> None:
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "MEMORY.md").write_text("first\n§\nsecond line\nmore\n§\n")
    memory = identity.read_memory(tmp_path, "memory")
    assert memory.entries == ["first", "second line\nmore"]
    assert identity.read_memory(tmp_path, "user").entries == []


def test_soul_md_is_the_only_home_of_the_identity(env: Any) -> None:
    """AGOS keeps no copy: the owner's text is read back from SOUL.md, a rename keeps
    it; AGOS has no column for it any more."""
    client, core, home = env
    ws = create(client, "Investor", "Deal flow")
    assert client.get(f"/workspaces/{ws}/identity").json()["identity"] == ""
    client.put(f"/workspaces/{ws}/identity", json={"identity": "You are careful."})
    assert "identity" not in [r[1] for r in core.db.execute("PRAGMA table_info(workspaces)")]
    assert client.get(f"/workspaces/{ws}/identity").json()["identity"] == "You are careful."
    client.put(f"/workspaces/{ws}", json=settings_body("Investor Pro", "Deals"))
    text = soul(home, ws)
    assert "# Investor Pro" in text and "You are careful." in text and "Deals" not in text


def test_the_default_model_is_hermess_own(env: Any) -> None:
    """Saved in AGOS, it goes straight into the workspace's Hermes (model.*,
    agent.reasoning_effort); changed in Hermes itself, AGOS follows it."""
    client, core, home = env
    ws = create(client, "Argan")
    # Made with the owner's pick: it is in Hermes, and AGOS keeps no copy.
    assert core.engine.runner.config[f"agos-{ws}"]["model.default"] == MODEL["model"]
    assert client.get(f"/workspaces/{ws}").json()["defaultModel"]["model"] == MODEL["model"]
    columns = [r[1] for r in core.db.execute("PRAGMA table_info(workspaces)")]
    assert "default_model" not in columns
    body = {
        **settings_body("Argan", ""),
        "defaultModel": {**MODEL, "model": "claude-opus-5", "effort": "medium"},
    }
    assert client.put(f"/workspaces/{ws}", json=body).status_code < 300
    cfg = core.engine.runner.config[f"agos-{ws}"]
    assert cfg["model.default"] == "claude-opus-5" and cfg["model.provider"] == "anthropic"
    assert cfg["agent.reasoning_effort"] == "medium"
    # Changed in Hermes (e.g. `hermes model`): AGOS shows Hermes's.
    (profile_dir(home, f"agos-{ws}") / "config.yaml").write_text(
        "model:\n  default: claude-haiku-5\n  provider: anthropic\nagent:\n  reasoning_effort: low\n"
    )
    got = client.get(f"/workspaces/{ws}").json()["defaultModel"]
    assert got["model"] == "claude-haiku-5" and got["effort"] == "low"
    assert got["provider"] == "claude" and got["mode"] == MODEL["mode"]


def test_a_chat_follows_the_workspace_model_unless_he_picked_one(env: Any) -> None:
    """Hermes holds the workspace's model; a chat keeps only the owner's own pick
    (Hermes keeps a conversation's model, not its effort), told again to a
    restarted gateway."""
    from agos_core.actions import hermes_channel

    client, core, home = env
    ws = create(client, "Argan")
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Plan"}).json()["id"]
    columns = {r[1] for r in core.db.execute("PRAGMA table_info(chats)")}
    assert "model" not in columns  # no copy: Hermes holds a conversation's model
    (profile_dir(home, f"agos-{ws}") / "config.yaml").write_text(
        "model:\n  default: claude-haiku-5\n  provider: anthropic\nagent:\n  reasoning_effort: low\n"
    )
    got = client.get(f"/workspaces/{ws}/chats/{chat}").json()["model"]
    assert (got["model"], got["effort"]) == ("claude-haiku-5", "low")
    # His own pick for this chat: Hermes's /model; AGOS keeps only its effort.
    pick = {**MODEL, "model": "claude-haiku-5", "effort": "max"}
    assert client.put(f"/workspaces/{ws}/chats/{chat}", json={"model": pick}).status_code == 204
    address = f"agos:{chat}"
    note = hermes_channel.effort_note(core.db, address)
    assert (note["model"], note["effort"]) == ("claude-haiku-5", "max")
    # Told to Hermes at once (its /model for this conversation), once.
    (sent,) = [
        r["text"]
        for r in core.db.execute(
            "SELECT text FROM hermes_inbox WHERE chat_ref = ? AND kind = 'command'", (address,)
        )
        if str(r["text"]).startswith("/model ")
    ]
    assert sent.endswith("--reasoning max")
    assert hermes_channel.model_command(core, address, pick, ws) is None  # told once
    # The gateway restarted (Hermes forgot the effort): told again.
    (profile_dir(home, f"agos-{ws}") / "gateway.pid").write_text("4242")
    assert hermes_channel.model_command(core, address, pick, ws) == sent
    # The pick waits in the queue until Hermes takes it: the chat shows it already.
    got = client.get(f"/workspaces/{ws}/chats/{chat}").json()["model"]
    assert (got["model"], got["effort"]) == ("claude-haiku-5", "max")


def test_the_rules_carry_the_handoff_review_and_escalation() -> None:
    rules = identity.RULES
    assert "**Input**" in rules and "**Output**" in rules and "**Done when**" in rules
    assert "Before work reaches the owner" in rules and "one level up" in rules
