"""Diagnostics for a GitHub issue (actions/diagnostics.py, GET /diagnostics) and the
deep health check (GET /health?deep=1)."""

import logging
from typing import Any

import pytest
import test_api
from fastapi.testclient import TestClient

from agos_core.actions import diagnostics

client = test_api.client  # the API tests' fixture


def core_of(c: TestClient) -> Any:
    return c.app.state.core  # type: ignore[attr-defined]


def test_the_report_holds_versions_health_and_errors(client: TestClient) -> None:
    logging.getLogger("agos.test").error("card 12 failed in /srv/agos/x.json")
    text = client.get("/diagnostics").json()["text"]
    for part in ("AGOS", "Python", "Health", "Workspace isolation", "Backups", "Labs", "Errors"):
        assert part in text
    assert "card <n> failed in <path>" in text  # the normalized line, never the raw one
    assert "/srv/agos" not in text


def test_the_report_holds_no_secret_and_no_personal_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    ws = test_api.create_workspace(client, "Secret Plans Inc")
    client.post(f"/workspaces/{ws}/chats", json={"title": "my divorce lawyer"})
    monkeypatch.setenv("AGOS_TELEGRAM_TOKEN", "123456:ABCdefGhIJKlmnoPQRstuVWXyz0123456789")
    monkeypatch.setenv("AGOS_PROFILE_PREFIX", "agos-")
    logging.getLogger("agos.test").error("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789")
    text = diagnostics.report(core)
    assert "Secret Plans" not in text and "divorce" not in text
    assert "ABCdefGhIJ" not in text and "sk-ant-api03-abc" not in text
    assert "AGOS_TELEGRAM_TOKEN=set" in text
    assert "AGOS_PROFILE_PREFIX=agos-" in text
    assert core.internal_token not in text


def test_the_report_takes_out_unquoted_names_and_addresses(client: TestClient) -> None:
    """The review's Low item: real error text names people and workspaces without
    quotes; the report's normalized line must not carry them."""
    core = core_of(client)
    ws = test_api.create_workspace(client, "Secret Plans Inc")
    client.post(f"/workspaces/{ws}/chats", json={"title": "Moroccan wholesale deal"})
    log = logging.getLogger("agos.test")
    log.error("workspace Secret Plans Inc: gateway did not start for sara.benali@example.com")
    log.error("hire of member Sara Benali failed: provider said no")
    log.error("chat Moroccan wholesale deal could not sync; see https://example.com/x?id=1")
    log.error("Telegram message from @youssef_shop dropped")
    text = diagnostics.report(core)
    for private in (
        "Secret Plans",
        "sara.benali",
        "example.com",
        "Sara Benali",
        "Moroccan wholesale",
        "youssef_shop",
    ):
        assert private not in text, private
    assert "member <name> failed" in text and "<email>" in text


def test_the_api_says_when_it_was_made(client: TestClient) -> None:
    body = client.get("/diagnostics").json()
    assert body["madeAt"].endswith("Z") and body["text"].startswith("## AGOS diagnostics")


def test_health_stays_cheap_and_public(client: TestClient) -> None:
    anonymous = TestClient(client.app)
    assert anonymous.get("/health").json() == {"ok": True}


def test_deep_health_checks_the_database_disk_and_loops(client: TestClient) -> None:
    anonymous = TestClient(client.app)
    answer = anonymous.get("/health", params={"deep": "1"})
    assert answer.status_code == 200
    assert answer.json() == {"ok": True, "database": True, "disk": True, "loops": True}


def test_deep_health_fails_when_a_loop_died(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostics, "loops_alive", lambda _app: False)
    answer = TestClient(client.app).get("/health", params={"deep": "1"})
    assert answer.status_code == 503
    assert answer.json()["ok"] is False and answer.json()["loops"] is False
