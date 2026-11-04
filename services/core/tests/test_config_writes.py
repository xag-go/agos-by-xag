"""engine.config_writes: a home's `hermes config set/unset` commands in ONE Hermes
process (Hermes's own writer; the real one: test_config_writes_live.py), a value
the home already holds skipped, a refused key raised like the CLI's, and one CLI
per command when that process can't run."""

from pathlib import Path

import pytest
from conftest import hermes_config_batch
from test_engine_sync import FakeRunner

from agos_core.config import EngineConfig
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError, HermesEngine


def _engine(tmp_path: Path) -> tuple[HermesEngine, FakeRunner, Path]:
    home = tmp_path / ".hermes"
    home.mkdir()
    runner = FakeRunner(home)
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
    )
    profile = engine.profile_home("a")
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("{}\n")
    return engine, runner, profile


COMMANDS = [
    ("config", "set", "--force", "skills.disabled", '["x"]'),
    ("config", "set", "--force", "agent.max_turns", "7"),
    ("config", "set", "--force", "AGOS_FLAG", "on"),
    ("config", "unset", "plugins.enabled"),
]


def _config_clis(runner: FakeRunner) -> list[list[str]]:
    return [c for c in runner.calls if c[1:2] == ["config"] or c[3:4] == ["config"]]


def test_a_homes_keys_are_written_by_one_hermes_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, runner, home = _engine(tmp_path)
    starts = hermes_config_batch(monkeypatch)
    wrote = engine.config_writes("a", COMMANDS)
    assert wrote == ["skills.disabled", "agent.max_turns", "AGOS_FLAG", "plugins.enabled"]
    assert len(starts) == 1 and _config_clis(runner) == []  # one Hermes start, no CLI
    held = config_file.read(home)
    assert config_file.get(held, "skills.disabled") == ["x"]
    assert config_file.get(held, "agent.max_turns") == 7
    assert config_file.read_env(home)["AGOS_FLAG"] == "on"
    # The same values again: Hermes holds them, nothing is written.
    assert engine.config_writes("a", COMMANDS[:3]) == []
    assert starts[-1] == [str(home)]


def test_without_hermess_runtime_each_command_runs_as_its_own_cli(tmp_path: Path) -> None:
    engine, runner, home = _engine(tmp_path)
    assert engine.config_writes("a", COMMANDS) == [
        "skills.disabled",
        "agent.max_turns",
        "AGOS_FLAG",
        "plugins.enabled",
    ]
    assert [c[1:] for c in _config_clis(runner)] == [list(c) for c in COMMANDS]
    assert config_file.get(config_file.read(home), "agent.max_turns") == 7


def test_a_key_hermes_refuses_stops_the_rest_like_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, runner, home = _engine(tmp_path)
    starts = hermes_config_batch(monkeypatch)
    managed = engine.settings.managed_home
    managed.mkdir(parents=True, exist_ok=True)
    (managed / "config.yaml").write_text("agent:\n  max_turns: 3\n")  # pinned
    with pytest.raises(EngineError):
        engine.config_writes("a", COMMANDS)
    assert len(starts) == 1 and _config_clis(runner) == []  # no CLI retry
    held = config_file.read(home)
    assert config_file.get(held, "skills.disabled") == ["x"]  # before the refused key
    assert "AGOS_FLAG" not in config_file.read_env(home)  # after it: not run


def test_a_home_hermes_has_not_made_yet_gets_its_first_command_from_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, runner, home = _engine(tmp_path)
    starts = hermes_config_batch(monkeypatch)
    (home / "config.yaml").unlink()
    engine.config_writes("a", COMMANDS[:2])
    assert starts == [] and len(_config_clis(runner)) == 2
