"""Queuing and delivering outbox rows (db/outbox.py).

`enqueue` writes a row on the caller's connection, so inside a Unit of Work it
commits or rolls back with the change: nothing goes out before the commit, and a
rolled-back change sends nothing. `run_forever` is the one delivery loop: it sends
what is due through the channel's sender (`SENDERS`), retries a failed send with
exponential backoff up to `MAX_ATTEMPTS`, then marks it failed and logs it to the
System Log. A row is claimed before its send (one sender per row) and a dedupe key
keeps one row per notification, so nothing is sent twice.

Owns: the retry rule, the loop and the channel -> sender table. Must not: build a
channel's payload or know how a channel sends (its sender does).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.db import outbox as rows

__all__ = [
    "MAX_ATTEMPTS",
    "SENDERS",
    "Sender",
    "backoff",
    "deliver_due",
    "enqueue",
    "run_forever",
    "wake",
]

log = logging.getLogger("agos.outbox")

Sender = Callable[[Any, dict[str, Any]], None]
SENDERS: dict[str, Sender] = {}

MAX_ATTEMPTS = 8
FIRST_WAIT = timedelta(seconds=30)
LONGEST_WAIT = timedelta(hours=1)
INTERVAL = 5.0  # seconds between two looks when nobody wakes the loop
BATCH = 50

_wake = threading.Event()


def _stamp(at: datetime) -> str:
    """The same text form as db/rows.now(), so stamps compare as strings."""
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def backoff(attempts: int) -> timedelta:
    """How long after the `attempts`-th failed try the next one comes."""
    wait: timedelta = FIRST_WAIT * (2 ** max(attempts - 1, 0))
    return min(wait, LONGEST_WAIT)


def enqueue(
    db: Any,
    channel: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
    dedupe_key: str | None = None,
    now: datetime | None = None,
) -> int | None:
    """Queues one notification; None when its dedupe key is already queued."""
    return rows.insert(
        db,
        channel,
        payload,
        workspace_id=workspace_id,
        dedupe_key=dedupe_key,
        at=_stamp(now or datetime.now(UTC)),
    )


def wake() -> None:
    """Something was queued: the loop looks now instead of at its next interval.
    Safe before the commit: the loop reads committed rows only."""
    _wake.set()


def deliver_due(core: Any, *, now: datetime | None = None) -> int:
    """Sends every due row once; returns how many went out."""
    at = now or datetime.now(UTC)
    sent = 0
    for row in rows.due(core.db, _stamp(at), BATCH):
        row_id = int(row["id"])
        if not rows.claim(core.db, row_id):
            continue
        attempts = int(row["attempts"]) + 1
        channel = str(row["channel"])
        try:
            sender = SENDERS.get(channel)
            if sender is None:
                raise LookupError(f"no sender for the {channel!r} channel")
            sender(core, json.loads(row["payload"]))
        except Exception as error:
            text = f"{type(error).__name__}: {error}"
            last = attempts >= MAX_ATTEMPTS
            if last:
                rows.mark_failed(core.db, row_id, text)
            else:
                rows.retry_at(core.db, row_id, _stamp(at + backoff(attempts)), text)
            # The last try is an error of AGOS (System Log); a retry is only noted.
            log.log(
                logging.ERROR if last else logging.INFO,
                "outbox %s #%s %s: %s",
                channel,
                row_id,
                f"not sent after {attempts} tries" if last else "will be tried again",
                text,
                exc_info=True,
            )
            continue
        rows.mark_sent(core.db, row_id, _stamp(at))
        sent += 1
    return sent  # old rows: the daily retention job (agos_core/background/retention.py)


async def run_forever(core: Any, *, interval: float = INTERVAL) -> None:
    """The one delivery loop (started with the core's other loops)."""
    await asyncio.to_thread(rows.release_claims, core.db)
    while True:
        _wake.clear()
        try:
            await asyncio.to_thread(deliver_due, core)
        except Exception:
            log.exception("the outbox loop failed once")
        waited = 0.0
        while waited < interval and not _wake.is_set():
            await asyncio.sleep(0.2)
            waited += 0.2
