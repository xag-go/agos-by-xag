"""Resource limits on each gateway's drop-in (engine/unit_limits.py) and on AGOS's
own services (deploy/install-server.sh): one runaway workspace must not take the
machine or the other workspaces (threat model T18, docs/adr/0025)."""

from pathlib import Path
from typing import Any

import pytest

from agos_core.config import ConfigError, EngineConfig, _engine
from agos_core.engine import root_unit, unit_limits
from agos_core.engine.hermes import HermesEngine

REPO = Path(__file__).resolve().parents[3]


def test_the_defaults_scale_to_the_machines_ram() -> None:
    assert unit_limits.scaled(16384) == unit_limits.GatewayLimits(3072, 4096, 512)
    assert unit_limits.scaled(2048) == unit_limits.GatewayLimits(768, 1024, 512)  # floor
    assert unit_limits.scaled(65536) == unit_limits.GatewayLimits(3072, 4096, 512)  # ceiling
    assert unit_limits.scaled(0).memory_max_mb == 4096  # RAM unknown: the ceiling


def test_the_owner_overrides_each_value_or_turns_them_off() -> None:
    got = unit_limits.from_env({"AGOS_GATEWAY_MEMORY_MAX_MB": "2000"}, total_mb=16384)
    assert got is not None and got.memory_max_mb == 2000
    assert got.memory_high_mb == 1500  # follows the override (3/4) when not set itself
    got = unit_limits.from_env(
        {"AGOS_GATEWAY_MEMORY_MAX_MB": "2000", "AGOS_GATEWAY_MEMORY_HIGH_MB": "1900"},
        total_mb=16384,
    )
    assert got is not None and (got.memory_high_mb, got.memory_max_mb) == (1900, 2000)
    got = unit_limits.from_env({"AGOS_GATEWAY_TASKS_MAX": "128"}, total_mb=16384)
    assert got is not None and got.tasks_max == 128
    assert unit_limits.from_env({"AGOS_GATEWAY_LIMITS": "off"}, total_mb=16384) is None
    with pytest.raises(unit_limits.LimitsError):
        unit_limits.from_env({"AGOS_GATEWAY_MEMORY_MAX_MB": "a lot"}, total_mb=16384)
    with pytest.raises(unit_limits.LimitsError):
        unit_limits.from_env({"AGOS_GATEWAY_LIMITS": "maybe"}, total_mb=16384)


def test_a_bad_override_stops_the_process_at_start() -> None:
    source = {"AGOS_ENGINE": "hermes", "HOME": "/h", "AGOS_HERMES_BIN": "/bin/hermes",
              "AGOS_DOCKER_BIN": "/bin/docker", "AGOS_GATEWAY_TASKS_MAX": "-3"}  # fmt: skip
    with pytest.raises(ConfigError):
        _engine(source)


def test_the_dropin_lines_cap_memory_and_tasks() -> None:
    lines = unit_limits.dropin_lines(unit_limits.GatewayLimits(1536, 2048, 512))
    assert "MemoryAccounting=yes" in lines and "TasksAccounting=yes" in lines
    assert "MemoryHigh=1536M" in lines
    assert "MemoryMax=2048M" in lines
    assert "TasksMax=512" in lines
    assert unit_limits.dropin_lines(None) == []
    partial = unit_limits.dropin_lines(unit_limits.GatewayLimits(0, 2048, 0))
    assert [ln for ln in partial if ln.startswith(("MemoryHigh", "TasksMax"))] == []


class _Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        self.calls.append(list(args))
        return ""

    def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
        pass


def _engine_with_limits(tmp_path: Path, limits: unit_limits.GatewayLimits | None) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "data" / "hermes",
            runtime_dir=tmp_path / ".hermes" / "tools",
            gateway_supervisor="systemd",
            gateway_limits=limits,
        ),
        runner=_Runner(),
    )


UNIT = '[Service]\nExecStart="/opt/h/.hermes/bin/hermes" "gateway" "run"\n'


def _dropin(tmp_path: Path, limits: unit_limits.GatewayLimits | None) -> str:
    engine = _engine_with_limits(tmp_path, limits)
    engine.root("alpha").mkdir(parents=True, exist_ok=True)
    root_unit.remember(engine.root("alpha"), "hermes-gw-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(UNIT)
    engine.refresh_dropin("alpha")
    return (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()


def test_the_gateway_dropin_carries_the_limits(tmp_path: Path) -> None:
    body = _dropin(tmp_path, unit_limits.GatewayLimits(1536, 2048, 512))
    assert "MemoryHigh=1536M" in body and "MemoryMax=2048M" in body and "TasksMax=512" in body
    assert body.index("[Service]") < body.index("MemoryMax=")


def test_limits_off_writes_a_dropin_without_them(tmp_path: Path) -> None:
    body = _dropin(tmp_path, None)
    assert "MemoryMax" not in body and "TasksMax" not in body
    assert "ExecStart=" in body  # the wall stays


def test_the_installer_caps_every_agos_service_and_the_journal() -> None:
    text = (REPO / "deploy" / "install-server.sh").read_text()
    core = text.split("write_unit agos-core")[1].split("write_unit")[0]
    hooks = text.split("write_unit agos-hooks")[1].split("write_unit")[0]
    web = text.split("write_unit agos-web")[1].split("say ")[0]
    for name, unit in (("core", core), ("hooks", hooks), ("web", web)):
        assert "MemoryMax=" in unit, f"agos-{name} has no MemoryMax"
        assert "TasksMax=" in unit, f"agos-{name} has no TasksMax"
        assert "ProtectProc=invisible" in unit, f"agos-{name} sees every /proc"
    # web and hooks never talk to Docker; the core needs the socket (sandbox
    # image build, egress proxy, MCP containers) until the broker (ADR 0025).
    for name, unit in (("hooks", hooks), ("web", web)):
        assert "InaccessiblePaths=-/run/docker.sock" in unit, f"agos-{name} can reach Docker"
    assert "SystemMaxUse=1G" in text  # journald cap
    assert "OOMScoreAdjust=-500" in core  # the OOM killer spares the core


# ---- the sandbox containers' own limits (Hermes's, pinned) ---------------------

HERMES = Path.home() / ".hermes" / "hermes-agent"


@pytest.mark.skipif(not HERMES.is_dir(), reason="needs the Hermes install")
def test_hermes_keeps_the_sandbox_limited_and_unprivileged() -> None:
    """AGOS writes no terminal.container_* key (engine/rules.py), so each
    workspace's sandbox runs on Hermes's own defaults: they must stay real limits,
    caps dropped and no-new-privileges, and the terminal must not pick a user (it
    inherits the image's `agent`). A Hermes update that loosens any of this fails
    here before the pin moves (docs/HERMES-UPDATES.md)."""
    defaults = (HERMES / "hermes_cli" / "config_defaults.py").read_text()
    for key, value in (
        ("container_cpu", "1"),
        ("container_memory", "5120"),
        ("container_disk", "51200"),
    ):
        assert f'"{key}": {value},' in defaults, f"Hermes default {key} changed: re-check T18"
    docker = (HERMES / "tools" / "environments" / "docker.py").read_text()
    assert '_DEFAULT_PIDS_LIMIT = "2048"' in docker
    assert '"--cap-drop", "ALL",' in docker
    assert '"--security-opt", "no-new-privileges"' in docker
    # The run/exec argv pass no --user (outside docker_run_as_host_user, which AGOS
    # locks to false): the container and its terminal stay the image's `agent`.
    run_bash = docker.split("def _run_bash")[1].split("def ")[0]
    assert "--user" not in run_bash and '"-u"' not in run_bash
