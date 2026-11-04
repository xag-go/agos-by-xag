"""Reads of the process environment outside agos_core/config.py, per file (the
inputs of test_environ_ratchet.py).

Typed config (ARCHITECTURE.md §10): AGOS's settings come from one `Settings`
(config.py), validated at start; no other module reads `os.environ`. Today's reads
are written in environ_baseline.json and may only go down. Counted: every
`os.environ` (a read, a copy for a child process, a write) and every `os.getenv`;
also `environ` / `getenv` imported from os.

    python tests/environ_scan.py            # print the counts
    python tests/environ_scan.py --update   # rewrite the baseline after removing reads
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
BASELINE = Path(__file__).with_name("environ_baseline.json")
CONFIG = "config.py"  # the one module that reads the environment


def scan_file(code: str) -> int:
    tree = ast.parse(code)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            names |= {a.asname or a.name for a in node.names if a.name in ("environ", "getenv")}
    return sum(1 for node in ast.walk(tree) if _reads(node, names))


def _reads(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Attribute):
        return (
            node.attr in ("environ", "getenv")
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )
    return isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)


def scan() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if "__pycache__" in path.parts or rel == CONFIG:
            continue
        count = scan_file(path.read_text(encoding="utf-8"))
        if count:
            found[rel] = count
    return found


def load_baseline() -> dict[str, int]:
    data: dict[str, int] = json.loads(BASELINE.read_text())["counts"]
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    now = scan()
    if args.update:
        BASELINE.write_text(
            json.dumps({"total": sum(now.values()), "counts": now}, indent=2, sort_keys=True) + "\n"
        )
    print(f"environ reads outside config.py: {sum(now.values())} in {len(now)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
