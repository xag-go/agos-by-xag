"""Idempotency keys on the web's create / run actions (ARCHITECTURE.md §10): the web
sends an invisible Idempotency-Key with Create workspace, the owner's own hire and
Run now; a retry or a double click with the same key gets the first answer and never
hires or runs twice (agos_core/ops/idempotency.py; a registered operation uses the
registry's own key, the same op_runs rows)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.actions import automations, proposals
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.db import op_runs
from agos_core.ops import idempotency
from agos_core.ops.errors import OperationNotAllowed

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


def test_a_key_runs_the_work_once_and_gives_the_first_answer(client: TestClient) -> None:
    core = _core(client)
    done: list[int] = []

    def work() -> dict[str, Any]:
        done.append(1)
        return {"id": len(done)}

    assert idempotency.once(core, "api.thing", "k1", work) == {"id": 1}
    assert idempotency.once(core, "api.thing", "k1", work) == {"id": 1}
    assert idempotency.once(core, "api.thing", "k2", work) == {"id": 2}
    assert idempotency.once(core, "api.thing", None, work) == {"id": 3}  # no key: as before
    assert len(done) == 3
    run = op_runs.find(core.db, "api.thing", "k1")
    assert run is not None and run["status"] == "done" and run["actor"] == "owner"


def test_a_failed_try_lets_its_key_go(client: TestClient) -> None:
    core = _core(client)
    tries: list[int] = []

    def flaky() -> dict[str, Any]:
        tries.append(1)
        if len(tries) == 1:
            raise RuntimeError("Hermes was busy")
        return {"ok": True}

    with pytest.raises(RuntimeError):
        idempotency.once(core, "api.thing", "k", flaky)
    assert idempotency.once(core, "api.thing", "k", flaky) == {"ok": True}
    assert len(tries) == 2


def test_a_key_of_another_workspace_is_refused(client: TestClient) -> None:
    core = _core(client)
    for name in ("A", "B"):
        client.post("/workspaces", json={"name": name, "defaultModel": MODEL})
    idempotency.once(core, "api.thing", "k", dict, workspace_id="a")
    with pytest.raises(OperationNotAllowed):
        idempotency.once(core, "api.thing", "k", dict, workspace_id="b")


def test_the_owners_own_hire_with_a_key_hires_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = client.post("/workspaces", json={"name": "Shop", "defaultModel": MODEL}).json()["id"]
    hired: list[str] = []

    def own_hire(core: Any, workspace_id: str, *, name: str, **_: Any) -> int:
        hired.append(name)
        return 40 + len(hired)

    monkeypatch.setattr(proposals, "own_hire", own_hire)
    body = {"name": "Sara", "title": "", "summary": "", "definition": {}}
    first = client.post(f"/workspaces/{ws}/hires", json=body, headers={"Idempotency-Key": "h1"})
    again = client.post(f"/workspaces/{ws}/hires", json=body, headers={"Idempotency-Key": "h1"})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() == {"id": 41}
    assert hired == ["Sara"]
    client.post(f"/workspaces/{ws}/hires", json=body)  # no key: a new hire each time
    assert hired == ["Sara", "Sara"]


def test_run_now_with_a_key_runs_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = client.post("/workspaces", json={"name": "Shop", "defaultModel": MODEL}).json()["id"]
    runs: list[int] = []
    monkeypatch.setattr(
        automations, "run_now", lambda core, workspace_id, automation_id, values: runs.append(1)
    )
    url = f"/workspaces/{ws}/automations/3/run"
    assert client.post(url, headers={"Idempotency-Key": "r1"}).status_code == 202
    assert client.post(url, headers={"Idempotency-Key": "r1"}).status_code == 202
    assert runs == [1]
    assert client.post(url, headers={"Idempotency-Key": "r2"}).status_code == 202
    assert runs == [1, 1]
