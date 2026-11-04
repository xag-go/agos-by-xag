"""At the core's start, a workspace whose create saga needs attention (a setup step
Hermes refused while it was made: Docker down...) is finished (`finish_setup`)
inside the start's sandbox sync (actions/engine.resync_all)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.actions import engine as engine_actions
from agos_core.actions import workspaces as ws_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.services.system import startup
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.domain.models import ModelSelection

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


@pytest.fixture
def core(tmp_path: Path) -> Iterator[Any]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as client:
        yield client.app.state.core  # type: ignore[attr-defined]


def _status(core: Any) -> str:
    row = core.db.execute(
        "SELECT status FROM sagas WHERE name = ? ORDER BY id DESC", (ws_actions.CREATE_SAGA,)
    ).fetchone()
    return str(row["status"])


def _half_made(core: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    def refused(core: Any, workspace_id: str) -> None:
        raise ActionError("Docker is not running", 503)

    monkeypatch.setattr(ws_actions, "sync_workspace", refused)
    ws = ws_actions.create_workspace(
        core, name="Later", description="", default_model=ModelSelection.model_validate(MODEL)
    )
    assert _status(core) == "needs_attention"
    monkeypatch.setattr(ws_actions, "sync_workspace", lambda core, workspace_id: None)
    return ws


def test_the_start_sync_finishes_a_create_left_needing_attention(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _half_made(core, monkeypatch)
    finished: list[str] = []

    def finish(core: Any, workspace_id: str) -> list[str]:
        finished.append(workspace_id)
        return ws_actions.finish_setup(core, workspace_id)

    asyncio.run(engine_actions.resync_all(core, finish=finish))
    assert finished == [ws]
    assert _status(core) == "done"


def test_a_setup_hermes_still_refuses_stays_needing_attention_and_the_start_goes_on(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _half_made(core, monkeypatch)

    def broken(core: Any, workspace_id: str) -> list[str]:
        raise OSError("hermes is gone")

    asyncio.run(engine_actions.resync_all(core, finish=broken))  # never raises
    assert _status(core) == "needs_attention"


def test_the_core_start_passes_finish_setup_to_the_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    class Stop(Exception):
        pass

    async def resync_all(core: Any, **kw: Any) -> None:
        seen.append(kw.get("finish"))
        raise Stop

    async def nothing(core: Any) -> None:
        return None

    monkeypatch.setattr(startup, "resync_all", resync_all)
    monkeypatch.setattr(startup, "_before_hand_over", nothing)
    with pytest.raises(Stop):
        asyncio.run(startup.sync_then_serve(object()))
    assert seen == [ws_actions.finish_setup]
