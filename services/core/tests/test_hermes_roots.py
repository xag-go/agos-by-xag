"""One Hermes root per workspace (ADR 0020): layout, CLI environment, isolation
walls, General Settings reaching every root, backups."""

from __future__ import annotations

import json
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import MODEL, FakeRunner

from agos_core.api.app import create_app
from agos_core.config import ConfigError, EngineConfig, Settings, load_settings
from agos_core.engine.hermes import HermesEngine


@pytest.fixture
def roots_env(tmp_path: Path) -> Iterator[tuple[TestClient, FakeRunner, Path, Any]]:
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
            runtime_dir=hermes_home / "tools",
        ),
    )
    runner = FakeRunner(hermes_home)
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        app.state.core.engine.runner = runner
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, runner, tmp_path, app.state.core


def _new(client: TestClient, name: str = "Argan") -> str:
    r = client.post("/workspaces", json={"name": name, "defaultModel": MODEL})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_a_new_workspace_gets_its_own_root(roots_env: Any) -> None:
    client, runner, tmp, core = roots_env
    ws = _new(client)
    root = tmp / "data" / "hermes" / "agos-argan"
    assert (root / ".agos-root").is_file() and (root / "config.yaml").is_file()
    assert core.engine.profile_home(ws) == root
    assert core.engine.hermes_name(ws) == "default"
    # Nothing of it in the shared home.
    assert not (tmp / "home" / ".hermes" / "profiles" / "agos-argan").exists()
    # Every Hermes call ran IN the root, with the install's runtime (never `-p`).
    assert runner.envs and all(e["HERMES_HOME"] == str(root) for e in runner.envs)
    assert all(
        e["HERMES_RUNTIME_DIR"] == str(tmp / "home" / ".hermes" / "tools") for e in runner.envs
    )
    config = runner.config["agos-argan"]
    assert config["gateway.standalone"] == "false"  # the root's gateway is its host
    assert config["terminal.docker_shared_container_key"] == "agos-argan"
    assert "API_SERVER_KEY=" in (root / ".env").read_text()


def test_members_live_under_the_root_and_never_elsewhere(roots_env: Any) -> None:
    client, runner, tmp, core = roots_env
    ws = _new(client)
    engine = core.engine
    member = f"{ws}--a-writer"
    assert engine.ensure_profile(member) is True
    root = tmp / "data" / "hermes" / "agos-argan"
    assert engine.profile_home(member) == root / "profiles" / "a-writer"
    assert (root / "profiles" / "a-writer" / "config.yaml").is_file()
    create = [c for c in runner.calls if c[1:3] == ["profile", "create"]]
    assert create[-1][3] == "a-writer" and "--no-alias" in create[-1]
    assert engine.own_profiles(ws) == ["agos-argan", "agos-argan--a-writer"]
    assert engine.hermes_name(member) == "a-writer"
    assert engine.home_of("agos-argan--a-writer") == root / "profiles" / "a-writer"
    assert engine.home_in(ws, "a-writer") == root / "profiles" / "a-writer"
    assert engine.home_in(ws, "default") == root
    # Each profile's sandboxes carry their own label: never "default" twice.
    other = _new(client, "Bees")
    assert engine.sandbox_label(ws) != engine.sandbox_label(other)
    assert not engine.sandbox_label(ws).startswith("default")


def test_kanban_dispatch_names_hermes_profiles_of_the_root(roots_env: Any) -> None:
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    from agos_core.actions import agent_profiles

    core.engine.ensure_profile(f"{ws}--a-writer")
    # Hermes's Kanban names profiles as the root knows them; a member profile in the
    # root is on the team (the team is the root's profiles).
    assert json.loads(agent_profiles.dispatch_list(core, ws)) == ["default", "a-writer"]
    assert core.engine.hermes_name(f"{ws}--a-writer") == "a-writer"
    assert agent_profiles.board_db(core, ws) == core.engine.root(ws) / "kanban.db"
    assert ("argan", "writer") in agent_profiles.existing(core, ws)


def test_a_workspace_still_in_the_shared_home_is_never_run_from_it(roots_env: Any) -> None:
    """Roots are the only layout: a workspace whose profile is still in the shared
    home is never run from there, and no fresh root is made over it (it must be
    moved with agos_core.migrate_root first)."""
    _client, runner, tmp, core = roots_env
    from agos_core.engine.hermes import EngineError

    legacy = tmp / "home" / ".hermes" / "profiles" / "agos-old"
    legacy.mkdir(parents=True)
    (legacy / "config.yaml").write_text("{}\n")
    root = tmp / "data" / "hermes" / "agos-old"
    assert core.engine.profile_home("old") == root
    assert core.engine.hermes_name("old") == "default"
    assert core.engine.legacy_home("old") == legacy  # what migrate_root reads
    with pytest.raises(EngineError, match="migrate_root"):
        core.engine.ensure_profile("old")
    assert not root.exists() and not [c for c in runner.calls if "-p" in c]
    # Once migrated (the root carries AGOS's marker), AGOS runs it.
    root.mkdir(parents=True)
    (root / ".agos-root").write_text("{}")
    assert not core.engine.not_migrated("old")


def test_the_roots_folder_is_never_mountable(roots_env: Any) -> None:
    client, _runner, tmp, _core = roots_env
    ws = _new(client)
    for path in (tmp / "data" / "hermes", tmp / "data" / "hermes" / "agos-argan"):
        r = client.post(f"/workspaces/{ws}/folders", json={"path": str(path)})
        assert r.status_code == 400, path


def test_roots_config_is_checked() -> None:
    base = {
        "AGOS_DATA_DIR": "/srv/agos-data",
        "AGOS_ENGINE": "hermes",
        "AGOS_HERMES_BIN": "/bin/true",
        "AGOS_DOCKER_BIN": "/bin/true",
        "HOME": "/home/x",
    }
    engine = load_settings(base).engine
    assert engine is not None and engine.roots_dir == Path("/srv/agos-data/hermes")
    assert engine.runtime_dir == Path("/home/x/.hermes/tools")
    assert engine.runtime_env() == {
        "HERMES_RUNTIME_DIR": "/home/x/.hermes/tools",
        # Hermes's managed scope beside the roots (actions/hermes_managed.py).
        "HERMES_MANAGED_DIR": str(engine.roots_dir.parent / "hermes-managed"),
    }
    with pytest.raises(ConfigError):  # the shared-home layout is gone (ADR 0020)
        load_settings(base | {"AGOS_HERMES_ROOTS": "off"})
    with pytest.raises(ConfigError):  # Hermes maps homes under ~/.hermes back to it
        load_settings(base | {"AGOS_HERMES_ROOTS": "/home/x/.hermes/roots"})
    with pytest.raises(ConfigError):
        load_settings(base | {"AGOS_HERMES_GATEWAY_SUPERVISOR": "cron"})


# ---- General Settings → every root (the owner's requirement) ----------------------


def _shared_env(tmp: Path, **values: str) -> None:
    (tmp / "home" / ".hermes" / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def _env_of(home: Path) -> dict[str, str]:
    out = {}
    for line in (home / ".env").read_text().splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


def test_a_general_key_reaches_every_root_and_member(roots_env: Any) -> None:
    client, _runner, tmp, core = roots_env
    from agos_core.actions import general_sync

    _shared_env(tmp, OPENROUTER_API_KEY="sk-or-one", TELEGRAM_BOT_TOKEN="not-general")
    a, b = _new(client, "Argan"), _new(client, "Bees")
    core.engine.ensure_profile(f"{a}--a-writer")
    general_sync.sync(core)
    homes = [core.engine.root(a), core.engine.root(b), core.engine.profile_home(f"{a}--a-writer")]
    for home in homes:
        env = _env_of(home)
        assert env["OPENROUTER_API_KEY"] == "sk-or-one", home
        assert "TELEGRAM_BOT_TOKEN" not in env  # never a profile's own line
    # Changed once in General Settings → every root has the new one.
    _shared_env(tmp, OPENROUTER_API_KEY="sk-or-two")
    general_sync.sync(core)
    assert all(_env_of(h)["OPENROUTER_API_KEY"] == "sk-or-two" for h in homes)
    # Removed in General Settings → AGOS's copies go.
    _shared_env(tmp)
    general_sync.sync(core)
    assert all("OPENROUTER_API_KEY" not in _env_of(h) for h in homes)


def test_a_new_workspace_gets_the_general_keys_at_once(roots_env: Any) -> None:
    client, _runner, tmp, core = roots_env
    _shared_env(tmp, GEMINI_API_KEY="gem-key-123")
    ws = _new(client)  # its sync writes them, no separate step
    assert _env_of(core.engine.root(ws))["GEMINI_API_KEY"] == "gem-key-123"


def test_a_workspace_own_value_wins(roots_env: Any) -> None:
    client, _runner, tmp, core = roots_env
    from agos_core.actions import general_sync
    from agos_core.engine import envfile

    ws = _new(client)
    root = core.engine.root(ws)
    envfile.rewrite(root / ".env", ("OPENAI_API_KEY=",), ["OPENAI_API_KEY=workspace-own"])
    _shared_env(tmp, OPENAI_API_KEY="general-one")
    general_sync.sync(core)
    assert _env_of(root)["OPENAI_API_KEY"] == "workspace-own"
    _shared_env(tmp)  # and removing the general one never removes the workspace's own
    general_sync.sync(core)
    assert _env_of(root)["OPENAI_API_KEY"] == "workspace-own"


def test_saving_a_key_in_general_settings_writes_every_root(
    roots_env: Any, monkeypatch: Any
) -> None:
    client, _runner, tmp, core = roots_env
    from agos_core.engine import provider_keys
    from agos_core.engine.provider_keys import KeyCheck

    a, b = _new(client, "Argan"), _new(client, "Bees")
    monkeypatch.setattr(provider_keys.ProviderKeys, "check", lambda *_a, **_k: KeyCheck(True, "ok"))

    def save(self: Any, name: str, key: str) -> None:  # save_provider_env_credential
        _shared_env(tmp, **{name: key})

    monkeypatch.setattr(provider_keys.ProviderKeys, "save_env", save)
    from agos_core.actions.services.settings import model_catalog

    row = {
        "id": "openrouter",
        "name": "OpenRouter",
        "cli": {"tool": "AGOS", "installed": False, "account": None, "loginCommand": "x"},
        "api": {"last4": "", "status": "", "statusAt": "", "problem": ""},
        "apiKey": True,
        "keyEnvs": ["OPENROUTER_API_KEY"],  # Hermes's own name (read with the catalog)
    }

    def catalog(_core: Any, _refresh: bool) -> dict[str, Any]:
        return {"catalog": [], "providers": [row]}

    monkeypatch.setattr(model_catalog, "load", catalog)
    r = client.put("/models/providers/openrouter/key", json={"key": "sk-or-key-9876"})
    assert r.status_code == 200, r.text
    for ws in (a, b):
        assert _env_of(core.engine.root(ws))["OPENROUTER_API_KEY"] == "sk-or-key-9876"
    # The key's end is read from Hermes's .env, how it did from Hermes's credential
    # pool (a root's: General Settings copied the key there); AGOS keeps nothing.
    [shown] = client.get("/models/providers").json()
    assert shown["api"]["last4"] == "9876" and shown["api"]["status"] == ""
    pool: dict[str, Any] = {"source": "env:OPENROUTER_API_KEY", "last_status": "exhausted"}
    pool |= {"last_status_at": 1790000000.0, "last_error_message": "402 out of credits"}
    (core.engine.root(a) / "auth.json").write_text(
        json.dumps({"credential_pool": {"openrouter": [pool]}})
    )
    [shown] = client.get("/models/providers").json()
    assert shown["api"]["status"] == "exhausted" and shown["api"]["statusAt"].startswith("2026")
    assert shown["api"]["problem"] == "402 out of credits"
    assert not core.db.execute("SELECT 1 FROM app_settings WHERE key = 'provider_keys'").fetchone()
    _shared_env(tmp, OPENROUTER_API_KEY="sk-or-key-5555")  # changed in Hermes
    assert client.get("/models/providers").json()[0]["api"]["last4"] == "5555"


def test_login_state_says_when_a_root_needs_its_own_login(roots_env: Any) -> None:
    client, _runner, _tmp, core = roots_env
    from agos_core.actions import general_sync

    ws = _new(client)
    root = core.engine.root(ws)
    (root / "config.yaml").write_text("model:\n  provider: anthropic\n  default: claude\n")
    state = general_sync.login_state(core, ws)
    assert state["root"] and state["needsLogin"] and state["provider"] == "anthropic"
    (root / "auth.json").write_text(json.dumps({"credential_pool": {"anthropic": [{"id": 1}]}}))
    assert not general_sync.login_state(core, ws)["needsLogin"]


def test_a_backup_holds_each_root_as_hermes_backup(
    roots_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _runner, _tmp, core = roots_env
    from agos_core.actions import backups

    # Hermes's own list of credential stores (test_backup asks the real one).
    monkeypatch.setattr(backups, "hermes_private", lambda core: lambda parts: [False] * len(parts))

    ws = _new(client)
    assert (
        client.put("/backups/password", json={"password": "a-long-password-1"}).status_code == 204
    )
    made = backups.run_backup(core)
    from agos_core.engine import backup as bk

    target = Path(_tmp) / "restored"
    manifest = bk.restore(backups.backup_dir(core) / made.name, "a-long-password-1", target)
    name = core.engine.profile(ws)
    assert f"hermes/roots/{name}.zip" in manifest.files
    assert bk.root_zip_problems(target / f"hermes/roots/{name}.zip", name) == []
    # The root itself is not walked as AGOS data (its runtime and caches are no data).
    assert not any(f.startswith("agos-data/hermes/") for f in manifest.files)


def _own_zone(home: Path) -> str:
    """A home's own `timezone` line (none: Hermes's managed scope holds it)."""
    from agos_core.engine import config_file

    return str(config_file.read(home).get("timezone") or "")


def config_file_zone(core: Any) -> Any:
    return core.engine.managed_config().get("timezone")


def test_the_owner_timezone_is_hermes_own_setting_in_every_home(roots_env: Any) -> None:
    client, runner, tmp, core = roots_env

    a, b = _new(client, "Argan"), _new(client, "Bees")
    core.engine.ensure_profile(f"{a}--a-writer")
    shared = tmp / "home" / ".hermes"
    homes = [shared, core.engine.root(a), core.engine.root(b)]
    homes.append(core.engine.profile_home(f"{a}--a-writer"))
    assert client.put("/preferences/timezone", json={"timezone": "Mars/Base"}).status_code == 400
    r = client.put("/preferences/timezone", json={"timezone": "Africa/Casablanca"})
    assert r.status_code == 200, r.text
    # Written once with Hermes's own `config set`, into its managed scope (every
    # home reads it); no home keeps a copy, nor does AGOS.
    assert config_file_zone(core) == "Africa/Casablanca"
    assert ["/bin/hermes", "config", "set", "--force", "timezone", "Africa/Casablanca"] in (
        runner.calls
    )
    for home in homes:
        assert _own_zone(home) == "", home
    assert (
        core.db.execute(
            "SELECT COUNT(*) FROM app_settings WHERE value LIKE '%Casablanca%'"
        ).fetchone()[0]
        == 0
    )
    assert client.get("/preferences/timezone").json() == {"timezone": "Africa/Casablanca"}
    # Each workspace profile's sandbox gets it as TZ (Hermes passes only
    # terminal.docker_env into the container); the shared home has no sandbox.
    from agos_core.engine import config_file

    def sandbox_tz(home: Path) -> Any:
        env = config_file.get(config_file.read(home), "terminal.docker_env")
        return env.get("TZ") if isinstance(env, dict) else None

    assert all(sandbox_tz(h) == "Africa/Casablanca" for h in homes[1:]), homes
    assert sandbox_tz(shared) is None
    # A new workspace's root reads it too; its sandbox gets TZ.
    c = _new(client, "Cedar")
    assert sandbox_tz(core.engine.root(c)) == "Africa/Casablanca"
    # Cleared: Hermes's own `config unset` (server-local time) in the scope.
    assert client.put("/preferences/timezone", json={"timezone": ""}).status_code == 200
    assert config_file_zone(core) is None
    assert all(_own_zone(h) == "" for h in [*homes, core.engine.root(c)])
    assert all(sandbox_tz(h) is None for h in homes[1:])
    assert client.get("/preferences/timezone").json() == {"timezone": ""}


def test_a_gateway_still_exiting_is_waited_for_before_the_next_starts(tmp_path: Path) -> None:
    """Newer Hermes refuses `gateway run --replace` for a process its pid record no
    longer names: AGOS lets a stopped gateway finish exiting first."""
    import subprocess
    import sys
    import time

    from conftest import hermes_gateway_status

    engine = types.SimpleNamespace(
        gateway_status=lambda home, fresh=False: hermes_gateway_status(home)
    )
    engine._gateway_up = lambda home: HermesEngine._gateway_up(engine, home)  # type: ignore[arg-type]
    wait_gone = HermesEngine._wait_gone

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)", "gateway"])
    (tmp_path / "gateway_state.json").write_text(
        json.dumps({"pid": proc.pid, "gateway_state": "stopped"})
    )
    started = time.monotonic()
    reaper = __import__("threading").Thread(target=proc.wait, daemon=True)
    reaper.start()
    wait_gone(engine, tmp_path, wait_s=10)  # type: ignore[arg-type]
    assert proc.poll() is not None and time.monotonic() - started >= 1.0
    # A running one is never waited for.
    (tmp_path / "gateway_state.json").write_text(json.dumps({"pid": 1, "gateway_state": "running"}))
    started = time.monotonic()
    wait_gone(engine, tmp_path, wait_s=10)  # type: ignore[arg-type]
    assert time.monotonic() - started < 1.0
