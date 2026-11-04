"""The Dashboard (GET /workspaces/{ws}/overview) asks the workspace's Hermes only
when what its answers come from changed: its usage (Hermes's analytics) when a
profile's sessions changed, its bots' lamps (Hermes's gateway verdict) when the
gateway's own files say something new. The read-ahead fills both after a start."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from channels_rig import connect, env, fake_telegram  # noqa: F401 - fixtures

from agos_core.engine.hermes import EngineError, HermesEngine
from agos_core.engine.read_cache import ReadCache


def _usage_from_hermes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Hermes's runtime as far as the usage script goes: the n-th ask counts n tokens."""
    asked: list[str] = []

    def runtime(self: Any, home: Path, script: str, tag: str, **_kw: Any) -> str:
        asked.append(tag)
        if tag != "AGOS-USAGE":
            raise EngineError("not in this test")
        n = asked.count("AGOS-USAGE")
        return json.dumps(
            {"models": {"m": {"tokens": n, "calls": 1, "input": n, "output": 0}}, "days": {}}
        )

    monkeypatch.setattr(HermesEngine, "_in_runtime", runtime)
    return asked


def test_usage_is_asked_from_hermes_again_only_when_its_sessions_changed(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tg, ws = env
    asked = _usage_from_hermes(monkeypatch)
    url = f"/workspaces/{ws}/overview"
    assert client.get(url).json()["usage"]["tokens"] == 1
    assert client.get(url).json()["usage"]["tokens"] == 1
    assert asked.count("AGOS-USAGE") == 1
    # Hermes counted something: the page answers at once with Hermes's last count
    # and Hermes counts again in the background (usage moves all the time).
    (core.engine.profile_home(ws) / "state.db").write_bytes(b"sessions")
    assert client.get(url).json()["usage"]["tokens"] == 1
    assert ReadCache.settle()
    assert client.get(url).json()["usage"]["tokens"] == 2
    assert asked.count("AGOS-USAGE") == 2


def _gateway_asks(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every ask for Hermes's gateway verdict (conftest's stand-in answers it)."""
    calls: list[Path] = []
    verdict = HermesEngine.gateway_status

    def counted(self: Any, home: Path, fresh: bool = False, kept: bool = False) -> Any:
        calls.append(home)
        return verdict(self, home, fresh=fresh, kept=kept)

    monkeypatch.setattr(HermesEngine, "gateway_status", counted)
    return calls


def _state(core: Any, ws: str) -> dict[str, Any]:
    return dict(json.loads((core.engine.profile_home(ws) / "gateway_state.json").read_text()))


def test_a_bots_lamp_asks_hermes_again_only_when_the_gateways_files_say_something_new(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tg, ws = env
    _usage_from_hermes(monkeypatch)
    connect(client)
    calls = _gateway_asks(monkeypatch)
    url = f"/workspaces/{ws}/overview"
    assert client.get(url).json()["channels"][0]["status"] == "connected"
    assert client.get(url).json()["channels"][0]["status"] == "connected"
    assert len(calls) == 1
    # The gateway's heartbeat alone (its updated_at re-stamped): nothing new to ask.
    state = _state(core, ws)
    state["updated_at"] = "2099-01-01T00:00:00+00:00"
    (core.engine.profile_home(ws) / "gateway_state.json").write_text(json.dumps(state))
    assert client.get(url).json()["channels"][0]["status"] == "connected"
    assert len(calls) == 1
    # Hermes says the bot fails: the very next page shows it.
    state["platforms"]["telegram"] = {"state": "error", "error_message": "Unauthorized"}
    (core.engine.profile_home(ws) / "gateway_state.json").write_text(json.dumps(state))
    lamp = client.get(url).json()["channels"][0]
    assert (lamp["status"], lamp["reason"]) == ("error", "Unauthorized")
    assert len(calls) == 2


def test_the_read_ahead_asks_the_dashboards_hermes_reads_before_the_first_page(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tg, ws = env
    asked = _usage_from_hermes(monkeypatch)
    connect(client)
    calls = _gateway_asks(monkeypatch)
    from agos_core.engine import read_ahead

    assert "agos_core.actions.services.system.dashboard:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.services.system.dashboard:read_ahead",))
    assert asked.count("AGOS-USAGE") == 1 and len(calls) == 1
    shown = client.get(f"/workspaces/{ws}/overview").json()
    assert shown["usage"]["tokens"] == 1 and shown["channels"][0]["status"] == "connected"
    assert asked.count("AGOS-USAGE") == 1 and len(calls) == 1


def test_a_dashboard_rendered_again_with_nothing_changed_starts_no_hermes(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every Hermes read of the Dashboard is kept while what it comes from holds:
    a second render starts neither Hermes's runtime nor its CLI."""
    client, core, _fake, _tg, ws = env
    asked = _usage_from_hermes(monkeypatch)
    connect(client)
    calls = _gateway_asks(monkeypatch)
    url = f"/workspaces/{ws}/overview"
    assert client.get(url).status_code == 200
    assert ReadCache.settle()
    before = (len(asked), len(calls))
    cli: list[tuple[str, ...]] = []
    real = core.engine._hermes

    def counted(workspace_id: str, *args: str, **kw: Any) -> str:
        cli.append(args)
        return str(real(workspace_id, *args, **kw))

    monkeypatch.setattr(core.engine, "_hermes", counted)
    core.engine.runner.calls.clear()
    assert client.get(url).status_code == 200
    assert ReadCache.settle()
    assert (len(asked), len(calls)) == before
    assert cli == [] and core.engine.runner.calls == []
