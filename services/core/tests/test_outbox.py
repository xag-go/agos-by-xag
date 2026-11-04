"""The outbox (agos_core/outbox): notifications are rows written inside the change's
transaction and delivered after it by one loop, with retry and backoff. Never sent
before the commit, never lost, never doubled."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.db import outbox as rows
from agos_core.db.connection import open_database
from agos_core.outbox import delivery
from agos_core.uow import UnitOfWork

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def core() -> Any:
    return SimpleNamespace(db=open_database(":memory:"))


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    monkeypatch.setitem(delivery.SENDERS, "test", lambda _core, payload: out.append(payload))
    return out


def _row(db: Any, row_id: int) -> Any:
    """An outbox row as the delivery loop left it (tests read it directly)."""
    return db.execute("SELECT * FROM outbox WHERE id = ?", (row_id,)).fetchone()


def _status(core: Any, row_id: int) -> tuple[str, int]:
    row = _row(core.db, row_id)
    assert row is not None
    return str(row["status"]), int(row["attempts"])


def test_a_queued_notification_goes_out_once(core: Any, sent: list[dict[str, Any]]) -> None:
    row_id = delivery.enqueue(core.db, "test", {"title": "hi"}, dedupe_key="hi:1", now=T0)
    assert row_id is not None
    assert delivery.enqueue(core.db, "test", {"title": "hi"}, dedupe_key="hi:1", now=T0) is None
    assert delivery.deliver_due(core, now=T0) == 1
    assert delivery.deliver_due(core, now=T0 + timedelta(hours=1)) == 0
    assert sent == [{"title": "hi"}]
    assert _status(core, row_id) == ("sent", 1)


def test_nothing_is_queued_when_the_change_rolls_back(
    core: Any, sent: list[dict[str, Any]]
) -> None:
    with pytest.raises(RuntimeError), UnitOfWork(core):
        delivery.enqueue(core.db, "test", {"title": "never"}, now=T0)
        raise RuntimeError("the change failed")
    assert delivery.deliver_due(core, now=T0) == 0
    assert sent == []


def test_a_failed_send_is_retried_later_with_backoff(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tries: list[datetime] = []

    def flaky(_core: Any, payload: dict[str, Any]) -> None:
        tries.append(payload["at"])
        if len(tries) < 3:
            raise ConnectionError("phone service down")

    monkeypatch.setitem(delivery.SENDERS, "flaky", flaky)
    row_id = delivery.enqueue(core.db, "flaky", {"at": "x"}, now=T0)
    assert row_id is not None
    delivery.deliver_due(core, now=T0)
    assert _status(core, row_id) == ("pending", 1)
    row = _row(core.db, row_id)
    assert row is not None and "phone service down" in str(row["last_error"])
    delivery.deliver_due(core, now=T0 + timedelta(seconds=1))  # not due yet
    assert len(tries) == 1
    first_wait = delivery.backoff(1)
    delivery.deliver_due(core, now=T0 + first_wait)
    assert _status(core, row_id) == ("pending", 2)
    assert delivery.backoff(2) > first_wait
    delivery.deliver_due(core, now=T0 + first_wait + delivery.backoff(2))
    assert _status(core, row_id) == ("sent", 3)
    assert len(tries) == 3


def test_after_the_last_try_it_is_failed_and_logged(
    core: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def down(_core: Any, _payload: dict[str, Any]) -> None:
        raise ConnectionError("down for good")

    monkeypatch.setitem(delivery.SENDERS, "down", down)
    row_id = delivery.enqueue(core.db, "down", {}, now=T0)
    assert row_id is not None
    at = T0
    for _ in range(delivery.MAX_ATTEMPTS):
        delivery.deliver_due(core, now=at)
        at += delivery.LONGEST_WAIT
    assert _status(core, row_id) == ("failed", delivery.MAX_ATTEMPTS)
    delivery.deliver_due(core, now=at)
    assert _status(core, row_id) == ("failed", delivery.MAX_ATTEMPTS)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].name.startswith("agos.")


def test_a_channel_without_sender_fails_closed(core: Any) -> None:
    row_id = delivery.enqueue(core.db, "nobody", {}, now=T0)
    assert row_id is not None
    delivery.deliver_due(core, now=T0)
    status, _ = _status(core, row_id)
    assert status == "pending"
    row = _row(core.db, row_id)
    assert row is not None and "nobody" in str(row["last_error"])


def test_a_send_cut_by_a_restart_is_tried_again(core: Any, sent: list[dict[str, Any]]) -> None:
    row_id = delivery.enqueue(core.db, "test", {"n": 1}, now=T0)
    assert row_id is not None
    assert rows.claim(core.db, row_id)  # the core stopped mid-send
    assert delivery.deliver_due(core, now=T0) == 0
    rows.release_claims(core.db)  # at start
    assert delivery.deliver_due(core, now=T0) == 1
    assert sent == [{"n": 1}]


def test_old_sent_rows_go_with_the_daily_retention_not_the_loop(
    core: Any, sent: list[dict[str, Any]]
) -> None:
    from agos_core.background import retention

    old = delivery.enqueue(core.db, "test", {"n": 1}, now=T0)
    delivery.deliver_due(core, now=T0)
    later = T0 + timedelta(days=31)
    new = delivery.enqueue(core.db, "test", {"n": 2}, now=later)
    delivery.deliver_due(core, now=later)
    assert old is not None and new is not None
    assert _row(core.db, old) is not None  # the loop deletes nothing
    retention.run(core, now=later)
    assert _row(core.db, old) is None
    assert _row(core.db, new) is not None


def test_the_loop_delivers_soon_after_a_wake(core: Any, sent: list[dict[str, Any]]) -> None:
    async def scenario() -> None:
        task = asyncio.create_task(delivery.run_forever(core, interval=30.0))
        await asyncio.sleep(0.05)
        delivery.enqueue(core.db, "test", {"n": "woken"})
        delivery.wake()
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert sent == [{"n": "woken"}]
