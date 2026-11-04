"""Recurring background work as jobs: the next job of each kind in `EVERY` is queued
once the last one finished, `interval` after it (at once the first time). A dead
job still counts as finished, so a failing chore keeps its rhythm and its errors
show in Settings → Errors.

Owns: the kind -> interval table and the planning rule. Must not: hold a kind's
work (its service registers the handler, actions/background_jobs.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.db import jobs as rows
from agos_core.jobs import queue

__all__ = ["EVERY", "Recurring", "plan"]


@dataclass(frozen=True)
class Recurring:
    """`interval` after the last one finished; `attempts` tries before it is a dead
    letter (1 for a chore whose next round comes soon anyway)."""

    interval: timedelta
    attempts: int = 1


EVERY: dict[str, Recurring] = {}

ROUND = "every"  # the dedupe key of a recurring kind's waiting job


def plan(core: Any, *, now: datetime | None = None) -> list[str]:
    """Queues the next job of every recurring kind that has none waiting; returns them."""
    at = now or datetime.now(UTC)
    planned: list[str] = []
    for kind, every in list(EVERY.items()):
        if rows.active(core.db, kind):
            continue
        last = rows.last_finished_at(core.db, kind)
        due = at
        if last is not None:
            due = max(at, datetime.fromisoformat(last.replace("Z", "+00:00")) + every.interval)
        queued = queue.enqueue(
            core.db,
            kind,
            {},
            run_at=due,
            dedupe_key=ROUND,
            max_attempts=every.attempts,
            now=at,
        )
        if queued is not None:
            planned.append(kind)
    return planned
