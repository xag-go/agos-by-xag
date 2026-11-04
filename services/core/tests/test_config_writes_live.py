"""engine.config_writes against the installed Hermes: several keys of one home in
ONE Hermes process (Hermes's own set_config_value / unset_config_value, as the CLI
runs them) leave the same config.yaml and .env as one `hermes config set --force`
per key. Scratch HOME and Hermes homes under the test's own folder (TMPDIR is
~/.hermes/cache/scratch), the install's runtime (HERMES_RUNTIME_DIR), and the
install's launcher is checked unchanged afterwards. Skipped without Hermes."""

import hashlib
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from agos_core.config import EngineConfig
from agos_core.engine.hermes import EngineError, HermesEngine

_SHIM = Path.home() / ".hermes" / "hermes-agent" / ".hermes" / "bin" / "hermes"
_TOOLS = Path.home() / ".hermes" / "tools"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _env_lines(home: Path) -> dict[str, str]:
    path = home / ".env"
    text = path.read_text() if path.is_file() else ""
    return dict(
        line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#")
    )


COMMANDS: list[tuple[str, ...]] = [
    ("config", "set", "--force", "compression.enabled", "false"),  # a bool
    ("config", "set", "--force", "agent.max_turns", "77"),  # an int
    ("config", "set", "--force", "skills.disabled", '["one", "two"]'),  # a list
    ("config", "set", "--force", "terminal.timeout", "321"),  # its .env mirror too
    ("config", "set", "--force", "AGOS_BATCH_FLAG", "on"),  # an UPPER key: the .env
    ("config", "set", "--force", "mcp_servers", '{"x": {"url": "http://127.0.0.1:9/mcp"}}'),
    ("config", "unset", "terminal.docker_image"),
]


def test_one_hermes_process_writes_what_one_cli_per_key_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()  # the real Hermes, not conftest's stand-in
    hermes = shutil.which("hermes")
    if not hermes or not _TOOLS.is_dir():
        pytest.skip("no Hermes install on this machine")
    shim = _sha(_SHIM)
    scratch = tmp_path / "s40-batch"
    try:
        engine = HermesEngine(
            EngineConfig(
                hermes_bin=hermes,
                docker_bin="docker",
                hermes_home=scratch / "shared",
                profile_prefix="agos-",
                sandbox_image="x",
                host_home=scratch / "home",
                roots_dir=scratch / "roots",
                runtime_dir=_TOOLS,
            ),
            egress=False,
        )
        (scratch / "home").mkdir(parents=True)
        cli_home, one_home = scratch / "cli", scratch / "one"
        from conftest import hermes_ready_home

        for home in (cli_home, one_home):
            home.mkdir()
            (home / "config.yaml").write_text("terminal:\n  docker_image: old:1\n")
            # A scratch HOME makes each home a data root of its own: Hermes would sync
            # its Python environment there first (minutes, past the 120 s calls).
            hermes_ready_home(home)

        def cli(home: Path, command: Sequence[str]) -> str:
            return engine.runner.run(
                [hermes, *command],
                timeout=120,
                env={**engine._env(), "HERMES_HOME": str(home)},
            )

        for command in COMMANDS:
            cli(cli_home, command)

        def never(command: Sequence[str]) -> str:
            raise AssertionError(f"the one process failed: {command} ran on its own")

        wrote = engine._config_writes(one_home, COMMANDS, {}, never)
        assert wrote == [c[-2] if c[1] == "set" else c[-1] for c in COMMANDS]
        assert yaml.safe_load((one_home / "config.yaml").read_text()) == yaml.safe_load(
            (cli_home / "config.yaml").read_text()
        )
        assert _env_lines(one_home) == _env_lines(cli_home)
        assert _env_lines(one_home)["AGOS_BATCH_FLAG"] == "on"
        held = yaml.safe_load((one_home / "config.yaml").read_text())
        assert held["compression"]["enabled"] is False and held["agent"]["max_turns"] == 77
        assert held["skills"]["disabled"] == ["one", "two"]

        # The same values again: Hermes holds them all, nothing is written.
        before = (one_home / "config.yaml").read_bytes(), (one_home / ".env").read_bytes()
        sets = [c for c in COMMANDS if c[1] == "set"]
        assert engine._config_writes(one_home, sets, {}, never) == []
        assert ((one_home / "config.yaml").read_bytes(), (one_home / ".env").read_bytes()) == before

        # A key the managed scope pins is refused, like the CLI (exit 1).
        managed = engine.settings.managed_home
        managed.mkdir(parents=True, exist_ok=True)
        (managed / "config.yaml").write_text("agent:\n  max_turns: 5\n")
        pinned = [("config", "set", "--force", "agent.max_turns", "9")]
        with pytest.raises(EngineError):
            cli(cli_home, pinned[0])
        with pytest.raises(EngineError):
            engine._config_writes(one_home, pinned, {}, never)
        assert yaml.safe_load((one_home / "config.yaml").read_text())["agent"]["max_turns"] == 77
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        assert _sha(_SHIM) == shim  # the install's launcher untouched
