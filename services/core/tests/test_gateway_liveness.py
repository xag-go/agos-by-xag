"""A gateway's liveness is Hermes's own verdict (area1 P1), run in its runtime:
gateway/status.py get_running_pid (lock + pid file), runtime_status_pid_is_live
(start-time guard against a reused pid) and runtime_status_is_stale (120 s without
a heartbeat). AGOS no longer guesses from `b"gateway" in cmdline`. Against the
installed Hermes; skipped on a machine without it."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agos_core.config import EngineConfig
from agos_core.engine.hermes import HermesEngine


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermesEngine:
    monkeypatch.undo()  # the real Hermes, not conftest's stand-in
    hermes = shutil.which("hermes")
    if not hermes:
        pytest.skip("no Hermes install on this machine")
    tools = Path.home() / ".hermes" / "tools"
    return HermesEngine(
        EngineConfig(
            hermes_bin=hermes,
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=Path.home(),
            roots_dir=tmp_path / "roots",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        egress=False,
    )


def _record(home: Path, **fields: object) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "gateway_state.json").write_text(json.dumps({"gateway_state": "running", **fields}))


def test_hermes_says_whether_a_gateway_lives(engine: HermesEngine, tmp_path: Path) -> None:
    home = tmp_path / "roots" / "agos-a"
    now = datetime.now(UTC).isoformat()
    _record(home, pid=999_999_999, updated_at=now)
    dead = engine.gateway_status(home, fresh=True)
    assert dead["live"] is False and dead["pid"] is None
    assert dead["record"]["gateway_state"] == "running"
    _record(home, pid=os.getpid(), updated_at=now)
    alive = engine.gateway_status(home, fresh=True)
    assert alive["live"] is True and alive["stale"] is False
    # a pid that was reused: its start time isn't the recorded one
    _record(home, pid=os.getpid(), start_time=1, updated_at=now)
    assert engine.gateway_status(home, fresh=True)["live"] is False
    _record(home, pid=os.getpid(), updated_at="2026-01-01T00:00:00+00:00")
    assert engine.gateway_status(home, fresh=True)["stale"] is True
    # no lock held, no running gateway: never "up", whatever the snapshot says
    assert engine.gateway_status(home, fresh=True)["pid"] is None
    assert engine._gateway_up(home) is False


def test_agos_has_no_cmdline_guess_any_more() -> None:
    engine = Path(__file__).resolve().parents[1] / "src" / "agos_core" / "engine" / "hermes"
    text = "\n".join(p.read_text() for p in sorted(engine.glob("*.py")))
    assert "def gateway_status(" in text  # the package is read
    assert 'b"gateway" in cmd' not in text and "def _alive(" not in text
