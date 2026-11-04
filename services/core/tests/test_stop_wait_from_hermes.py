"""#24: AGOS's gateway stop waits for Hermes's own stop budget, derived from
`agent.restart_drain_timeout` by Hermes's own readers (H: hermes_cli/gateway.py
_get_restart_drain_timeout / _get_cron_drain_timeout, gateway/restart.py
resolve_systemd_timeout_stop_sec: what systemd's TimeoutStopSec is sized from), and
the drain itself is the owner's choice (AGOS's value only as a new profile's start)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import MODEL, FakeRunner, env  # noqa: F401 - fixture

from agos_core.engine import hermes as hermes_engine


def _stop_timeouts(
    env: tuple[TestClient, FakeRunner, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    budget: Any,
) -> list[float]:
    client, _runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    engine = client.app.state.core.engine  # type: ignore[attr-defined]
    asked: list[float] = []

    def hermes(key: str, *args: str, timeout: float = 60, **_kw: Any) -> str:
        if args[:2] == ("gateway", "stop"):
            asked.append(timeout)
        return ""

    monkeypatch.setattr(engine, "_quiet_drain", lambda home, *, on: budget if on else 0.0)
    monkeypatch.setattr(engine, "_hermes", hermes)
    monkeypatch.setattr(engine, "is_running", lambda workspace_id: False)
    engine.stop(ws)
    return asked


def test_the_stop_waits_for_hermess_own_stop_budget(
    env: tuple[TestClient, FakeRunner, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _stop_timeouts(env, monkeypatch, 300.0) == [300.0 + hermes_engine.STOP_HEADROOM_S]


def test_without_hermess_answer_the_stop_keeps_agoss_fallback_wait(
    env: tuple[TestClient, FakeRunner, Path],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _stop_timeouts(env, monkeypatch, None) == [hermes_engine.STOP_WAIT_S]


def test_the_quiet_drain_script_asks_hermes_for_the_budget() -> None:
    script = hermes_engine._QUIET_DRAIN
    assert "resolve_systemd_timeout_stop_sec" in script
    assert "_get_restart_drain_timeout" in script and "_get_cron_drain_timeout" in script


def test_the_drain_is_the_owners_choice_not_forced() -> None:
    from agos_core.actions.hermes_all_settings import FORCED_WHY
    from agos_core.engine.owner_choices import WHY

    assert "agent.restart_drain_timeout" not in FORCED_WHY
    assert "agent.restart_drain_timeout" in WHY
    pairs = {"agent.restart_drain_timeout": "60"}
    from agos_core.engine.owner_choices import keep_owner

    assert keep_owner(pairs, {"agent": {"restart_drain_timeout": 300}}) == {}
    assert keep_owner(pairs, {}) == pairs
