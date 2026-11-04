#!/usr/bin/env python3
"""Web page bundle sizes: each page's first-load JavaScript, gzipped, as a budget.

    pnpm --filter @agos/web build
    python3 scripts/ci/web_budgets.py [--next apps/web/.next] [--report web-budgets.json] [--update]

Per page (`web.page.<url pattern>.gzip_kB`): Next's root chunks (build-manifest.json
rootMainFiles + polyfillFiles) plus every chunk the page's layouts and page load (the
`entryJSFiles` of its server/app/**/page_client-reference-manifest.js), each chunk once,
gzipped at level 9 as a server would send it. Plus `web.all_js.gzip_kB`: every chunk
any page loads. Route groups are dropped from the name (`/(app)/w/[id]/board` ->
`/w/[id]/board`).

The numbers are checked against scripts/ci/web-budget-baseline.json with
scripts/ci/budget_ratchet.py: a page more than 20% heavier fails; --update records
lighter pages (never a heavier one). Standard library only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BASELINE = HERE / "web-budget-baseline.json"
sys.path.insert(0, str(HERE))

import budget_ratchet  # noqa: E402 - beside this script

__all__ = ["main", "measure"]


def _rel(chunk: str) -> str:
    """A chunk path as the manifests write it, relative to .next."""
    return re.sub(r"^/?(_next/)?", "", chunk)


def _gzip_size(path: Path, cache: dict[Path, int]) -> int:
    if path not in cache:
        cache[path] = len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))
    return cache[path]


def _entries(manifest: Path) -> tuple[str, set[str]]:
    text = manifest.read_text()
    found = re.search(r'__RSC_MANIFEST\["([^"]+)"\]\s*=\s*(\{.*\})\s*;?\s*$', text, re.S)
    if not found:
        raise SystemExit(f"{manifest}: not a client reference manifest")
    data: dict[str, Any] = json.loads(found.group(2))
    chunks = {_rel(c) for files in (data.get("entryJSFiles") or {}).values() for c in files}
    return found.group(1), chunks


def _page_name(route: str) -> str:
    """'/(app)/w/[id]/board/page' -> '/w/[id]/board'."""
    parts = [p for p in route.split("/") if p and not (p.startswith("(") and p.endswith(")"))]
    if parts and parts[-1] == "page":
        parts.pop()
    return "/" + "/".join(parts)


def measure(next_dir: Path) -> dict[str, dict[str, Any]]:
    build = next_dir / "build-manifest.json"
    if not build.is_file():
        raise SystemExit(f"no {build}: run `pnpm --filter @agos/web build` (next build) first")
    root_files = json.loads(build.read_text())
    root = {
        _rel(c)
        for c in [*root_files.get("rootMainFiles", []), *root_files.get("polyfillFiles", [])]
    }
    cache: dict[Path, int] = {}
    metrics: dict[str, dict[str, Any]] = {}
    every: set[str] = set(root)
    for manifest in sorted(
        (next_dir / "server" / "app").rglob("page_client-reference-manifest.js")
    ):
        route, chunks = _entries(manifest)
        name = _page_name(route)
        if name.startswith(("/_not-found", "/_global-error")):
            continue
        files = root | chunks
        every |= files
        size = sum(
            _gzip_size(next_dir / f, cache) for f in sorted(files) if (next_dir / f).is_file()
        )
        key = f"web.page.{name}.gzip_kB"
        if key in metrics:  # two route groups with one URL pattern: keep the heavier
            size = max(size, int(metrics[key]["value"] * 1024))
        metrics[key] = {"value": round(size / 1024, 1), "unit": "kB"}
    if not metrics:
        raise SystemExit(f"{next_dir}: no page manifests (not an app-router build?)")
    total = sum(_gzip_size(next_dir / f, cache) for f in sorted(every) if (next_dir / f).is_file())
    metrics["web.all_js.gzip_kB"] = {"value": round(total / 1024, 1), "unit": "kB"}
    return dict(sorted(metrics.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--next", type=Path, default=REPO / "apps" / "web" / ".next")
    parser.add_argument("--report", type=Path, default=Path("web-budgets.json"))
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    metrics = measure(args.next)
    args.report.write_text(json.dumps({"metrics": metrics}, indent=1) + "\n")
    print(f"{len(metrics)} sizes measured -> {args.report}")
    ratchet = [str(args.report), "--baseline", str(args.baseline)]
    return budget_ratchet.main([*ratchet, *(["--update"] if args.update else [])])


if __name__ == "__main__":
    sys.exit(main())
