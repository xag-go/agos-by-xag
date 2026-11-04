#!/usr/bin/env python3
"""Accessibility lint ratchet: eslint-plugin-jsx-a11y over the web, no new finding, and today's
may only go away.

Read with ESLint (apps/web/eslint.a11y.mjs: jsx-a11y's recommended rules plus
control-has-associated-label, syntax only). `a11y-baseline.json` holds, per file, how many
findings of each rule it had when the gate was added. The check fails when
  - a file has more findings of a rule than its baseline (a new unlabeled button, a click
    handler on a <div> with no keyboard way in...): fix it, never record it,
  - a file has fewer (lower the baseline with --update, so it can't grow back).
--update records only improvements: it refuses while anything is new or worse.

    python3 scripts/ci/a11y_lint.py            # check (CI web job; needs node_modules)
    python3 scripts/ci/a11y_lint.py --update   # record a fix
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

__all__ = ["Counts", "compare", "counts", "main", "measure"]

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps/web"
BASELINE = Path(__file__).resolve().parent / "a11y-baseline.json"
PREFIX = "jsx-a11y/"

Counts = dict[str, dict[str, int]]  # "apps/web/<file>" -> {rule: findings}


def counts(results: list[dict[str, Any]], web: Path = WEB) -> Counts:
    """ESLint's JSON results -> jsx-a11y findings per file and rule (other rules ignored;
    a file ESLint can't parse stops the check)."""
    found: dict[str, Counter[str]] = {}
    for result in results:
        rel = Path(result["filePath"]).resolve().relative_to(web.resolve()).as_posix()
        for message in result["messages"]:
            rule = str(message.get("ruleId") or "")
            if message.get("fatal"):
                raise SystemExit(f"a11y: eslint can't parse {rel}: {message['message']}")
            if rule.startswith(PREFIX):
                found.setdefault(f"apps/web/{rel}", Counter())[rule.removeprefix(PREFIX)] += 1
    return {f: dict(sorted(c.items())) for f, c in sorted(found.items())}


def measure() -> Counts:
    if not (WEB / "node_modules").is_dir():
        raise SystemExit("a11y: apps/web has no node_modules (pnpm install first)")
    done = subprocess.run(
        [  # noqa: S607 - pnpm from PATH, as the CI web job runs it
            "pnpm",
            "-s",
            "exec",
            "eslint",
            "--no-warn-ignored",
            "-c",
            "eslint.a11y.mjs",
            "--format",
            "json",
            "src",
        ],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise SystemExit(f"a11y: eslint failed\n{done.stderr[-2000:]}")
    return counts(json.loads(done.stdout))


def compare(now: Counts, base: Counts) -> tuple[list[str], list[str]]:
    """(worse, better) lines: more findings than the baseline, and fewer."""
    worse: list[str] = []
    better: list[str] = []
    for file in sorted({*now, *base}):
        for rule in sorted({*now.get(file, {}), *base.get(file, {})}):
            n, b = now.get(file, {}).get(rule, 0), base.get(file, {}).get(rule, 0)
            if n > b:
                worse.append(f"  {file}: {rule} {n} (baseline {b})")
            elif n < b:
                better.append(f"  {file}: {rule} {n} < {b}")
    return worse, better


def total(found: Counts) -> int:
    return sum(sum(rules.values()) for rules in found.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    stored = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    base: Counts = stored.get("files", {})
    now = measure()
    worse, better = compare(now, base)
    print(f"a11y: {total(now)} jsx-a11y findings ({total(base)} in the baseline)")
    if worse:
        print("New accessibility findings (label the control, give the element its role/keys):")
        print("\n".join(worse))
    if args.update:
        if worse and BASELINE.is_file():
            print("--update records only improvements: fix the lines above first.")
            return 1
        out = {
            "about": stored.get("about")
            or "scripts/ci/a11y_lint.py: jsx-a11y findings per web file; only shrinks",
            "total": total(now),
            "files": now,
        }
        BASELINE.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    if better:
        print("Fewer findings, good: run `python3 scripts/ci/a11y_lint.py --update`:")
        print("\n".join(better))
    return 1 if worse or better else 0


if __name__ == "__main__":
    sys.exit(main())
