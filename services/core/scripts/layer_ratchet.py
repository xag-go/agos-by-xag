"""Layer rules for agos_core, as a ratchet.

Counts every import statement in src/agos_core that breaks a layer contract, including
the imports inside function bodies (65% of the core's internal imports are lazy, and
they hide the real dependency graph). Today's breaks are written in
`layer-baseline.json`; the check fails when a contract gains a new importer -> imported
pair or a pair's count grows. When a count shrinks the baseline must shrink with it
(`--update`), so a fixed break can never come back unseen.

The same contracts, for direct and indirect chains of module-level and lazy imports,
are in `.importlinter` (run `lint-imports`); this script is the per-statement ratchet.

    python scripts/layer_ratchet.py            # check (CI)
    python scripts/layer_ratchet.py --update   # rewrite the baseline after removing breaks
    python scripts/layer_ratchet.py --list     # print every counted break with its line
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
SRC = CORE / "src"
BASELINE = CORE / "layer-baseline.json"
ROOT = "agos_core"

# ARCHITECTURE.md §10: api -> actions -> db/storage/security -> domain. `engine` is the
# Hermes driver and pure rules the actions use; it sits between actions and the
# persistence layer. `hermes_gateway` (ADR 0024) is the boundary the engine grows
# into: same layer, and the two may import each other while code moves across.
# The Service Layer's own machinery (the operation registry `ops`, the Unit of Work,
# sagas, domain events, the outbox, the job queue) sits beside them: the services (actions) use it,
# and the engine's pure Co-Founder tables read the operation catalogue (ops/specs).
# A lower layer never imports a higher one.
SERVICE_INFRA = ("engine", "hermes_gateway", "ops", "uow", "saga", "events", "outbox", "jobs")
LAYERS: list[set[str]] = [
    {"api"},
    {"actions"},
    set(SERVICE_INFRA),
    {"db", "storage", "security"},
    {"domain"},
]


@dataclass(frozen=True)
class Contract:
    name: str
    text: str


CONTRACTS = [
    Contract(
        "layers",
        "api -> actions -> engine|hermes_gateway|ops|uow|saga|events|outbox|jobs"
        " -> db|storage|security -> domain, never upward",
    ),
    Contract(
        "api-only-via-actions",
        "api reaches engine/hermes_gateway/db/storage/security only through actions",
    ),
    Contract("core-not-plugin", "core code never imports hermes_plugin (it runs inside Hermes)"),
    Contract("plugin-standalone", "hermes_plugin imports no core package (it talks HTTP)"),
    Contract("domain-pure", "domain imports nothing else from agos_core"),
    Contract(
        "shared-pure",
        "shared imports nothing else from agos_core (it is copied into the plugin)",
    ),
]

_DTO_MODULES = {"agos_core.db.records"}  # view models the api may use (moving to schemas/)


def _package(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _layer(package: str) -> int | None:
    for index, layer in enumerate(LAYERS):
        if package in layer:
            return index
    return None


def _modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted((SRC / ROOT).rglob("*.py")):
        rel = path.relative_to(SRC).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found[".".join(parts)] = path
    return found


def _imports(module: str, path: Path, known: dict[str, Path]) -> list[tuple[str, int]]:
    """Every agos_core module this file imports, one entry per imported name, any depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    is_package = path.name == "__init__.py"
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")
                if not is_package:
                    base = base[:-1]
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join([*base, *([node.module] if node.module else [])])
            else:
                prefix = node.module or ""
            for alias in node.names:
                full = f"{prefix}.{alias.name}"
                out.append((full if full in known else prefix, node.lineno))
    resolved: list[tuple[str, int]] = []
    for name, line in out:
        if not name.startswith(ROOT + ".") and name != ROOT:
            continue
        while name not in known and "." in name:
            name = name.rsplit(".", 1)[0]
        resolved.append((name, line))
    return resolved


def _broken(importer: str, imported: str) -> list[str]:
    src, dst = _package(importer), _package(imported)
    if not src or not dst or src == dst:
        return []
    hits: list[str] = []
    a, b = _layer(src), _layer(dst)
    if a is not None and b is not None and b < a:
        hits.append("layers")
    if (
        src == "api"
        and dst in {"engine", "hermes_gateway", "db", "storage", "security"}
        and imported not in _DTO_MODULES
    ):
        hits.append("api-only-via-actions")
    if dst == "hermes_plugin":
        hits.append("core-not-plugin")
    if src == "hermes_plugin":
        hits.append("plugin-standalone")
    if src == "domain":
        hits.append("domain-pure")
    if src == "shared":
        hits.append("shared-pure")
    return hits


def scan() -> tuple[dict[str, Counter[str]], list[str]]:
    known = _modules()
    counts: dict[str, Counter[str]] = {c.name: Counter() for c in CONTRACTS}
    lines: list[str] = []
    for module, path in known.items():
        for imported, line in _imports(module, path, known):
            for contract in _broken(module, imported):
                counts[contract][f"{module} -> {imported}"] += 1
                rel = path.relative_to(CORE)
                lines.append(f"{contract}: {rel}:{line} {module} -> {imported}")
    return counts, lines


def _as_json(counts: dict[str, Counter[str]]) -> dict[str, object]:
    return {
        "_doc": "Layer breaks allowed today (scripts/layer_ratchet.py). Counts may only shrink.",
        "totals": {name: sum(c.values()) for name, c in counts.items()},
        "pairs": {name: dict(sorted(c.items())) for name, c in counts.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    counts, lines = scan()  # lines: "<contract>: <file>:<line> <importer> -> <imported>"
    if args.list:
        print("\n".join(lines))
    if args.update:
        BASELINE.write_text(json.dumps(_as_json(counts), indent=2) + "\n", encoding="utf-8")
        print(
            f"wrote {BASELINE.name}: "
            + ", ".join(f"{k}={sum(v.values())}" for k, v in counts.items())
        )
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["pairs"]
    new: list[str] = []
    new_pairs: set[tuple[str, str]] = set()
    shrunk: list[str] = []
    for contract in CONTRACTS:
        allowed: dict[str, int] = base.get(contract.name, {})
        for pair, n in sorted(counts[contract.name].items()):
            if n > allowed.get(pair, 0):
                new.append(f"  [{contract.name}] {pair}: {n} (baseline {allowed.get(pair, 0)})")
                new_pairs.add((contract.name, pair))
        for pair, n in sorted(allowed.items()):
            if counts[contract.name].get(pair, 0) < n:
                shrunk.append(
                    f"  [{contract.name}] {pair}: {counts[contract.name].get(pair, 0)} < {n}"
                )
    for contract in CONTRACTS:
        total = sum(counts[contract.name].values())
        print(f"{contract.name}: {total} breaks ({contract.text})")
    if new:
        print("\nNEW layer breaks (move the code to the right layer instead):")
        print("\n".join(new))
        for contract_name, pair in sorted(new_pairs):
            for ln in lines:
                if ln.startswith(contract_name + ": ") and ln.endswith(" " + pair):
                    print("    " + ln)
    if shrunk:
        print(
            "\nFewer breaks than the baseline, good: run `python scripts/layer_ratchet.py --update`"
        )
        print("and commit layer-baseline.json so they cannot come back:")
        print("\n".join(shrunk))
    return 1 if new or shrunk else 0


if __name__ == "__main__":
    sys.exit(main())
