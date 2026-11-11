"""Settings → General → Updates: one check and one run for AGOS and the engine
together, through the two existing update actions (their backups, fit checks and
rollbacks), AGOS first. The old /agos-update and /hermes-update endpoints stay."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agos_core.actions import agos_update, hermes_update, updates
from agos_core.actions.errors import ActionError
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.db import op_runs
from agos_core.db.app_settings import set_setting
from agos_core.ops.operation import OWNER
from agos_core.ops.registry import REGISTRY

AGOS_READY: dict[str, Any] = {
    "at": "2026-11-04T10:00:00+00:00",
    "ref": "main",
    "channel": "main",
    "release": None,
    "current": "aaaa",
    "target": "bbbb",
    "target_version": "0.2.0",
    "news": ["Faster board"],
    "hermes_changes": False,
}
AGOS_CURRENT: dict[str, Any] = {**AGOS_READY, "target": None, "news": []}
ENGINE_READY: dict[str, Any] = {
    "at": "2026-11-04T10:00:00+00:00",
    "current": {"version": "0.22.2", "sha": "d923a5eb"},
    "target": {"version": "0.22.3", "sha": "feedc0ff"},
    "fits": True,
    "report": "",
    "news": ["aaaa111 One fix"],
}
ENGINE_CURRENT: dict[str, Any] = {**ENGINE_READY, "target": None, "news": []}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, Any]]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=None,
    )
    application = create_app(settings, background=False)
    with TestClient(application) as c:
        c.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        yield c, application.state.core


def _with_engine(core: Any) -> None:
    object.__setattr__(core, "engine", object())  # Core is a frozen dataclass


def test_check_is_ready_when_either_part_has_an_update(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, core = client
    _with_engine(core)
    monkeypatch.setattr(agos_update, "run_check", lambda core: AGOS_CURRENT)
    monkeypatch.setattr(hermes_update, "run_check", lambda core: ENGINE_READY)
    found = c.post("/updates/check")
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["ready"] is True
    assert body["note"] == "An update is ready."
    # the two parts' own records ride along for the popup's detail
    assert body["agos"] == AGOS_CURRENT
    assert body["engine"] == ENGINE_READY


def test_check_says_up_to_date_when_nothing_is_new(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, core = client
    _with_engine(core)
    monkeypatch.setattr(agos_update, "run_check", lambda core: AGOS_CURRENT)
    monkeypatch.setattr(hermes_update, "run_check", lambda core: ENGINE_CURRENT)
    body = c.post("/updates/check").json()
    assert body["ready"] is False
    assert body["note"] == "You're up to date."


def test_check_without_the_installer_still_checks_the_engine(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, core = client
    _with_engine(core)

    def refuse(core: Any) -> dict[str, Any]:
        raise ActionError(
            "This AGOS wasn't installed with the installer: update it the way you installed it."
        )

    monkeypatch.setattr(agos_update, "run_check", refuse)
    monkeypatch.setattr(hermes_update, "run_check", lambda core: ENGINE_READY)
    body = c.post("/updates/check").json()
    assert body["ready"] is True
    assert body["agos"] is None
    assert "installed" in body["agos_note"]
    assert body["engine"] == ENGINE_READY


def test_check_without_the_engine_keeps_a_neutral_note(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, _core = client  # the fixture's core has no engine
    monkeypatch.setattr(agos_update, "run_check", lambda core: AGOS_CURRENT)
    body = c.post("/updates/check").json()
    assert body["ready"] is False
    assert body["engine"] is None
    assert "hermes" not in body["engine_note"].lower()
    assert "hermes" not in body["note"].lower()


def test_check_refuses_while_an_update_runs(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _core = client

    def busy(core: Any) -> dict[str, Any]:
        raise ActionError("An update is running.")

    monkeypatch.setattr(agos_update, "run_check", busy)
    refused = c.post("/updates/check")
    assert refused.status_code == 400
    assert refused.json()["detail"] == "An update is already running."


def test_check_with_neither_part_available_refuses(client: Any) -> None:
    # no installer conf and no engine: nothing can be checked
    refused = c_post_check(client)
    assert refused.status_code == 400
    assert "hermes" not in refused.json()["detail"].lower()


def c_post_check(client: Any) -> Any:
    c, _core = client
    return c.post("/updates/check")


def test_run_does_agos_first(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, core = client
    set_setting(core.db, agos_update.KEY_CHECK, AGOS_READY)
    set_setting(core.db, hermes_update.KEY_CHECK, ENGINE_READY)
    started: list[str] = []
    monkeypatch.setattr(
        agos_update, "start_update", lambda core: started.append("agos") or {"phase": "queued"}
    )
    monkeypatch.setattr(
        hermes_update,
        "start_update",
        lambda core: pytest.fail("the engine's update must wait for AGOS's"),
    )
    answer = c.post("/updates/run")
    assert answer.status_code == 200, answer.text
    assert started == ["agos"]
    assert answer.json()["part"] == "agos"
    assert answer.json()["state"] == {"phase": "queued"}


def test_run_updates_the_engine_when_agos_is_current(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, core = client
    set_setting(core.db, hermes_update.KEY_CHECK, ENGINE_READY)
    monkeypatch.setattr(hermes_update, "start_update", lambda core: {"phase": "starting"})
    answer = c.post("/updates/run")
    assert answer.status_code == 200, answer.text
    assert answer.json()["part"] == "engine"
    assert answer.json()["state"] == {"phase": "starting"}


def test_run_without_a_check_refuses(client: Any) -> None:
    c, _core = client
    refused = c.post("/updates/run")
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Check for an update first."


def test_status_merges_both_parts(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _core = client
    monkeypatch.setattr(agos_update, "status", lambda core: {"state": {"phase": "build"}})
    monkeypatch.setattr(hermes_update, "status", lambda core: {"state": None})
    body = c.get("/updates").json()
    assert body["agos"] == {"state": {"phase": "build"}}
    assert body["engine"] == {"state": None}


def test_the_old_endpoints_still_answer(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _core = client
    monkeypatch.setattr(agos_update, "status", lambda core: {"state": None})
    assert c.get("/agos-update").status_code == 200
    assert c.get("/hermes-update").status_code == 200


def test_check_updates_and_run_updates_are_declared_operations() -> None:
    specs = {s.name: s for s in REGISTRY.specs()}
    check, run = specs["check_updates"], specs["run_updates"]
    assert check.gate == "once" and check.effect == "read"
    assert run.gate == "owner" and run.effect == "power"
    for spec in (check, run):
        assert spec.cofounder_domain is not None  # Co-Founder parity
        assert "hermes" not in spec.audit_title.lower()


def test_the_cofounder_runs_check_updates_with_an_audit_row(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agos_core.actions.settings_ops  # noqa: F401 - binds the operations

    _c, core = client
    monkeypatch.setattr(updates, "run_check", lambda core: {"ready": False})
    REGISTRY.run(core, "check_updates", {}, actor=OWNER, workspace_id="ws-a")
    run = op_runs.latest(core.db, "check_updates")
    assert run is not None and run["status"] == "done"


def test_run_updates_runs_the_combined_update_with_an_audit_row(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agos_core.actions.settings_ops  # noqa: F401 - binds the operations

    _c, core = client
    ran: list[str] = []
    monkeypatch.setattr(updates, "start_update", lambda core: ran.append("run") or {"part": "agos"})
    REGISTRY.run(core, "run_updates", {}, actor=OWNER, workspace_id="ws-a")
    assert ran == ["run"]
    run = op_runs.latest(core.db, "run_updates")
    assert run is not None and run["status"] == "done"
