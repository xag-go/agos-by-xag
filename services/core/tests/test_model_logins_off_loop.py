"""Settings → Models' login routes never start Hermes on the core's event loop
(audit F5): working out the provider (Hermes's catalog) and the workspace's root, and
each login step, run in FastAPI's threadpool, so every other page and live chat keeps
answering while Hermes starts. The suite's strict loop guard turns a step started on
the loop into a 500 here."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agos_core.actions.services.settings import model_logins
from agos_core.api import models
from agos_core.engine import loop_guard

VIEW = {
    "provider": "kimi",
    "status": "waiting",
    "url": None,
    "user_code": None,
    "needs_code": False,
    "message": "",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    def hermes(what: str, answer: Any = None) -> Any:
        def step(*_args: Any) -> Any:
            loop_guard.off_loop(what)  # where the real step starts Hermes
            return answer

        return step

    monkeypatch.setattr(model_logins, "provider_of", hermes("hermes catalog", "kimi"))
    monkeypatch.setattr(model_logins, "workspace_of", hermes("hermes roots", "w1"))
    for name in ("start", "status", "send_code", "cancel"):
        monkeypatch.setattr(model_logins, name, hermes(f"hermes auth {name}", VIEW))
    monkeypatch.setattr(model_logins, "logout", hermes("hermes auth logout"))
    app = FastAPI()
    app.include_router(models.router)
    app.state.core = SimpleNamespace()
    loop_guard.broken.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    loop_guard.broken.clear()


@pytest.mark.parametrize("base", ["/models/providers/kimi", "/workspaces/w1/models/providers/kimi"])
def test_every_login_step_runs_off_the_event_loop(client: TestClient, base: str) -> None:
    answers = {
        "start": client.post(f"{base}/login").status_code,
        "status": client.get(f"{base}/login").status_code,
        "code": client.post(f"{base}/login/code", json={"code": "123"}).status_code,
        "cancel": client.delete(f"{base}/login").status_code,
        "logout": client.post(f"{base}/logout").status_code,
    }
    assert answers == {"start": 201, "status": 200, "code": 200, "cancel": 200, "logout": 204}
    assert loop_guard.broken == []
