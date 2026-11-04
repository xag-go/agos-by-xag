"""The chat tests' rig: a fake Hermes behind the API (FakeHermes), the `env` fixture
and the helpers that open a chat, say something and wait for the answer.

Shared by tests/test_chat*.py and the other chat tests (they import it directly).
"""

import base64
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_gateway import follow_requests, pump
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import chat as chat_actions
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine.hermes import EngineError

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


# ---- through the API, with a fake Hermes -----------------------------------------


class FakeHermes:
    """Runs whose events the test pushes; the stream ends on a run.* event."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.keys: list[str] = []
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self.stopped: list[str] = []
        self.approvals: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.refuse = False
        # The fake gateway (tests/fake_gateway.py): on, and its answers in progress.
        self.gateway = True
        self.turns: dict[str, dict[str, Any]] = {}

    def create_run(self, workspace_id: str, body: dict[str, Any], *, idempotency_key: str) -> str:
        if self.refuse:
            raise EngineError("the engine refused to start the work: no credits")
        run_id = f"run_{len(self.bodies) + 1}"
        self.bodies.append(body)
        self.keys.append(idempotency_key)
        self.events[run_id] = []
        self.status[run_id] = {"status": "running"}
        return run_id

    def push(self, run_id: str, *events: dict[str, Any]) -> None:
        self.events[run_id].extend(events)
        for e in events:
            if str(e.get("event", "")).startswith("run."):
                self.status[run_id] = {"status": e["event"][4:], **e}

    def follow_events(
        self,
        workspace_id: str,
        run_id: str,
        on_event: Callable[[dict[str, Any]], bool],
        should_stop: Callable[[], bool],
    ) -> None:
        seen = 0
        for _ in range(3_000):
            if should_stop():
                return
            while seen < len(self.events[run_id]):
                event = self.events[run_id][seen]
                seen += 1
                if on_event(event):
                    return
            time.sleep(0.01)

    def get_run(self, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        return self.status.get(run_id)

    def stop_run(self, workspace_id: str, run_id: str) -> None:
        self.stopped.append(run_id)
        self.push(run_id, {"event": "run.cancelled"})

    def answer_approval(self, workspace_id: str, run_id: str, choice: str) -> None:
        self.approvals.append((run_id, choice))
        self.push(run_id, {"event": "approval.responded", "choice": choice})

    def steer(self, workspace_id: str, run_id: str, text: str) -> bool:
        self.steered = [*getattr(self, "steered", []), (run_id, text)]
        return True

    def delete_session(self, workspace_id: str, session_id: str) -> None:
        self.deleted.append(session_id)


Env = tuple[TestClient, FakeHermes, Any, str]


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
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
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: True
        core.engine.stop = lambda workspace_id, **_: None
        fake = FakeHermes()
        core.engine.runs_client = fake
        follow_requests(client, core, fake)
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        CLIENT["client"] = client
        yield client, fake, core, ws
        for live in chat_actions._state(core).live.values():
            live.stop = True


CLIENT: dict[str, TestClient] = {}


def settle(core: Any, until: Callable[[], bool], rounds: int = 250) -> None:
    """Ticks the chat loop on the app's own event loop (where answers run as
    tasks, like in production) until `until()` holds."""
    portal = CLIENT["client"].portal
    assert portal is not None
    for _ in range(rounds):
        portal.call(chat_actions.tick, core)
        if getattr(core.engine.runs_client, "gateway", True):
            pump(core, core.engine.runs_client)
        if until():
            return
        time.sleep(0.02)
    raise AssertionError("the chat did not settle")


def new_chat(client: TestClient, ws: str, title: str = "Research") -> int:
    return int(client.post(f"/workspaces/{ws}/chats", json={"title": title}).json()["id"])


def say(client: TestClient, ws: str, chat: int, text: str) -> None:
    r = client.post(f"/workspaces/{ws}/chats/{chat}/messages", json={"body": text})
    assert r.status_code == 201, r.text


def get(client: TestClient, ws: str, chat: int) -> dict[str, Any]:
    data: dict[str, Any] = client.get(f"/workspaces/{ws}/chats/{chat}").json()
    return data


# ---- access and attachments ------------------------------------------------------

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()


def chat_actions_tick(core: Any) -> None:
    portal = CLIENT["client"].portal
    assert portal is not None
    portal.call(chat_actions.tick, core)
