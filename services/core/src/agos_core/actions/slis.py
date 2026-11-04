"""The measured SLIs of docs/compliance/sre.md, written as `slo_samples` rows
(db/slo_samples.py) for `scripts/slo.py`'s monthly report:

- S1 page: the web's time to first byte from the core's host (`probe`, every 5 min,
  the "slo.probes" job: agos_core/background/schedule.py);
- S2 first output: owner message sent -> first visible output of the turn (an
  activity line or reply text), recorded once per turn when it ends (`first_output`);
- S3 health: the core's own `/health` over HTTP (`probe`, every minute); a minute
  with no sample counts as down in the report (the core was not there to probe);
- S4 automation delay: a scheduled run's due time vs when Hermes's scheduler started
  it, from Hermes's own dispatch stamp (`last_dispatch`), once per run
  (`automation_delays`, every 5 min).

Owns: how each SLI is measured and its sample. Must not: judge a sample against
its SLO (scripts/slo.py does) or tell the owner anything.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from agos_core.db import chat_turns
from agos_core.db import slo_samples as samples
from agos_core.db.rows import now

__all__ = [
    "ON_TIME_MS",
    "automation_delays",
    "first_output",
    "probe",
    "probe_targets",
    "turn_ended",
]

log = logging.getLogger("agos.slis")

ON_TIME_MS = 120_000  # S4: a run that starts within 2 min of its due time is on time
PROBE_TIMEOUT = 10.0


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        found = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def first_output(
    core: Any, workspace_id: str, turn_id: int, started: datetime | None, first: datetime | None
) -> bool:
    """S2: one sample per turn (True when written); none when nothing was shown."""
    if started is None or first is None:
        return False
    ms = max(0, int((first - started).total_seconds() * 1000))
    return samples.add(
        core.db,
        "first_output",
        at=_stamp(first),
        value_ms=ms,
        subject=f"turn:{turn_id}",
        workspace_id=workspace_id,
        once_key=f"turn:{turn_id}",
    )


def turn_ended(core: Any, workspace_id: str, turn_id: int, first: datetime | None) -> bool:
    """S2 at a turn's end: from its start (chat_turns.started_at) to `first`."""
    return first_output(
        core, workspace_id, turn_id, _when(chat_turns.started_at(core.db, turn_id)), first
    )


def automation_delays(core: Any, workspace_id: str, jobs: list[dict[str, Any]]) -> int:
    """S4: each scheduled run Hermes dispatched (its `last_dispatch` stamp: due and
    started), once; returns how many were new."""
    added = 0
    for job in jobs:
        due, started = _when(job.get("dispatched_for")), _when(job.get("dispatched_at"))
        if due is None or started is None:
            continue
        ms = max(0, int((started - due).total_seconds() * 1000))
        added += samples.add(
            core.db,
            "automation_delay",
            at=_stamp(started),
            value_ms=ms,
            ok=ms <= ON_TIME_MS,
            subject=str(job.get("name") or job.get("id") or "")[:200],
            workspace_id=workspace_id,
            once_key=f"{workspace_id}:{job.get('id')}:{_stamp(due)}",
        )
    return added


def probe_targets(settings: Any) -> list[tuple[str, str]]:
    """(sli, url) the probes ask: the core's /health (S3) and the web's home (S1)."""
    found: list[tuple[str, str]] = []
    core_url = getattr(settings, "slo_core_url", None)
    web_url = getattr(settings, "slo_web_url", None)
    if core_url:
        found.append(("health", core_url.rstrip("/") + "/health"))
    if web_url:
        found.append(("page", web_url.rstrip("/") + "/"))
    return found


def probe(core: Any, sli: str, url: str, *, client: httpx.Client | None = None) -> bool:
    """One GET (no redirect followed): its time to first byte and whether it
    answered (a status below 500). Returns that answer."""
    http = client or httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False)
    started = time.monotonic()
    ms: int | None = None
    try:
        with http.stream("GET", url) as response:
            ms = int((time.monotonic() - started) * 1000)  # headers in: the first byte
            ok = response.status_code < 500
    except httpx.HTTPError as error:
        log.info("SLI probe %s %s: %s", sli, url, type(error).__name__)
        ok = False
    finally:
        if client is None:
            http.close()
    samples.add(core.db, sli, at=now(), value_ms=ms, ok=ok, subject=urlsplit(url).path or "/")
    return ok
