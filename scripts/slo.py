#!/usr/bin/env python3
"""The month's SLO report from AGOS's measured SLIs (stdlib only, read-only).

    python3 scripts/slo.py [--db $AGOS_DATA_DIR/system/agos.db] [--month 2026-10] [--json]

Reads the `slo_samples` table (migration 147; written by the core's "slo.*" jobs and
each chat turn's end, services/core/src/agos_core/actions/slis.py) and judges each
SLI against its SLO in docs/compliance/sre.md:

- S1 page: share of web probes that answered with a time to first byte <= 800 ms
  (SLO 95%).
- S2 first output: share of chat turns whose first visible output came within 6 s
  (SLO 90%); also within 20 s (SLO 99%).
- S3 availability: minutes with an ok /health probe over the minutes since the first
  probe of the month (SLO 99.5%). A minute with no probe counts as down: the core was
  not there to answer.
- S4 automation on time: share of scheduled runs Hermes started within 2 min of their
  due time (SLO 99%).

The default month is the last full one; the default database is the installed one
(AGOS_DATA_DIR from /etc/agos/agos.conf, else ~/agos-data).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PAGE_MS = 800
FIRST_MS = 6_000
FIRST_SLOW_MS = 20_000


def _month_bounds(month: str) -> tuple[str, str]:
    start = datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=UTC)
    end = (start + timedelta(days=32)).replace(day=1)
    return _stamp(start), _stamp(end)


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _rows(db: sqlite3.Connection, sli: str, start: str, end: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT value_ms, ok, at FROM slo_samples WHERE sli = ? AND at >= ? AND at < ?"
            " ORDER BY at",
            (sli, start, end),
        )
    )


def _share(good: int, total: int) -> float | None:
    return round(100.0 * good / total, 2) if total else None


def _row(name: str, slo: float, good: int, total: int, detail: str) -> dict[str, Any]:
    value = _share(good, total)
    return {
        "sli": name,
        "slo": slo,
        "samples": total,
        "value": value,
        "met": None if value is None else value >= slo,
        "detail": detail,
    }


def _availability(rows: list[sqlite3.Row], end: str, now: str) -> dict[str, Any]:
    if not rows:
        return _row("S3 availability", 99.5, 0, 0, "no probes")
    first = _parse(str(rows[0]["at"])).replace(second=0, microsecond=0)
    until = min(_parse(end), _parse(now))
    expected = max(1, int((until - first).total_seconds() // 60))
    up = {str(r["at"])[:16] for r in rows if r["ok"]}
    down = expected - len(up)
    return _row("S3 availability", 99.5, len(up), expected, f"{down} min down of {expected}")


def report(db_file: Path, month: str, *, now: str | None = None) -> dict[str, Any]:
    start, end = _month_bounds(month)
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        pages = _rows(db, "page", start, end)
        firsts = _rows(db, "first_output", start, end)
        health = _rows(db, "health", start, end)
        runs = _rows(db, "automation_delay", start, end)
    finally:
        db.close()
    fast = [r for r in pages if r["ok"] and r["value_ms"] is not None and r["value_ms"] <= PAGE_MS]
    within = [r for r in firsts if (r["value_ms"] or 0) <= FIRST_MS]
    slow_ok = [r for r in firsts if (r["value_ms"] or 0) <= FIRST_SLOW_MS]
    rows = [
        _row("S1 page", 95.0, len(fast), len(pages), f"TTFB <= {PAGE_MS} ms"),
        _row(
            "S2 first output",
            90.0,
            len(within),
            len(firsts),
            f"<= 6 s; <= 20 s: {_share(len(slow_ok), len(firsts))}% (SLO 99%)",
        ),
        _availability(health, end, now or _stamp(datetime.now(UTC))),
        _row(
            "S4 automation on time",
            99.0,
            sum(1 for r in runs if r["ok"]),
            len(runs),
            "started <= 2 min after due",
        ),
    ]
    return {"month": month, "rows": rows}


def markdown(found: dict[str, Any]) -> str:
    lines = [
        f"SLO report {found['month']}",
        "",
        "| SLI | SLO | measured | met | samples | detail |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in found["rows"]:
        value = "no samples" if r["value"] is None else f"{r['value']}%"
        met = "-" if r["met"] is None else ("yes" if r["met"] else "NO")
        lines.append(
            f"| {r['sli']} | {r['slo']}% | {value} | {met} | {r['samples']} | {r['detail']} |"
        )
    return "\n".join(lines)


def _default_db() -> Path:
    data = os.environ.get("AGOS_DATA_DIR", "")
    conf = Path("/etc/agos/agos.conf")
    if not data and conf.is_file():
        for line in conf.read_text().splitlines():
            if line.startswith("AGOS_DATA_DIR="):
                data = line.split("=", 1)[1].strip().strip('"')
    return Path(data or Path.home() / "agos-data") / "system" / "agos.db"


def _last_month() -> str:
    first = datetime.now(UTC).replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--month", default=None, help="YYYY-MM (default: last full month)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    db_file = args.db or _default_db()
    if not db_file.is_file():
        print(f"no AGOS database at {db_file} (give --db)", file=sys.stderr)
        return 2
    found = report(db_file, args.month or _last_month())
    print(json.dumps(found, indent=2) if args.json else markdown(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
