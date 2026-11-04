"""Saga (agos_core/saga.py): a multi-step change that touches Hermes. A failed step
undoes the done ones in reverse; a step allowed to fail leaves the saga "needs
attention" with its journal, so a later sync can finish it; a compensation that
fails is recorded and logged, never swallowed."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agos_core.db import sagas as journal
from agos_core.db.connection import open_database
from agos_core.saga import Saga


class _Core:
    def __init__(self) -> None:
        self.db = open_database(":memory:")


@pytest.fixture
def core() -> Any:
    return _Core()


def _status(core: Any, saga_id: int) -> str:
    row = journal.get(core.db, saga_id)
    assert row is not None
    return str(row["status"])


def _steps(core: Any, saga_id: int) -> list[tuple[str, str]]:
    return [(s["name"], s["status"]) for s in journal.steps(core.db, saga_id)]


def test_every_step_done_is_journaled_and_the_saga_ends_done(core: Any) -> None:
    with Saga(core, "thing.create") as saga:
        assert saga.step("first", lambda: 1) == 1
        assert saga.step("second", lambda: "two") == "two"
    assert _status(core, saga.id) == "done"
    assert _steps(core, saga.id) == [("first", "done"), ("second", "done")]


def test_a_failed_step_undoes_the_done_ones_in_reverse(
    core: Any, caplog: pytest.LogCaptureFixture
) -> None:
    undone: list[Any] = []

    def boom() -> None:
        raise RuntimeError("Hermes refused")

    with pytest.raises(RuntimeError, match="Hermes refused"), Saga(core, "thing.create") as saga:
        saga.step("folder", lambda: "f", undo=undone.append)
        saga.step("row", lambda: "r", undo=undone.append)
        saga.step("hermes", boom, undo=undone.append)
    assert undone == ["r", "f"]
    assert _status(core, saga.id) == "compensated"
    assert _steps(core, saga.id) == [
        ("folder", "compensated"),
        ("row", "compensated"),
        ("hermes", "failed"),
    ]
    assert any(
        r.levelno == logging.ERROR and "thing.create" in r.getMessage() for r in caplog.records
    )


def test_a_failed_compensation_is_journaled_and_the_rest_still_runs(
    core: Any, caplog: pytest.LogCaptureFixture
) -> None:
    undone: list[str] = []

    def stuck(_: object) -> None:
        raise OSError("folder busy")

    with pytest.raises(ValueError), Saga(core, "thing.delete", workspace_id=None) as saga:
        saga.step("first", lambda: "a", undo=lambda _: undone.append("first"))
        saga.step("second", lambda: "b", undo=stuck)
        raise ValueError("between steps")
    assert undone == ["first"]
    row = journal.get(core.db, saga.id)
    assert row is not None and row["status"] == "compensation_failed"
    assert "folder busy" in str(row["error"])
    assert _steps(core, saga.id) == [("first", "compensated"), ("second", "compensation_failed")]
    assert saga.failed_compensations == ["second: folder busy"]
    assert any(
        "folder busy" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    )


def test_a_tolerated_failure_needs_attention_and_resume_finishes_it(
    core: Any, caplog: pytest.LogCaptureFixture
) -> None:
    def refuses() -> None:
        raise ConnectionError("Hermes busy")

    with Saga(core, "thing.create", data={"model": "m"}) as saga:
        saga.step("row", lambda: "r")
        assert saga.step("sync", refuses, tolerate=(ConnectionError,)) is None
        saga.step("after", lambda: "a")
    assert saga.unfinished == ["sync"]
    assert _status(core, saga.id) == "needs_attention"
    assert _steps(core, saga.id) == [("row", "done"), ("sync", "failed"), ("after", "done")]
    assert any(r.levelno == logging.WARNING and "sync" in r.getMessage() for r in caplog.records)
    assert [s["id"] for s in journal.open_sagas(core.db, "thing.create")] == [saga.id]
    assert journal.data_of(core.db, saga.id) == {"model": "m"}

    still = Saga.resume(core, saga.id, {"sync": refuses})
    assert still == ["sync"]
    assert _status(core, saga.id) == "needs_attention"
    ran: list[str] = []
    assert Saga.resume(core, saga.id, {"sync": lambda: ran.append("sync")}) == []
    assert ran == ["sync"]
    assert _status(core, saga.id) == "done"
    assert journal.open_sagas(core.db, "thing.create") == []


def test_an_untolerated_error_of_a_tolerating_step_still_compensates(core: Any) -> None:
    undone: list[str] = []

    def broken() -> None:
        raise KeyError("bug")

    with pytest.raises(KeyError), Saga(core, "thing.create") as saga:
        saga.step("row", lambda: "r", undo=lambda _: undone.append("row"))
        saga.step("sync", broken, tolerate=(ConnectionError,))
    assert undone == ["row"]
