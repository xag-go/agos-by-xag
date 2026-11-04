"""The MCP address rule at connect time: when AGOS writes a workspace's servers into
Hermes's config, and again when the root's gateway starts (Hermes connects from this
machine, so a private address there reaches this computer's own services)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_library import env as env
from test_library import ws

from agos_core.config import EngineConfig
from agos_core.engine.hermes import HermesEngine
from agos_core.security import mcp_address


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {"wiki.example.com": ["93.184.216.34"], "rebound.example.com": ["10.0.0.7"]}
    monkeypatch.setattr(mcp_address, "resolve_host", lambda host, **_: table.get(host))


def test_a_private_server_in_hermes_config_is_written_switched_off(env: Any) -> None:
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    runner.config[f"agos-{a}"]["mcp_servers"] = json.dumps(
        {
            "wiki": {"url": "https://wiki.example.com/mcp"},
            "lan": {"url": "http://127.0.0.1:9000/mcp"},
            "rebound": {"url": "https://rebound.example.com/mcp"},
        }
    )
    runner._write_yaml(f"agos-{a}")
    from agos_core.actions.library import apply_workspace

    (core.engine.profile_home(a) / ".agos-connectors").unlink()
    assert apply_workspace(core, a) is None
    servers = json.loads(runner.config[f"agos-{a}"]["mcp_servers"])
    assert servers["wiki"].get("enabled", True) is not False
    assert servers["lan"]["enabled"] is False
    assert servers["rebound"]["enabled"] is False


def _engine(tmp_path: Path) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/false",
            docker_bin="/bin/false",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
            gateway_supervisor="spawn",
        ),
        egress=False,
    )


def _config(home: Path, servers: dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump({"model": "x", "mcp_servers": servers}))


def test_the_gateway_start_switches_off_private_servers_in_every_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    root = engine.root("w1")
    relay = {"url": "http://127.0.0.1:41000/mcp", "headers": mcp_address.relay_header("files")}
    _config(
        root,
        {
            "wiki": {"url": "https://wiki.example.com/mcp"},
            "meta": {"url": "http://169.254.169.254/latest"},
            "files": {**relay, "agos": {"command": "npx files"}},
        },
    )
    _config(root / "profiles" / "a-writer", {"shell": {"command": "bash", "args": ["-c", "x"]}})
    writes: list[tuple[str, list[list[str]]]] = []

    def record(key: str, commands: Any) -> list[str]:
        writes.append((key, [list(c) for c in commands]))
        return []

    monkeypatch.setattr(engine, "config_writes", record)
    monkeypatch.setattr(engine, "is_running", lambda workspace_id: True)
    engine.start("w1")
    by_key = {key: commands for key, commands in writes}
    assert set(by_key) == {"w1", "w1--a-writer"}
    (command,) = by_key["w1"]
    assert command[:4] == ["config", "set", "--force", "mcp_servers"]
    written = json.loads(command[4])
    assert written["meta"]["enabled"] is False
    assert "enabled" not in written["wiki"] and "enabled" not in written["files"]
    (member,) = by_key["w1--a-writer"]
    assert json.loads(member[4])["shell"]["enabled"] is False


def test_a_clean_root_starts_without_any_config_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    _config(engine.root("w1"), {"wiki": {"url": "https://wiki.example.com/mcp"}})
    writes: list[str] = []

    def record(key: str, commands: Any) -> list[str]:
        writes.append(key)
        return []

    monkeypatch.setattr(engine, "config_writes", record)
    monkeypatch.setattr(engine, "is_running", lambda workspace_id: True)
    engine.start("w1")
    assert writes == []


def test_the_gateway_does_not_start_when_a_private_server_cannot_be_switched_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.hermes_gateway.errors import EngineError

    engine = _engine(tmp_path)
    _config(engine.root("w1"), {"lan": {"url": "http://10.0.0.5/mcp"}})

    def refuse(key: str, commands: Any) -> list[str]:
        raise EngineError("Hermes refused")

    monkeypatch.setattr(engine, "config_writes", refuse)
    monkeypatch.setattr(engine, "is_running", lambda workspace_id: True)
    with pytest.raises(EngineError, match="MCP"):
        engine.start("w1")


def test_the_relay_header_is_the_one_agos_writes() -> None:
    from agos_core.actions import mcp_relays

    for name in ("files", "app-google", "my.server"):
        assert mcp_address.relay_header(name) == mcp_relays.header(name)


def test_testing_a_server_checks_the_address_hermes_connects_to(env: Any) -> None:
    # `hermes mcp test` runs on this machine and uses the entry's own URL (hermes_cli/
    # mcp_config.py cmd_mcp_test: "url" wins), not AGOS's part of it: an entry marked
    # local whose URL is not the relay's loopback is refused before Hermes connects.
    from test_library import mcp

    client, core, runner, _home = env
    a = ws(client, "Alpha")
    mid = mcp(client, a, "wiki", {"url": "https://wiki.example.com/mcp"})
    runner.config[f"agos-{a}"]["mcp_servers"] = json.dumps(
        {"wiki": {"url": "http://10.0.0.7/mcp", "agos": {"command": "npx wiki-mcp"}}}
    )
    runner._write_yaml(f"agos-{a}")
    asked: list[tuple[str, ...]] = []

    def hermes(workspace_id: str, *args: str, timeout: float = 60) -> str:
        asked.append(args)
        return "  ✓ Connected (1ms)\n"

    core.engine.walled_cli = hermes
    got = client.post(f"/workspaces/{a}/mcp/{mid}/test").json()
    assert asked == []
    assert got["ok"] is False and got["error"].startswith("Not tested: this server")
