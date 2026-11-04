"""Queuing a job and the retry rule (db/jobs.py holds the rows).

`enqueue` writes a job on the caller's connection, so inside a Unit of Work it
commits or rolls back with the change: a rolled-back change queues nothing. A dedupe
key keeps one waiting job per (kind, key). `backoff` says when a failed job is
tried again.

Owns: the retry rule and the stamps' text form. Must not: run a job (runner does)
or know a kind's work (its service does).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.db import jobs as rows

__all__ = ["MAX_ATTEMPTS", "backoff", "enqueue", "stamp", "wake", "woken"]

MAX_ATTEMPTS = 5
FIRST_WAIT = timedelta(seconds=30)
LONGEST_WAIT = timedelta(hours=1)

_wake = threading.Event()


def stamp(at: datetime) -> str:
    """The same text form as db/rows.now(), so stamps compare as strings."""
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def backoff(attempts: int) -> timedelta:
    """How long after the `attempts`-th failed try the next one comes."""
    wait: timedelta = FIRST_WAIT * (2 ** max(attempts - 1, 0))
    return min(wait, LONGEST_WAIT)


def enqueue(
    db: Any,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
    workspace_id: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    now: datetime | None = None,
) -> int | None:
    """Queues one job (due now unless `run_at`); None when this key is waiting already."""
    at = now or datetime.now(UTC)
    job_id = rows.insert(
        db,
        kind,
        payload or {},
        workspace_id=workspace_id,
        dedupe_key=dedupe_key,
        max_attempts=max(1, max_attempts),
        run_at=stamp(run_at or at),
        at=stamp(at),
    )
    wake()
    return job_id


def wake() -> None:
    """Something was queued: the loop looks now instead of at its next interval.
    Safe before the commit: the loop reads committed rows only."""
    _wake.set()


def woken() -> threading.Event:
    return _wake
