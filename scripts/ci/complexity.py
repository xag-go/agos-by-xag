#!/usr/bin/env python3
"""Function-complexity ratchet: no function over the limits below, except today's, which may
not get worse. A small file can't hide a 300-line function.

Python (services/core/src, the agos_guard plugin included), read with ruff and `ast`:
  - C901 cyclomatic complexity    > PY_LIMITS["C901"]
  - PLR0912 branches              > PY_LIMITS["PLR0912"]
  - PLR0915 statements            > PY_LIMITS["PLR0915"]
  - length (lines, `def` to end)  > PY_LIMITS["length"]
Web (apps/web/src), read with ESLint (apps/web/eslint.complexity.mjs, syntax only):
  - complexity                    > WEB_LIMITS["complexity"]
  - max-lines-per-function        > WEB_LIMITS["lines"] (blank and comment lines skipped)

`complexity-baseline.json` holds every function over a limit when the gate was added, with
its measures. The check fails when
  - a function not in the baseline is over a limit (split it instead),
  - a baselined function got worse on any measure,
  - a baselined function got better or is gone (lower it with --update, so it can't grow back).
--update records only improvements: it refuses while anything is new or worse.

    python3 scripts/ci/complexity.py                 # check both parts (local, pre-commit)
    python3 scripts/ci/complexity.py --part python   # CI core-static (ruff from the venv)
    python3 scripts/ci/complexity.py --part web      # CI web job (needs node_modules)
    python3 scripts/ci/complexity.py --update        # record a split / simplification
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "complexity-baseline.json"
CORE = ROOT / "services/core"
WEB = ROOT / "apps/web"
PY_LIMITS = {"C901": 10, "PLR0912": 12, "PLR0915": 50, "length": 80}
WEB_LIMITS = {"complexity": 10, "lines": 80}
WEB_IGNORED = {"src/data/core-api.d.ts"}

Measures = dict[str, dict[str, int]]  # "file::function" -> {measure: value}


def _keyed(found: list[tuple[str, int, str, str, int]]) -> Measures:
    """(file, line, name, measure, value) -> measures keyed by file::name, with #n for a
    name used twice in one file (numbered in line order, so a move keeps the key)."""
    by_fn: dict[tuple[str, int, str], dict[str, int]] = defaultdict(dict)
    for file, line, name, measure, value in found:
        by_fn[(file, line, name)][measure] = value
    out: Measures = {}
    seen: dict[str, int] = defaultdict(int)
    for (file, _line, name), measures in sorted(by_fn.items()):
        key = f"{file}::{name}"
        seen[key] += 1
        out[key if seen[key] == 1 else f"{key}#{seen[key]}"] = dict(sorted(measures.items()))
    return out


def _qualnames(tree: ast.Module) -> dict[int, tuple[str, int]]:
    """`def` line -> (qualified name, length in lines) of every function in a module."""
    out: dict[int, tuple[str, int]] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                out[child.lineno] = (name, (child.end_lineno or child.lineno) - child.lineno + 1)
                walk(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def _ruff() -> str:
    for candidate in (Path(sys.executable).parent / "ruff", CORE / ".venv/bin/ruff"):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ruff")
    if found is None:
        raise SystemExit("complexity: ruff not found (run inside services/core's venv: uv run)")
    return found


def python_measures() -> Measures:
    src = CORE / "src"
    files = sorted(p for p in src.rglob("*.py") if "__pycache__" not in p.parts)
    names = {p: _qualnames(ast.parse(p.read_text(encoding="utf-8"))) for p in files}
    found: list[tuple[str, int, str, str, int]] = []
    for path, fns in names.items():
        rel = path.relative_to(ROOT).as_posix()
        for line, (name, length) in fns.items():
            if length > PY_LIMITS["length"]:
                found.append((rel, line, name, "length", length))
    done = subprocess.run(  # noqa: S603
        [
            _ruff(),
            "check",
            "--isolated",
            "--select",
            "C901,PLR0912,PLR0915",
            "--config",
            f"lint.mccabe.max-complexity = {PY_LIMITS['C901']}",
            "--config",
            f"lint.pylint.max-branches = {PY_LIMITS['PLR0912']}",
            "--config",
            f"lint.pylint.max-statements = {PY_LIMITS['PLR0915']}",
            "--output-format",
            "json",
            "--exit-zero",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    for item in json.loads(done.stdout or "[]"):
        path = Path(item["filename"]).resolve()
        line = int(item["location"]["row"])
        value = re.search(r"\((\d+) > \d+\)", item["message"])
        fn = names.get(path, {}).get(line)
        if value is None or fn is None:
            raise SystemExit(f"complexity: can't place ruff's {item['code']} at {path}:{line}")
        found.append((path.relative_to(ROOT).as_posix(), line, fn[0], item["code"], int(value[1])))
    return _keyed(found)


_WEB_NAME = re.compile(
    r"^(?:Async )?(?:Generator )?(?:Function|Method|Arrow function)(?: '([^']*)')?"
)


def web_measures() -> Measures:
    if not (WEB / "node_modules").is_dir():
        raise SystemExit("complexity: apps/web has no node_modules (pnpm install first)")
    done = subprocess.run(
        [  # noqa: S607
            "pnpm",
            "-s",
            "exec",
            "eslint",
            "--no-warn-ignored",
            "-c",
            "eslint.complexity.mjs",
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
        raise SystemExit(f"complexity: eslint failed\n{done.stderr[-2000:]}")
    found: list[tuple[str, int, str, str, int]] = []
    for result in json.loads(done.stdout):
        rel = Path(result["filePath"]).resolve().relative_to(WEB).as_posix()
        if rel in WEB_IGNORED:
            continue
        for m in result["messages"]:
            rule = m.get("ruleId")
            if rule not in ("complexity", "max-lines-per-function"):
                if m.get("fatal"):
                    raise SystemExit(f"complexity: eslint can't parse {rel}: {m['message']}")
                continue
            named = _WEB_NAME.match(m["message"])
            name = (named[1] if named and named[1] else "") or "(anonymous)"
            value = re.search(r"complexity of (\d+)|too many lines \((\d+)\)", m["message"])
            if value is None:
                raise SystemExit(f"complexity: unread eslint message {m['message']!r}")
            measure = "complexity" if rule == "complexity" else "lines"
            found.append(
                (f"apps/web/{rel}", int(m["line"]), name, measure, int(value[1] or value[2]))
            )
    return _keyed(found)


def compare(part: str, now: Measures, base: Measures) -> tuple[list[str], list[str]]:
    worse: list[str] = []
    better: list[str] = []
    for key, measures in now.items():
        if key not in base:
            worse.append(f"  [{part}] {key}: {measures} (new function over the limit)")
            continue
        for measure, value in measures.items():
            was = base[key].get(measure)
            if was is None or value > was:
                worse.append(f"  [{part}] {key}: {measure} {value}, was {was or 'under the limit'}")
    for key, measures in base.items():
        if key not in now:
            better.append(f"  [{part}] {key}: gone or under every limit (baseline {measures})")
            continue
        for measure, was in measures.items():
            value = now[key].get(measure)
            if value is None or value < was:
                better.append(f"  [{part}] {key}: {measure} {value or 'under the limit'} < {was}")
    return worse, better


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=("python", "web", "all"), default="all")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    parts = ("python", "web") if args.part == "all" else (args.part,)
    stored = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    worse: list[str] = []
    better: list[str] = []
    refused: list[str] = []  # worse in a part that has a baseline already
    now: dict[str, Measures] = {}
    for part in parts:
        now[part] = python_measures() if part == "python" else web_measures()
        w, b = compare(part, now[part], stored.get(part, {}))
        worse += w
        better += b
        if part in stored:
            refused += w
        print(
            f"complexity [{part}]: {len(now[part])} functions over a limit "
            f"({len(stored.get(part, {}))} in the baseline)"
        )
    if worse:
        print("Functions over a limit got worse or are new (split them into smaller functions):")
        print("\n".join(worse))
    if args.update:
        if refused:
            print("--update records only improvements: fix the lines above first.")
            return 1
        out = {**stored, "limits": {"python": PY_LIMITS, "web": WEB_LIMITS}, **now}
        BASELINE.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    if better:
        print("Functions got simpler, good: run `python3 scripts/ci/complexity.py --update`:")
        print("\n".join(better))
    return 1 if worse or better else 0


if __name__ == "__main__":
    sys.exit(main())
