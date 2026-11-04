"""The durable job queue (agos_core/jobs, migration 147): AGOS's own background work
as rows. A job is claimed with a lease (one worker at a time; a worker that died
lets it go when the lease ends), retried with backoff when it fails, and kept as a
dead letter after its last try (an error in the System Log, so Settings → Errors
shows it). Recurring work (the idle round, retention, the trash) is planned as the
next job of its kind once the last one finished."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.db import jobs as rows
from agos_core.db.connection import open_database
from agos_core.jobs import queue, recurring, runner
from agos_core.uow import UnitOfWork

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def core() -> Any:
    return SimpleNamespace(db=open_database(":memory:"))


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    monkeypatch.setitem(runner.HANDLERS, "test.ok", lambda _core, payload: out.append(payload))
    return out


def _row(core: Any, job_id: int) -> Any:
    row = core.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    return row


def test_a_job_runs_once_and_is_done(core: Any, ran: list[dict[str, Any]]) -> None:
    job = queue.enqueue(core.db, "test.ok", {"n": 1}, now=T0)
    assert job is not None
    assert runner.run_due(core, now=T0) == 1
    assert runner.run_due(core, now=T0 + timedelta(hours=1)) == 0
    assert ran == [{"n": 1}]
    row = _row(core, job)
    assert (row["status"], row["attempts"]) == ("done", 1)
    assert row["finished_at"] is not None


def test_a_dedupe_key_keeps_one_waiting_job(core: Any, ran: list[dict[str, Any]]) -> None:
    assert queue.enqueue(core.db, "test.ok", {}, dedupe_key="k", now=T0) is not None
    assert queue.enqueue(core.db, "test.ok", {}, dedupe_key="k", now=T0) is None
    runner.run_due(core, now=T0)
    # Once done, the same key may be queued again (the next round).
    assert queue.enqueue(core.db, "test.ok", {}, dedupe_key="k", now=T0) is not None


def test_a_job_queued_in_a_change_that_rolls_back_never_runs(
    core: Any, ran: list[dict[str, Any]]
) -> None:
    with pytest.raises(RuntimeError), UnitOfWork(core):
        queue.enqueue(core.db, "test.ok", {"n": 1}, now=T0)
        raise RuntimeError("the change failed")
    assert runner.run_due(core, now=T0) == 0
    assert ran == []


def test_a_job_due_later_waits(core: Any, ran: list[dict[str, Any]]) -> None:
    queue.enqueue(core.db, "test.ok", {}, run_at=T0 + timedelta(minutes=5), now=T0)
    assert runner.run_due(core, now=T0) == 0
    assert runner.run_due(core, now=T0 + timedelta(minutes=5)) == 1


def test_a_failed_job_is_retried_with_backoff_then_dead_lettered(
    core: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tries: list[int] = []

    def fails(_core: Any, _payload: dict[str, Any]) -> None:
        tries.append(1)
        raise OSError("disk full")

    monkeypatch.setitem(runner.HANDLERS, "test.fails", fails)
    job = queue.enqueue(core.db, "test.fails", {}, max_attempts=3, now=T0)
    assert job is not None
    assert runner.run_due(core, now=T0) == 0
    row = _row(core, job)
    assert row["status"] == "pending" and "disk full" in row["last_error"]
    assert row["run_at"] == queue.stamp(T0 + queue.backoff(1))
    assert runner.run_due(core, now=T0 + timedelta(seconds=1)) == 0  # not due yet
    at = T0 + queue.backoff(1)
    runner.run_due(core, now=at)
    at += queue.backoff(2)
    with caplog.at_level(logging.ERROR, logger="agos.jobs"):
        runner.run_due(core, now=at)
    assert len(tries) == 3
    row = _row(core, job)
    assert row["status"] == "dead" and row["attempts"] == 3
    # The dead letter is an AGOS error: the System Log, so Settings → Errors lists it.
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "test.fails" in record.getMessage() and "disk full" in record.getMessage()
    assert runner.run_due(core, now=at + timedelta(days=1)) == 0  # never again
    assert [int(r["id"]) for r in rows.dead(core.db, 10)] == [job]


def test_backoff_doubles_up_to_an_hour() -> None:
    assert queue.backoff(1) == timedelta(seconds=30)
    assert queue.backoff(2) == timedelta(seconds=60)
    assert queue.backoff(20) == timedelta(hours=1)


def test_a_kind_nobody_handles_is_a_failure_not_a_crash(core: Any) -> None:
    job = queue.enqueue(core.db, "test.nobody", {}, max_attempts=1, now=T0)
    assert job is not None
    assert runner.run_due(core, now=T0) == 0
    assert _row(core, job)["status"] == "dead"


def test_a_claimed_job_is_one_workers_until_its_lease_ends(
    core: Any, ran: list[dict[str, Any]]
) -> None:
    job = queue.enqueue(core.db, "test.ok", {}, now=T0)
    assert job is not None
    claimed = rows.claim(core.db, queue.stamp(T0), queue.stamp(T0 + runner.LEASE))
    assert claimed is not None and int(claimed["id"]) == job
    # A second worker finds nothing while the lease holds...
    assert rows.claim(core.db, queue.stamp(T0), queue.stamp(T0 + runner.LEASE)) is None
    assert runner.run_due(core, now=T0 + timedelta(minutes=1)) == 0
    # ...and takes it once the first one's lease ended (it died mid-run).
    assert runner.run_due(core, now=T0 + runner.LEASE + timedelta(seconds=1)) == 1
    row = _row(core, job)
    assert (row["status"], row["attempts"]) == ("done", 2)


def test_a_job_whose_worker_died_on_its_last_try_is_dead_lettered(
    core: Any, ran: list[dict[str, Any]]
) -> None:
    job = queue.enqueue(core.db, "test.ok", {}, max_attempts=1, now=T0)
    assert job is not None
    rows.claim(core.db, queue.stamp(T0), queue.stamp(T0 + runner.LEASE))
    assert runner.run_due(core, now=T0 + runner.LEASE + timedelta(seconds=1)) == 0
    assert _row(core, job)["status"] == "dead"
    assert ran == []


def test_at_start_a_run_cut_by_a_restart_is_tried_again(
    core: Any, ran: list[dict[str, Any]]
) -> None:
    job = queue.enqueue(core.db, "test.ok", {}, now=T0)
    assert job is not None
    rows.claim(core.db, queue.stamp(T0), queue.stamp(T0 + runner.LEASE))
    assert rows.release_leases(core.db) == 1
    assert runner.run_due(core, now=T0) == 1


def test_recurring_work_is_planned_after_the_last_one_finished(
    core: Any, ran: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(recurring.EVERY, "test.ok", recurring.Recurring(timedelta(minutes=10)))
    assert recurring.plan(core, now=T0) == ["test.ok"]
    assert recurring.plan(core, now=T0) == []  # one waiting already
    assert runner.run_due(core, now=T0) == 1
    assert recurring.plan(core, now=T0 + timedelta(minutes=1)) == ["test.ok"]
    assert runner.run_due(core, now=T0 + timedelta(minutes=1)) == 0  # due 10 min after
    assert runner.run_due(core, now=T0 + timedelta(minutes=10)) == 1
    assert len(ran) == 2


def test_the_loop_plans_and_runs_recurring_work(
    core: Any, ran: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(recurring.EVERY, "test.ok", recurring.Recurring(timedelta(minutes=10)))
    assert runner.tick(core, now=T0) == 1
    assert runner.tick(core, now=T0 + timedelta(minutes=2)) == 0
    assert runner.tick(core, now=T0 + timedelta(minutes=11)) == 1
