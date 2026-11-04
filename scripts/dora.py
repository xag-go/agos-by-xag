#!/usr/bin/env python3
"""DORA metrics for AGOS from git history alone (stdlib only, read-only).

    python3 scripts/dora.py [--since 2026-10-01] [--until <date>] [--branch origin/main]
                            [--window-days 7] [--wide] [--ships ships.csv] [--json]

Definitions (docs/compliance/dora.md explains the reasoning and the caveats):

- Deployment: a first-parent commit on the main branch (each PR merge or direct
  push), or, with --ships, each row of a CSV ledger `sha,iso_time` of live ships.
- Lead time for changes: for every non-merge commit a deployment brings in
  (`git rev-list D^1..D`), deployment time minus the commit's author time.
- Change failure: each fix commit (subject matches FIX) blames one deployment: the
  latest deployment before the fix was authored (within --window-days) that changed a
  source file the fix touches. A deployment with at least one blame is failed.
- Time to restore: for a failed deployment, the time from D to the first later
  deployment carrying such a fix (an upper bound: the live server may have been
  fixed earlier by a ship that main only records at merge time).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIX = re.compile(
    r"(^fix\b|^fix:|\bfix(es|ed)?\b|\bbug\b|\bhotfix\b|\brevert\b|\bregress)", re.IGNORECASE
)
FIX_WIDE = re.compile(
    r"\b(fix|bug|broke|broken|wrong|regress|crash|hang|stale|revert|repair|lost|missing|fail)",
    re.IGNORECASE,
)
# Generated or bookkeeping files: a fix touching only these is not tied to a deployment.
NOISE = re.compile(
    r"(^|/)(openapi\.json|core-api\.d\.ts|pnpm-lock\.yaml|uv\.lock|CHANGELOG\.md)$|^docs/|(^|/)tests?/"
)


GIT = shutil.which("git") or "git"


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - git with a fixed argv, no shell
        [GIT, *args], check=True, capture_output=True, text=True
    ).stdout


def when(epoch: str) -> datetime:
    return datetime.fromtimestamp(int(epoch), UTC)


@dataclass
class Commit:
    sha: str
    author_at: datetime
    subject: str
    files: set[str] = field(default_factory=set)


@dataclass
class Deploy:
    sha: str
    at: datetime
    subject: str
    commits: list[Commit] = field(default_factory=list)

    @property
    def files(self) -> set[str]:
        return {f for c in self.commits for f in c.files if not NOISE.search(f)}


def commits_in(rev_range: str) -> list[Commit]:
    out = git("log", "--no-merges", "--format=\x1e%H\x1f%at\x1f%s", "--name-only", rev_range)
    result = []
    for block in out.split("\x1e")[1:]:
        head, _, names = block.partition("\n")
        sha, at, subject = head.split("\x1f", 2)
        result.append(Commit(sha, when(at), subject, {n for n in names.splitlines() if n}))
    return result


def deploys_from_git(branch: str, since: str, until: str | None) -> list[Deploy]:
    args = ["log", "--first-parent", "--format=%H\x1f%ct\x1f%P\x1f%s", f"--since={since}"]
    if until:
        args.append(f"--until={until}")
    deploys = []
    for line in git(*args, branch).splitlines():
        sha, at, parents, subject = line.split("\x1f", 3)
        first = parents.split()[0] if parents else None
        brought = commits_in(f"{first}..{sha}") if first else commits_in(sha)
        deploys.append(Deploy(sha, when(at), subject, brought))
    return sorted(deploys, key=lambda d: d.at)


def deploys_from_ledger(path: str) -> list[Deploy]:
    with Path(path).open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    deploys: list[Deploy] = []
    previous: str | None = None
    for sha, at in rows:
        rng = f"{previous}..{sha}" if previous else f"{sha}~1..{sha}"
        deploys.append(Deploy(sha, datetime.fromisoformat(at), "ship", commits_in(rng)))
        previous = sha
    return deploys


def hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def compute(
    deploys: list[Deploy], window: timedelta, fix: re.Pattern[str], period_days: float
) -> dict[str, object]:
    if not deploys:
        return {"deployments": 0}
    span_days = max(1.0, period_days)
    leads = [hours(d.at - c.author_at) for d in deploys for c in d.commits]
    per_deploy = [
        round(statistics.median([hours(d.at - c.author_at) for c in d.commits]), 1)
        for d in deploys
        if d.commits
    ]
    # Each fix commit blames one deployment: the latest one before the fix was
    # written that changed a file the fix touches (and is at most `window` older).
    blamed: dict[str, dict[str, object]] = {}
    for j, later in enumerate(deploys):
        for c in later.commits:
            if not fix.search(c.subject):
                continue
            for d in reversed(deploys[:j]):
                if d.at >= c.author_at or c.author_at - d.at > window:
                    continue
                if c.files & d.files:
                    blamed.setdefault(
                        d.sha,
                        {
                            "deploy": d.sha[:8],
                            "deploy_subject": d.subject[:70],
                            "fixed_by": later.sha[:8],
                            "fix_commit": c.sha[:8],
                            "fix_subject": c.subject[:70],
                            "restore_h": hours(later.at - d.at),
                        },
                    )
                    break
    failed = sorted(blamed.values(), key=lambda f: str(f["deploy"]))
    restore = [f["restore_h"] for f in failed]
    bulk = max(deploys, key=lambda d: len(d.commits))
    leads_wo_bulk = [hours(d.at - c.author_at) for d in deploys if d is not bulk for c in d.commits]
    return {
        "first_deploy": deploys[0].at.isoformat(),
        "last_deploy": deploys[-1].at.isoformat(),
        "deployments": len(deploys),
        "deploys_per_week": round(len(deploys) / span_days * 7, 1),
        "active_deploy_days": len({d.at.date() for d in deploys}),
        "commits_deployed": len(leads),
        "lead_time_h_median_all_commits": pct(leads, 0.5),
        "lead_time_h_p90_all_commits": pct(leads, 0.9),
        "bulk_deploy": {
            "sha": bulk.sha[:8],
            "subject": bulk.subject[:70],
            "commits": len(bulk.commits),
        },
        "lead_time_h_median_without_bulk": pct(leads_wo_bulk, 0.5),
        "lead_time_h_p90_without_bulk": pct(leads_wo_bulk, 0.9),
        "lead_time_h_median_of_deploy_medians": pct(per_deploy, 0.5),
        "failed_deployments": len(failed),
        "change_failure_rate_pct": round(100 * len(failed) / len(deploys), 1),
        "time_to_restore_h_median": pct(restore, 0.5),
        "time_to_restore_h_max": max(restore) if restore else 0.0,
        "failures": failed,
    }


def as_markdown(m: dict[str, object]) -> str:
    rows = [
        ("Period", str(m["period"])),
        (
            "Deployments",
            f"{m['deployments']} ({m['deploys_per_week']}/week, {m['active_deploy_days']} active days)",
        ),
        ("Lead time, median (all commits)", f"{m['lead_time_h_median_all_commits']} h"),
        ("Lead time, p90 (all commits)", f"{m['lead_time_h_p90_all_commits']} h"),
        ("Lead time, median (without bulk sync)", f"{m['lead_time_h_median_without_bulk']} h"),
        (
            "Lead time, median of per-deploy medians",
            f"{m['lead_time_h_median_of_deploy_medians']} h",
        ),
        (
            "Change failure rate",
            f"{m['change_failure_rate_pct']}% ({m['failed_deployments']}/{m['deployments']})",
        ),
        (
            "Time to restore, median / max",
            f"{m['time_to_restore_h_median']} h / {m['time_to_restore_h_max']} h",
        ),
    ]
    lines = ["| Metric | Value |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows]]
    failures = m.get("failures") or []
    if failures:
        lines += [
            "",
            "| Failed deploy | Fixed by deploy | Fix commit | Restore (h) |",
            "|---|---|---|---|",
        ]
        for f in failures:  # type: ignore[union-attr]
            lines.append(
                f"| `{f['deploy']}` {f['deploy_subject']} | `{f['fixed_by']}` "
                f"| `{f['fix_commit']}` {f['fix_subject']} | {f['restore_h']} |"
            )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--since", default="2026-10-01")
    p.add_argument("--until")
    p.add_argument("--branch", default="origin/main")
    p.add_argument("--window-days", type=float, default=7)
    p.add_argument("--wide", action="store_true", help="wide fix pattern (counts more fixes)")
    p.add_argument("--ships", help="CSV ledger of live ships: sha,iso_time (overrides git merges)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    deploys = (
        deploys_from_ledger(a.ships) if a.ships else deploys_from_git(a.branch, a.since, a.until)
    )
    start = datetime.fromisoformat(a.since).replace(tzinfo=UTC)
    end = datetime.fromisoformat(a.until).replace(tzinfo=UTC) if a.until else datetime.now(UTC)
    period = (end - start).total_seconds() / 86400
    m = compute(deploys, timedelta(days=a.window_days), FIX_WIDE if a.wide else FIX, period)
    m["period"] = f"{a.since} .. {end.date().isoformat()} ({round(period, 1)} days)"
    print(json.dumps(m, indent=2) if a.json else as_markdown(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
