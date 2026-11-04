"""The pilot of the Service Layer: creating and deleting a workspace run as
registered operations (ops/specs/workspace.py, actions/workspace_ops.py), each a
saga (actions/workspaces.py): an idempotency key makes a retried create return
the first workspace, a fatal step undoes the steps before it, a step that may be
finished later leaves the saga "needs attention", and a delete that fails midway
starts again what it had stopped."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core import events
from agos_core.actions import tool_services, workspace_ops
from agos_core.actions import workspaces as ws_actions
from agos_core.actions.errors import ActionError
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.db import op_runs, sagas
from agos_core.db import workspaces as repo
from agos_core.domain.models import ModelSelection
from agos_core.ops import registry
from agos_core.ops.operation import OWNER

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as test_client:
        test_client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield test_client


def _core(client: TestClient) -> Any:
    return client.app.state.core  # type: ignore[attr-defined]


def _ids(core: Any) -> list[str]:
    return [w.id for w in repo.list_workspaces(core.db, include_archived=True)]


def _saga(core: Any, name: str) -> Any:
    row = core.db.execute("SELECT * FROM sagas WHERE name = ? ORDER BY id DESC", (name,)).fetchone()
    assert row is not None
    return row


def test_a_create_retried_with_its_key_makes_one_workspace(client: TestClient) -> None:
    body = {"name": "Argan Store", "defaultModel": MODEL}
    first = client.post("/workspaces", json=body, headers={"Idempotency-Key": "click-1"})
    again = client.post("/workspaces", json=body, headers={"Idempotency-Key": "click-1"})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() == {"id": "argan-store"}
    assert _ids(_core(client)) == ["argan-store"]
    other = client.post("/workspaces", json=body, headers={"Idempotency-Key": "click-2"})
    assert other.json() == {"id": "argan-store-2"}
    plain = client.post("/workspaces", json=body)  # no key: as before, a new one each time
    assert plain.json() == {"id": "argan-store-3"}


def test_the_create_is_audited_as_the_owners_and_its_saga_is_done(client: TestClient) -> None:
    ws = client.post("/workspaces", json={"name": "Store", "defaultModel": MODEL}).json()["id"]
    run = op_runs.latest(_core(client).db, "create_workspace")
    assert run is not None
    assert (run["actor"], run["status"], run["title"], run["workspace_id"]) == (
        "owner",
        "done",
        "Create the workspace Store",
        ws,
    )
    saga = _saga(_core(client), ws_actions.CREATE_SAGA)
    assert (saga["status"], saga["workspace_id"]) == ("done", ws)
    names = [s["name"] for s in sagas.steps(_core(client).db, int(saga["id"]))]
    assert names[:2] == ["folders", "rows"]


def test_a_fatal_setup_step_undoes_the_whole_create(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(core: Any, workspace_id: str) -> None:
        raise RuntimeError("tool services broke")

    monkeypatch.setattr(tool_services, "apply_to", broken)
    core = _core(client)
    with pytest.raises(RuntimeError, match="tool services broke"):
        ws_actions.create_workspace(core, name="Half", description="", default_model=_model())
    assert _ids(core) == []  # no half-made workspace left behind
    assert not (tmp_path / "data" / "workspaces" / "half").exists()
    saga = _saga(core, ws_actions.CREATE_SAGA)
    assert saga["status"] == "compensated" and saga["workspace_id"] is None
    # The same name is free again: nothing of the failed try is inherited.
    monkeypatch.undo()
    assert (
        ws_actions.create_workspace(core, name="Half", description="", default_model=_model())
        == "half"
    )


def test_a_step_hermes_can_finish_later_leaves_the_create_needing_attention(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(core: Any, workspace_id: str) -> None:
        raise ActionError("Docker is not running", 503)

    monkeypatch.setattr(ws_actions, "sync_workspace", refused)
    core = _core(client)
    ws = ws_actions.create_workspace(core, name="Later", description="", default_model=_model())
    assert ws in _ids(core)  # the workspace exists, its agent stays stopped (fail closed)
    saga = _saga(core, ws_actions.CREATE_SAGA)
    assert saga["status"] == "needs_attention"
    failed = [s["name"] for s in sagas.steps(core.db, int(saga["id"])) if s["status"] == "failed"]
    assert failed == ["sync"]
    monkeypatch.setattr(ws_actions, "sync_workspace", lambda core, workspace_id: None)
    assert ws_actions.finish_setup(core, ws) == []
    assert _saga(core, ws_actions.CREATE_SAGA)["status"] == "done"


def test_a_workspace_coming_back_finishes_the_setup_its_create_left(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(core: Any, workspace_id: str) -> None:
        raise ActionError("Docker is not running", 503)

    monkeypatch.setattr(ws_actions, "sync_workspace", refused)
    core = _core(client)
    ws = ws_actions.create_workspace(core, name="Back", description="", default_model=_model())
    monkeypatch.setattr(ws_actions, "sync_workspace", lambda core, workspace_id: None)
    assert client.post(f"/workspaces/{ws}/archive").status_code == 200
    assert _saga(core, ws_actions.CREATE_SAGA)["status"] == "needs_attention"
    assert client.post(f"/workspaces/{ws}/unarchive").status_code == 200
    assert _saga(core, ws_actions.CREATE_SAGA)["status"] == "done"


def test_the_created_event_is_published_once_the_workspace_is_made(client: TestClient) -> None:
    got: list[events.Event] = []
    stop = events.subscribe(events.WORKSPACE_CREATED, lambda core, e: got.append(e))
    try:
        ws = client.post("/workspaces", json={"name": "Told", "defaultModel": MODEL}).json()["id"]
    finally:
        stop()
    assert got == [events.Event(events.WORKSPACE_CREATED, ws, {"name": "Told"})]


def test_a_delete_that_fails_midway_starts_again_what_it_stopped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _core(client)
    ws = ws_actions.create_workspace(core, name="Keep", description="", default_model=_model())
    calls: list[str] = []
    automations = ws_actions._automations()
    monkeypatch.setattr(automations, "park", lambda core, w: calls.append(f"park:{w}"))
    monkeypatch.setattr(
        automations, "resync_workspace", lambda core, w: calls.append(f"resync:{w}")
    )
    monkeypatch.setattr(ws_actions, "_serve", lambda core, w: calls.append(f"serve:{w}"))

    def stuck(layout: Any, workspace_id: str) -> str:
        raise OSError("folder busy")

    monkeypatch.setattr(ws_actions, "move_workspace_to_trash", stuck)
    with pytest.raises(OSError, match="folder busy"):
        client.post(f"/workspaces/{ws}/delete", json={"confirm": ws})
    assert calls == [f"park:{ws}", f"serve:{ws}", f"resync:{ws}"]
    assert ws in _ids(core)  # still his, running again
    assert _saga(core, ws_actions.DELETE_SAGA)["status"] == "compensated"


def test_delete_is_an_operation_whose_undo_restores_from_the_trash(client: TestClient) -> None:
    core = _core(client)
    ws = ws_actions.create_workspace(core, name="Gone", description="", default_model=_model())
    assert workspace_ops.DELETE.spec.name == "delete_workspace"
    assert client.post(f"/workspaces/{ws}/delete", json={"confirm": ws}).status_code == 200
    assert ws not in _ids(core)
    run = op_runs.latest(core.db, "delete_workspace")
    assert run is not None and run["status"] == "done" and run["workspace_id"] == ws
    registry.undo(core, int(run["id"]), actor=OWNER)
    assert ws in _ids(core)


def test_a_wrong_confirm_is_still_refused_and_audited(client: TestClient) -> None:
    ws = client.post("/workspaces", json={"name": "Safe", "defaultModel": MODEL}).json()["id"]
    response = client.post(f"/workspaces/{ws}/delete", json={"confirm": "nope"})
    assert response.status_code == 400
    run = op_runs.latest(_core(client).db, "delete_workspace")
    assert run is not None and run["status"] == "failed"
    assert ws in _ids(_core(client))


def _model() -> ModelSelection:
    return ModelSelection.model_validate(MODEL)
