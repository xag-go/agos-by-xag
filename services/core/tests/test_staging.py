"""A staging copy is quiet (actions/staging.py, AGOS_STAGING=1): every Hermes cron
job paused, no phone push, AGOS's own egress proxy name its own."""

from pathlib import Path
from typing import Any

import pytest
from test_api import MODEL
from test_library import env  # noqa: F401 - fixture

from agos_core.actions import staging, web_push


class Bridge:
    def __init__(self, jobs: dict[str, list[dict[str, Any]]]) -> None:
        self.jobs = jobs
        self.paused: list[tuple[str, str, str]] = []

    def job_states(self, home: Path) -> list[dict[str, Any]]:
        return self.jobs.get(home.name, [])

    def pause(self, home: Path, job_id: str, reason: str) -> None:
        self.paused.append((home.name, job_id, reason))


def test_staging_pauses_every_running_cron_job(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    ws = client.post("/workspaces", json={"name": "Shop", "defaultModel": MODEL}).json()["id"]
    root = core.engine.profile_home(ws)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("model: {}\n")
    bridge = Bridge({root.name: [{"id": "a", "enabled": True}, {"id": "b", "enabled": False}]})
    core.engine.cron_bridge = bridge
    assert staging.quiet(core) == 0  # not a staging copy: nothing paused
    monkeypatch.setenv("AGOS_STAGING", "1")
    assert staging.quiet(core) == 1
    assert bridge.paused == [(root.name, "a", staging.REASON)]


def test_staging_runs_no_kanban_dispatcher(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M3: copied cards would be worked with real provider logins: in a staging copy
    no profile, the Co-Founder's included, runs Hermes's Kanban dispatcher."""
    from agos_core.actions import agent_profiles

    client, core, _runner, _home = env
    ws = client.post("/workspaces", json={"name": "Shop", "defaultModel": MODEL}).json()["id"]
    live = agent_profiles.kanban_pairs(core, ws, cofounder=True)
    assert live["kanban.dispatch_in_gateway"] == "true"
    monkeypatch.setenv("AGOS_STAGING", "1")
    for cofounder in (True, False):
        pairs = agent_profiles.kanban_pairs(core, ws, cofounder=cofounder)
        assert pairs["kanban.dispatch_in_gateway"] == "false"


def test_staging_sends_no_phone_push(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _runner, _home = env
    monkeypatch.setattr(
        web_push,
        "subscriptions",
        lambda _core: [{"endpoint": "https://x", "p256dh": "", "auth": ""}],
    )
    sent: list[Any] = []
    monkeypatch.setattr(web_push, "queue", lambda *a, **k: sent.append(a))
    monkeypatch.setenv("AGOS_STAGING", "1")
    assert web_push.notify(core, "t", "b") == 0
    assert sent == []


def test_the_egress_proxy_name_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from agos_core.engine import network

    monkeypatch.setenv("AGOS_EGRESS_NAME", "agos-stg-egress")
    try:
        importlib.reload(network)
        assert network.PROXY_NAME == "agos-stg-egress"
        assert network.proxy_url().startswith("http://agos-stg-egress:")
    finally:
        monkeypatch.delenv("AGOS_EGRESS_NAME")
        importlib.reload(network)
    assert network.PROXY_NAME == "agos-egress"
