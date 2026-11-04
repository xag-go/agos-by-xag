"""Each workspace's root gateway is always on: Hermes's own service keeps it up.
AGOS makes one pass when it starts (and when a workspace comes back); it never
watches the gateways after that (members have no gateway of their own)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import idle
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, list[str]]]:
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
        parked: list[str] = []
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: workspace_id not in parked
        core.engine.stop = lambda workspace_id, **_: None
        core.engine.park = parked.append
        core.engine.service_active = lambda workspace_id: workspace_id not in parked
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield client, core, parked


def test_one_pass_hands_each_gateway_to_hermess_service(env: Any) -> None:
    """One pass (at AGOS's start) installs Hermes's service where it isn't active;
    a gateway Hermes's service already runs is left alone. No loop restarts them:
    Hermes's service (Restart=always) does."""
    client, core, parked = env
    ws = client.post("/workspaces", json={"name": "Quiet", "defaultModel": MODEL}).json()["id"]
    started: list[str] = []
    core.engine.start = lambda workspace_id, **_: started.append(workspace_id)
    assert idle.ensure_all(core) == [] and started == []  # the service runs it
    parked.append(ws)  # no service yet (or AGOS spawned it before)
    assert idle.ensure_all(core) == [ws]
    assert started == [ws]
    assert not hasattr(idle, "sweep")  # nothing in AGOS watches the gateways


def test_the_loops_never_start_a_gateway() -> None:
    """Only Hermes's service keeps gateways up: AGOS's loops have no start in them."""
    import inspect

    from agos_core.actions import automations, channels

    for loop in (idle.chores, automations.run_forever, channels.run_forever):
        assert ".start(" not in inspect.getsource(loop)


def test_a_message_never_starts_a_gateway_under_hermess_service(env: Any) -> None:
    """A message for a stopped gateway doesn't start it: Hermes's systemd service
    (Restart=always) keeps it up, and one stopped on purpose stays stopped. Only the
    test-only "spawn" supervisor (no service) brings back a gateway AGOS spawned."""
    import dataclasses

    client, core, parked = env
    ws = client.post("/workspaces", json={"name": "Calm", "defaultModel": MODEL}).json()["id"]
    started: list[str] = []
    core.engine.start = lambda workspace_id, **_: started.append(workspace_id)
    parked.append(ws)  # stopped
    assert idle.spawned_up(core, ws) is False and started == []
    core.engine.settings = dataclasses.replace(core.engine.settings, gateway_supervisor="spawn")
    assert idle.spawned_up(core, ws) is True and started == [ws]


def test_a_board_decision_never_starts_a_gateway_under_hermess_service(env: Any) -> None:
    """The learning conversation (a board decision said to Hermes) waits in the
    inbox for a stopped gateway under Hermes's systemd service; only the test-only
    "spawn" supervisor starts it."""
    import dataclasses

    from agos_core.actions import learning

    client, core, parked = env
    ws = client.post("/workspaces", json={"name": "Still", "defaultModel": MODEL}).json()["id"]
    started: list[str] = []
    core.engine.start = lambda workspace_id, **_: started.append(workspace_id)
    parked.append(ws)  # stopped
    learning.say(core, ws, "The owner rejected: x")
    assert started == []
    waiting = core.db.execute(
        "SELECT text FROM hermes_inbox WHERE workspace_id = ? AND chat_ref = ?",
        (ws, learning.ADDRESS),
    ).fetchall()
    assert [r["text"] for r in waiting][-1] == "The owner rejected: x"
    core.engine.settings = dataclasses.replace(core.engine.settings, gateway_supervisor="spawn")
    learning.say(core, ws, "The owner approved: y")
    assert started == [ws]


def test_chats_and_rooms_leave_starting_to_hermes() -> None:
    import inspect

    from agos_core.actions import chat, learning, rooms

    assert "engine.start(" not in inspect.getsource(learning.say)
    for fn in (chat._gateway_up, rooms._wake):
        src = inspect.getsource(fn)
        assert "engine.start(" not in src and "is_running" not in src


def test_a_new_workspace_s_gateway_is_started_as_hermess_service(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new workspace's gateway is handed to Hermes's service (idle.ensure) right
    when it's made: no message starts one, so without this its chats never got an
    answer on the systemd supervisor (found live after step 27)."""
    import threading

    client, _core, _ = env
    served: list[str] = []
    done = threading.Event()

    def ensure(core: Any, workspace_id: str) -> bool:
        served.append(workspace_id)
        done.set()
        return True

    monkeypatch.setattr(idle, "ensure", ensure)
    ws = client.post("/workspaces", json={"name": "Fresh", "defaultModel": MODEL}).json()["id"]
    assert done.wait(10), "the new workspace's gateway was never handed to Hermes's service"
    assert served == [ws]
