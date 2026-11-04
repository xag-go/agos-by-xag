"""Unit of Work (agos_core/uow.py): one SQL transaction, the compensations of the
side effects done inside it (run in reverse when it rolls back) and the hooks and
domain events that run only once it committed."""

from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core import events
from agos_core.db.connection import open_database
from agos_core.uow import UnitOfWork


@pytest.fixture
def core() -> Any:
    db = open_database(":memory:")
    db.execute("CREATE TABLE t (v TEXT)")
    return SimpleNamespace(db=db)


def _values(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute("SELECT v FROM t ORDER BY v").fetchall()]


def test_all_writes_commit_together_and_after_commit_hooks_run_once(core: Any) -> None:
    seen: list[str] = []
    with UnitOfWork(core) as uow:
        core.db.execute("INSERT INTO t VALUES ('a')")
        uow.after_commit(lambda: seen.append(f"after:{_values(core.db)}"))
        core.db.execute("INSERT INTO t VALUES ('b')")
        assert seen == []  # never before the commit
    assert _values(core.db) == ["a", "b"]
    assert seen == ["after:['a', 'b']"]


def test_a_failure_rolls_back_every_write_and_runs_compensations_in_reverse(core: Any) -> None:
    undone: list[str] = []
    after: list[str] = []
    with pytest.raises(RuntimeError, match="boom"), UnitOfWork(core) as uow:
        core.db.execute("INSERT INTO t VALUES ('a')")
        uow.on_rollback(lambda: undone.append("first"))
        uow.on_rollback(lambda: undone.append("second"))
        uow.after_commit(lambda: after.append("never"))
        raise RuntimeError("boom")
    assert _values(core.db) == []
    assert undone == ["second", "first"]
    assert after == []


def test_a_failed_compensation_is_logged_and_the_others_still_run(
    core: Any, caplog: pytest.LogCaptureFixture
) -> None:
    undone: list[str] = []

    def broken() -> None:
        raise OSError("disk gone")

    with pytest.raises(RuntimeError), UnitOfWork(core, name="make thing") as uow:
        uow.on_rollback(lambda: undone.append("first"))
        uow.on_rollback(broken, "broken")
        raise RuntimeError("boom")
    assert undone == ["first"]
    assert uow.failed_compensations == ["broken: disk gone"]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "make thing" in errors[0].getMessage()
    assert errors[0].name.startswith("agos.")  # lands in the System Log


def test_a_nested_unit_hands_its_hooks_to_the_outer_one(core: Any) -> None:
    after: list[str] = []
    undone: list[str] = []
    with pytest.raises(RuntimeError), UnitOfWork(core) as outer:
        with UnitOfWork(core) as inner:
            core.db.execute("INSERT INTO t VALUES ('inner')")
            inner.after_commit(lambda: after.append("inner"))
            inner.on_rollback(lambda: undone.append("inner"))
        assert after == []  # the outer transaction has not committed yet
        outer.on_rollback(lambda: undone.append("outer"))
        raise RuntimeError("outer fails")
    assert _values(core.db) == []
    assert after == []
    assert undone == ["outer", "inner"]


def test_a_nested_unit_that_fails_alone_keeps_the_outer_work(core: Any) -> None:
    undone: list[str] = []
    with UnitOfWork(core):
        core.db.execute("INSERT INTO t VALUES ('outer')")
        with pytest.raises(RuntimeError), UnitOfWork(core) as inner:
            core.db.execute("INSERT INTO t VALUES ('inner')")
            inner.on_rollback(lambda: undone.append("inner"))
            raise RuntimeError("inner fails")
    assert _values(core.db) == ["outer"]
    assert undone == ["inner"]


def test_events_are_published_only_after_commit(core: Any) -> None:
    got: list[events.Event] = []
    stop = events.subscribe("thing.made", lambda _core, event: got.append(event))
    try:
        with UnitOfWork(core) as uow:
            uow.publish(events.Event("thing.made", "ws-1", {"id": 7}))
            assert got == []
        assert got == [events.Event("thing.made", "ws-1", {"id": 7})]
        with pytest.raises(RuntimeError), UnitOfWork(core) as uow:
            uow.publish(events.Event("thing.made", "ws-1", {"id": 8}))
            raise RuntimeError("rolled back")
        assert len(got) == 1  # a rolled-back change tells nobody
    finally:
        stop()


def test_a_failing_after_commit_hook_never_undoes_the_commit(
    core: Any, caplog: pytest.LogCaptureFixture
) -> None:
    def broken() -> None:
        raise ValueError("hook broke")

    ran: list[str] = []
    with UnitOfWork(core) as uow:
        core.db.execute("INSERT INTO t VALUES ('kept')")
        uow.after_commit(broken)
        uow.after_commit(lambda: ran.append("next"))
    assert _values(core.db) == ["kept"]
    assert ran == ["next"]
    assert any("hook broke" in r.getMessage() or r.exc_info for r in caplog.records)
