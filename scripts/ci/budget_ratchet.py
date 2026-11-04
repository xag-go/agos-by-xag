#!/usr/bin/env python3
"""Speed / RAM / bundle-size budgets: a ratchet on measured numbers.

    python3 scripts/ci/budget_ratchet.py REPORT.json --baseline BASELINE.json [--update]
                                         [--tolerance 0.2]

REPORT and BASELINE hold {"metrics": {name: {"value": number, "unit": "ms"|"s"|"MB"|"kB"|
"pts"}}} (lower is better for every metric). Each metric may be up to --tolerance (20%)
worse than its baseline: run-to-run noise. Worse than that fails, unless the change is
under the unit's noise floor (10 ms, 0.25 s, 10 MB, 1 kB, 5 pts of a Lighthouse score: a
4 -> 8 ms page is not a regression). A metric the baseline has and the report lacks
fails (a budget never goes away unseen); a new one is told and recorded by --update.

--update records the report's better numbers and its new metrics, never a worse one,
and refuses while anything is worse (like scripts/ci/complexity.py --update).

Used by scripts/ci/web_budgets.py (page bundle sizes, every PR),
services/core/tests/browser/test_lighthouse.py (the main screens' Lighthouse scores as
the points they miss, CI browser job) and services/core/tests/perf/budgets.py (core
start, API latencies, RSS on the e2e-style rig; nightly on the self-hosted runner,
where its baseline was measured).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["FLOOR", "Row", "compare", "load", "main", "passed", "updated"]

TOLERANCE = 0.2
FLOOR = {"ms": 10.0, "s": 0.25, "MB": 10.0, "kB": 1.0, "pts": 5.0}
Metrics = dict[str, dict[str, Any]]


@dataclass
class Row:
    name: str
    unit: str
    base: float | None
    now: float | None
    status: str  # ok | better | worse | new | missing

    def line(self) -> str:
        if self.base is None:
            return f"  new      {self.name}: {self.now:g} {self.unit}"
        if self.now is None:
            return f"  MISSING  {self.name}: baseline {self.base:g} {self.unit}, not measured"
        change = (self.now - self.base) / self.base * 100 if self.base else 0.0
        mark = {"worse": "WORSE   ", "better": "better  ", "ok": "ok      "}[self.status]
        return f"  {mark} {self.name}: {self.now:g} {self.unit} (baseline {self.base:g}, {change:+.0f}%)"


def compare(base: Metrics, now: Metrics, tolerance: float = TOLERANCE) -> list[Row]:
    rows: list[Row] = []
    for name in [*base, *(n for n in now if n not in base)]:
        unit = str((base.get(name) or now.get(name) or {}).get("unit") or "")
        b = base.get(name, {}).get("value")
        n = now.get(name, {}).get("value")
        if b is None:
            rows.append(Row(name, unit, None, float(n), "new"))
        elif n is None:
            rows.append(Row(name, unit, float(b), None, "missing"))
        else:
            b, n = float(b), float(n)
            if n > b * (1 + tolerance) and n - b > FLOOR.get(unit, 0.0):
                status = "worse"
            elif n < b:
                status = "better"
            else:
                status = "ok"
            rows.append(Row(name, unit, b, n, status))
    return rows


def passed(rows: list[Row]) -> bool:
    return not any(r.status in ("worse", "missing") for r in rows)


def updated(base: Metrics, now: Metrics, tolerance: float = TOLERANCE) -> Metrics:
    rows = compare(base, now, tolerance)
    bad = [r.name for r in rows if r.status in ("worse", "missing")]
    if bad:
        raise SystemExit(f"not updated: worse or missing first: {', '.join(bad)}")
    new = {k: dict(v) for k, v in base.items()}
    for row in rows:
        if row.status in ("better", "new"):
            new[row.name] = {**now[row.name]}
    return new


def load(path: Path) -> Metrics:
    data = json.loads(path.read_text())
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, dict):
        raise SystemExit(f"{path}: no metrics")
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)

    now = load(args.report)
    base = load(args.baseline) if args.baseline.is_file() else {}
    rows = compare(base, now, args.tolerance)
    for row in rows:
        print(row.line())
    if args.update:
        try:
            new = updated(base, now, args.tolerance)
        except SystemExit as refused:
            print(refused)
            return 1
        kept = json.loads(args.baseline.read_text()) if args.baseline.is_file() else {}
        kept["metrics"] = dict(sorted(new.items()))
        args.baseline.write_text(json.dumps(kept, indent=2) + "\n")  # prettier's shape
        print(f"baseline updated: {args.baseline}")
        return 0
    ok = passed(rows)
    worse = [r.name for r in rows if r.status in ("worse", "missing")]
    print(
        "budgets ok"
        if ok
        else f"budgets FAILED ({len(worse)}): more than {args.tolerance:.0%} worse or missing: "
        + ", ".join(worse)
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
