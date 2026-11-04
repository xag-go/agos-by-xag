#!/usr/bin/env python3
"""File-size ratchet: no source file over LIMIT lines, except today's, which may not grow.

Counts lines of every tracked .py/.ts/.tsx file (git ls-files), minus generated files.
`file-size-baseline.json` holds the files over the limit when the gate was added, with
their line counts. The check fails when
  - a file not in the baseline is over the limit (split it instead),
  - a baselined file got longer than its recorded count,
  - a baselined file got shorter (lower its count with --update, so it cannot grow back).

    python3 scripts/ci/file_size.py            # check (CI, pre-commit)
    python3 scripts/ci/file_size.py --update   # rewrite the baseline after a split
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

LIMIT = 800
ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "file-size-baseline.json"
SUFFIXES = (".py", ".ts", ".tsx")
GENERATED = {"apps/web/src/data/core-api.d.ts"}
# Append-only by design (each migration is frozen once shipped): tracked, may grow.
GROWS = {"services/core/src/agos_core/db/migrations.py"}


def sizes() -> dict[str, int]:
    out = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z", "--", *[f"*{s}" for s in SUFFIXES]],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode()
    found: dict[str, int] = {}
    for name in filter(None, out.split("\0")):
        path = ROOT / name
        if name in GENERATED or name.endswith("next-env.d.ts") or not path.is_file():
            continue
        with path.open("rb") as handle:
            found[name] = sum(1 for _ in handle)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    now = sizes()
    over = {k: v for k, v in sorted(now.items()) if v > LIMIT}
    if args.update:
        BASELINE.write_text(
            json.dumps({"limit": LIMIT, "files": over}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {BASELINE.relative_to(ROOT)}: {len(over)} files over {LIMIT} lines")
        return 0
    base: dict[str, int] = json.loads(BASELINE.read_text(encoding="utf-8"))["files"]
    errors: list[str] = []
    stale: list[str] = []
    for name, n in over.items():
        if name not in base:
            errors.append(f"  {name}: {n} lines, over the {LIMIT}-line limit (new file)")
        elif n > base[name] and name not in GROWS:
            errors.append(f"  {name}: {n} lines, grew from {base[name]} (baselined file)")
    for name, n in base.items():
        if name not in now:
            stale.append(f"  {name}: gone (baseline {n})")
        elif now[name] < n and name not in GROWS:
            stale.append(f"  {name}: {now[name]} lines < baseline {n}")
    print(f"file size: {len(over)} files over {LIMIT} lines ({len(base)} in the baseline)")
    if errors:
        print("Files over the limit (split them; move code into a new module):")
        print("\n".join(errors))
    if stale:
        print("Files shrank, good: run `python3 scripts/ci/file_size.py --update` and commit it:")
        print("\n".join(stale))
    return 1 if errors or stale else 0


if __name__ == "__main__":
    sys.exit(main())
