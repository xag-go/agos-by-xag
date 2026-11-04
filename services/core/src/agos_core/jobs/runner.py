"""The one job loop: claims due jobs with a lease, runs each kind's handler, retries
a failure with backoff (queue.backoff) and dead-letters the last try. A dead letter
is logged as an error on the "agos.jobs" logger, so it lands in the System Log and
Settings → Errors (the existing error pattern; no new screen).

A claim is one SQL statement (one worker per job). A worker that dies mid-run keeps
its job until the lease ends; then another takes it (its try counted), or it is
dead-lettered when that was its last try. At start every lease is let go: the core
is the only worker, so a running job was cut by the restart.

Owns: the kind -> handler table, the lease and the loop. Must not: hold a kind's
work (its service does) or be called inside an open transaction (a handler opens
its own Unit of Work).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.db import jobs as rows
from agos_core.jobs import queue, recurring

__all__ = ["HANDLERS", "LEASE", "Handler", "run_due", "run_forever", "tick"]

log = logging.getLogger("agos.jobs")

Handler = Callable[[Any, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}

LEASE = timedelta(minutes=10)  # longer than any one job takes
INTERVAL = 5.0  # seconds between two looks when nobody wakes the loop
BATCH = 20


def _bury_expired(core: Any, at: datetime) -> None:
    for row in rows.expired(core.db, queue.stamp(at)):
        text = "its worker stopped during its last try"
        rows.mark_dead(core.db, row["workspace_id"], int(row["id"]), queue.stamp(at), text)
        log.error(
            "job %s #%s dead after %s tries: %s", row["kind"], row["id"], row["attempts"], text
        )


def _run_one(core: Any, row: Any, at: datetime) -> bool:
    job_id, kind = int(row["id"]), str(row["kind"])
    attempts = int(row["attempts"])
    try:
        handler = HANDLERS.get(kind)
        if handler is None:
            raise LookupError(f"no handler for the {kind!r} job")
        handler(core, json.loads(row["payload"]))
    except Exception as error:
        text = f"{type(error).__name__}: {error}"
        if attempts >= int(row["max_attempts"]):
            rows.mark_dead(core.db, row["workspace_id"], job_id, queue.stamp(at), text)
            log.error(
                "job %s #%s dead after %s tries: %s",
                kind,
                job_id,
                attempts,
                text,
                exc_info=error,
                extra={"agos_workspace": row["workspace_id"]} if row["workspace_id"] else None,
            )
        else:
            rows.retry_at(
                core.db,
                row["workspace_id"],
                job_id,
                queue.stamp(at + queue.backoff(attempts)),
                text,
            )
            log.info("job %s #%s will be tried again: %s", kind, job_id, text)
        return False
    rows.mark_done(core.db, row["workspace_id"], job_id, queue.stamp(at))
    return True


def run_due(core: Any, *, now: datetime | None = None, limit: int = BATCH) -> int:
    """Runs the due jobs (at most `limit`); returns how many finished well."""
    at = now or datetime.now(UTC)
    _bury_expired(core, at)
    done = 0
    for _ in range(limit):
        row = rows.claim(core.db, queue.stamp(at), queue.stamp(at + LEASE))
        if row is None:
            break
        done += _run_one(core, row, at)
    return done


def tick(core: Any, *, now: datetime | None = None) -> int:
    """One pass of the loop: the recurring work planned, then the due jobs run."""
    recurring.plan(core, now=now)
    return run_due(core, now=now)


async def run_forever(core: Any, *, interval: float = INTERVAL) -> None:
    """The one job loop (started with the core's other loops)."""
    await asyncio.to_thread(rows.release_leases, core.db)
    woken = queue.woken()
    while True:
        woken.clear()
        try:
            await asyncio.to_thread(tick, core)
        except Exception:
            log.exception("the job loop failed once")
        waited = 0.0
        while waited < interval and not woken.is_set():
            await asyncio.sleep(0.2)
            waited += 0.2
