"""Counts every Hermes call outside the Hermes Gateway (ADR 0024), per rule and file.

Read by tests/test_hermes_gateway_ratchet.py against hermes_gateway_baseline.json.
Code inside strings (scripts AGOS writes for Hermes's cron to run) is not counted:
the scan reads the syntax tree. After a change that removes calls, record the new
counts: `python tests/hermes_gateway_scan.py --update` (from services/core)."""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
BASELINE = Path(__file__).resolve().parent / "hermes_gateway_baseline.json"

# Where Hermes may be called from: the gateway itself, and the engine it wraps
# (plan G8 moves the engine's own calls in). The plugin runs inside Hermes.
INSIDE = ("hermes_gateway/", "engine/", "hermes_plugin/")
GATEWAY = "agos_core.hermes_gateway"

ENGINE_CLI = frozenset(
    {
        "_hermes",
        "walled_cli",
        "config_writes",
        "managed_write",
        "unmanaged_hermes",
        "unmanaged_writes",
        "unmanaged_in",
    }
)
SUBPROCESS = frozenset({"run", "Popen", "check_output", "check_call", "call", "getoutput"})
RULES = (
    "engine_cli",  # the engine's raw CLI entry points, called from outside it
    "subprocess",  # a process started outside the gateway/engine
    "sqlite3_connect",  # a database opened outside the gateway (db/connection.py: AGOS's own)
    "hermes_python",  # Hermes's Python located to run code in it
    "engine_runner",  # the engine's Runner used directly
    "actions_import",  # actions/ importing subprocess (Hermes DBs: sqlite3_connect)
)


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _gateway_names(tree: ast.AST) -> set[str]:
    """The names a file binds to the gateway's own modules (`hermes_cli.cli(...)` is
    the gateway, not an engine internal)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(GATEWAY):
            names.update(a.asname or a.name for a in node.names)
    return names


def scan_file(rel: str, text: str) -> Counter[str]:
    found: Counter[str] = Counter()
    tree = ast.parse(text)
    gateway = _gateway_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in ENGINE_CLI and _name(func.value) not in gateway:
                    found["engine_cli"] += 1
                if func.attr in SUBPROCESS and _name(func.value) == "subprocess":
                    found["subprocess"] += 1
                if func.attr == "connect" and _name(func.value) == "sqlite3":
                    found["sqlite3_connect"] += 1
            if _name(func) == "hermes_python":
                found["hermes_python"] += 1
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "runner"
            and _name(node.value) == "engine"
        ):
            found["engine_runner"] += 1
        elif rel.startswith("actions/") and isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            if "subprocess" in names:
                found["actions_import"] += 1
    return found


def scan(root: Path = SRC) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {rule: {} for rule in RULES}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(INSIDE) or rel == "db/connection.py":
            continue
        for rule, count in scan_file(rel, path.read_text()).items():
            if count:
                out[rule][rel] = count
    return out


def totals(counts: dict[str, dict[str, int]]) -> dict[str, int]:
    return {rule: sum(files.values()) for rule, files in counts.items()}


def load_baseline() -> dict[str, dict[str, int]]:
    data: dict[str, dict[str, int]] = json.loads(BASELINE.read_text())["counts"]
    return data


def write_baseline(counts: dict[str, dict[str, int]]) -> None:
    BASELINE.write_text(
        json.dumps(
            {
                "about": "Hermes calls outside agos_core/hermes_gateway (ADR 0024), per rule "
                "and file. Counts may only go down; lower them here in the same change "
                "(python tests/hermes_gateway_scan.py --update).",
                "totals": totals(counts),
                "counts": counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    now = scan()
    if "--update" in sys.argv:
        old = totals(load_baseline()) if BASELINE.is_file() else {}
        grown = {r: (old[r], n) for r, n in totals(now).items() if r in old and n > old[r]}
        if grown and "--allow-growth" not in sys.argv:
            sys.exit(f"refused: calls outside the gateway grew {grown}")
        write_baseline(now)
    print(json.dumps(totals(now), indent=2))
