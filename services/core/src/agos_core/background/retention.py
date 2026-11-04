"""Retention: one daily job deletes AGOS's old machine records, never the owner's
content (docs/operations.md, ADR 0026). Owner default, applied (he may change it):

| table          | what goes                                  | after    |
| -------------- | ------------------------------------------ | -------- |
| system_log     | AGOS's own warning/error lines             | 90 days  |
| op_runs        | finished operation runs (audit, keys)      | 180 days |
| outbox         | delivered notifications (failed ones stay) | 30 days  |
| jobs           | finished jobs (done or dead letters)       | 30 days  |
| sagas          | journals of completed sagas (+ steps)      | 90 days  |
| slo_samples    | measured SLI samples                       | 400 days |

Chats, cards, Inbox items, activity, files, settings and everything Hermes keeps
are his content: never touched here. Each table's own repository deletes its rows.

Owns: the policy table and the daily job's work. Must not: delete any table not in
`TABLES`, or decide a row's age by anything but its own stamp.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.db import jobs as jobs_rows
from agos_core.db import op_runs, outbox, sagas, slo_samples, system_log
from agos_core.jobs import queue

__all__ = ["KIND", "POLICY", "TABLES", "run"]

log = logging.getLogger("agos.retention")

KIND = "retention.daily"

Prune = Callable[[Any, str], int]

# table -> (kept this long, its repository's delete of older rows)
POLICY: dict[str, tuple[timedelta, Prune]] = {
    "system_log": (timedelta(days=90), system_log.prune_before),
    "op_runs": (timedelta(days=180), op_runs.prune_finished),
    "outbox": (timedelta(days=30), outbox.prune),
    "jobs": (timedelta(days=30), jobs_rows.prune_finished),
    "sagas": (timedelta(days=90), sagas.prune_completed),
    "slo_samples": (timedelta(days=400), slo_samples.prune_before),
}
TABLES = tuple(POLICY)


def run(core: Any, *, now: datetime | None = None) -> dict[str, int]:
    """Deletes what the policy says; returns how many rows went per table."""
    at = now or datetime.now(UTC)
    gone = {
        table: prune(core.db, queue.stamp(at - keep)) for table, (keep, prune) in POLICY.items()
    }
    if any(gone.values()):
        log.info("retention: %s", ", ".join(f"{t} {n}" for t, n in gone.items() if n))
    return gone
