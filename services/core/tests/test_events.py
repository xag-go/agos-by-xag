"""Domain events (agos_core/events.py): sync, in-process subscribers; one that fails
never stops the others nor the change that published it."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agos_core import events


def test_subscribers_of_a_kind_get_its_events_in_order() -> None:
    got: list[tuple[str, Any]] = []
    core = object()
    stop_a = events.subscribe("card.moved", lambda c, e: got.append(("a", e.data["card"])))
    stop_b = events.subscribe("card.moved", lambda c, e: got.append(("b", c is core)))
    stop_other = events.subscribe("member.hired", lambda c, e: got.append(("other", e)))
    try:
        events.publish(core, events.Event("card.moved", "ws", {"card": "t1"}))
    finally:
        stop_a(), stop_b(), stop_other()
    assert got == [("a", "t1"), ("b", True)]


def test_unsubscribed_handlers_hear_nothing() -> None:
    got: list[events.Event] = []
    stop = events.subscribe("card.moved", lambda c, e: got.append(e))
    stop()
    events.publish(None, events.Event("card.moved", "ws"))
    assert got == []


def test_a_broken_subscriber_is_logged_and_the_next_still_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    got: list[str] = []

    def broken(_core: Any, _event: events.Event) -> None:
        raise RuntimeError("subscriber broke")

    stops = [
        events.subscribe("run.finished", broken),
        events.subscribe("run.finished", lambda c, e: got.append("next")),
    ]
    try:
        events.publish(None, events.Event("run.finished", "ws-9"))
    finally:
        for stop in stops:
            stop()
    assert got == ["next"]
    record = next(r for r in caplog.records if r.levelno == logging.ERROR)
    assert record.name.startswith("agos.")
    assert getattr(record, "agos_workspace", None) == "ws-9"  # the workspace's own Log
