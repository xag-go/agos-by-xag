"""The API end to end, through the same HTTP calls the web app makes."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agos_core.api.app import create_app
from agos_core.config import Settings

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as test_client:
        token = settings.internal_token_file.read_text()
        test_client.headers["x-agos-internal"] = token
        yield test_client


def create_workspace(client: TestClient, name: str) -> str:
    response = client.post("/workspaces", json={"name": name, "defaultModel": MODEL})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_health_is_public_everything_else_needs_the_token(client: TestClient) -> None:
    anonymous = TestClient(client.app)
    assert anonymous.get("/health").json() == {"ok": True}
    assert anonymous.get("/workspaces").status_code == 401
    assert anonymous.get("/workspaces", headers={"x-agos-internal": "wrong"}).status_code == 401
    assert client.get("/workspaces").status_code == 200


def test_no_public_docs(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404


def test_workspace_lifecycle(client: TestClient, tmp_path: Path) -> None:
    ws = create_workspace(client, "Argan Store")
    assert ws == "argan-store"
    assert create_workspace(client, "Argan Store") == "argan-store-2"
    assert (tmp_path / "data" / "workspaces" / ws / "files").is_dir()
    settings = {
        "name": "Argan",
        "defaultModel": MODEL,
    }
    assert client.put(f"/workspaces/{ws}", json=settings).status_code == 200
    got = client.get(f"/workspaces/{ws}").json()
    assert got["name"] == "Argan" and "limits" not in got
    assert client.post(f"/workspaces/{ws}/delete", json={"confirm": "nope"}).status_code == 400
    assert client.post(f"/workspaces/{ws}/delete", json={"confirm": ws}).status_code == 200
    assert client.get(f"/workspaces/{ws}").status_code == 404
    assert [t["id"] for t in client.get("/trash").json()] == [ws]
    assert client.post(f"/trash/{ws}/restore").status_code == 200
    assert client.get(f"/workspaces/{ws}").status_code == 200


def test_folders(client: TestClient, tmp_path: Path) -> None:
    ws = create_workspace(client, "Investor")
    reports = tmp_path / "Q3 Reports"
    reports.mkdir()
    # The added folders live in the workspace's Hermes (its docker_volumes): with
    # no engine there is nowhere to keep one (test_engine_sync covers the rest).
    off = client.post(f"/workspaces/{ws}/folders", json={"path": str(reports)})
    assert off.status_code == 409 and "engine is off" in off.json()["detail"]
    refused = client.post(
        f"/workspaces/{ws}/folders", json={"path": str(tmp_path / "data" / "system")}
    )
    assert refused.status_code == 400 and "private" in refused.json()["detail"]
    folders = client.get(f"/workspaces/{ws}/folders").json()
    assert [f["own"] for f in folders] == [True]
    assert client.delete(f"/workspaces/{ws}/folders/q3-reports").status_code == 200


def test_the_old_board_is_gone_and_counters_come_from_the_kanban(client: TestClient) -> None:
    ws = create_workspace(client, "Store")
    for path in (f"/workspaces/{ws}/tasks", f"/workspaces/{ws}/plans"):
        assert client.get(path).status_code == 404
    counters = client.get(f"/workspaces/{ws}/counters").json()
    assert counters == {"working": 0, "waitingForYou": 0, "suggestions": 0, "done": 0, "inbox": 0}
    assert client.get("/workspaces/nope/counters").status_code == 404


def test_chats(client: TestClient) -> None:
    ws = create_workspace(client, "Store")
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Ads"}).json()["id"]
    assert (
        client.post(f"/workspaces/{ws}/chats/{chat}/messages", json={"body": "hello"}).status_code
        == 201
    )
    assert client.get(f"/workspaces/{ws}/chats/{chat}").json()["messages"][0]["body"] == "hello"
    assert (
        client.post(f"/workspaces/{ws}/chats/{chat}/messages", json={"body": ""}).status_code == 400
    )


def test_automations_write_a_file(client: TestClient, tmp_path: Path) -> None:
    ws = create_workspace(client, "Store")
    body = {
        "name": "Daily brief",
        "instructions": "Summarise.",
        "schedule": "0 8 * * *",
        "model": MODEL,
    }
    aid = client.post(f"/workspaces/{ws}/automations", json=body).json()["id"]
    file = tmp_path / "data" / "workspaces" / ws / "automations" / "daily-brief.md"
    assert "Summarise." in file.read_text() and file.stat().st_mode & 0o777 == 0o600
    # No engine: no Hermes to check the schedule (its parser does, test_cron_schedule).
    assert (
        client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False}).status_code
        == 200
    )
    # No Hermes job holds the instructions here (no engine): the file keeps them, as
    # the owner's request; on/off and the schedule too are the request.
    assert "on:" not in file.read_text() and "schedule:" not in file.read_text()
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["on"] is False
    assert client.delete(f"/workspaces/{ws}/automations/{aid}").status_code == 200
    assert not file.exists()


def test_no_login_is_left(client: TestClient) -> None:
    """AGOS is single-user with no login: no password, session or member routes, and
    the internal token between the web app and the core still guards every route."""
    for method, path in (
        ("GET", "/auth/status"),
        ("POST", "/auth/setup"),
        ("POST", "/auth/sign-in"),
        ("POST", "/auth/session"),
        ("POST", "/auth/who"),
        ("GET", "/auth/sessions"),
        ("GET", "/members"),
        ("POST", "/members/sign-in"),
        ("GET", "/member/1"),
    ):
        assert client.request(method, path).status_code in (404, 405), path
    paths = set(client.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert not {p for p in paths if p.startswith(("/auth", "/member"))}
    assert TestClient(client.app).get("/preferences/owner-name").status_code == 401
    assert client.get("/preferences/owner-name").json() == {"name": ""}
