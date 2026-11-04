"""Guards against dead leftovers coming back (the step-16 clean-up).

- every module-level function of agos_core is used by agos_core itself (a function
  only tests call is dead code with a test around it);
- nothing outside the migrations names a table or column that was dropped.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
MIGRATIONS = SRC / "db" / "migrations.py"

# Dropped by migration 98 (moved into Hermes: routes, USER.md, mcp_servers, the
# plugin's file and Hermes's own approvals/pairing).
DROPPED = (
    r"\b(FROM|INTO|JOIN|UPDATE|TABLE)\s+(hermes_moves|owner_rules|workspace_apps)\b",
    r"\bhook_(token|secret|filter)\b",
    # Dropped in step 26 (the added folders are Hermes's terminal.docker_volumes).
    r"\b(FROM|INTO|JOIN|UPDATE|TABLE)\s+workspace_folders\b",
)


def _sources() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_every_function_is_used_by_the_app() -> None:
    used: set[str] = set()
    defined: list[tuple[str, str]] = []
    for path in _sources():
        tree = ast.parse(path.read_text())
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.alias):
                used.add(node.name.rsplit(".", 1)[-1])
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
            ):
                used.update(re.findall(r"[A-Za-z_]\w*", node.value))
        for top in tree.body:
            # Decorated ones are reached by their decorator (routes, hooks, fixtures).
            if isinstance(top, ast.FunctionDef | ast.AsyncFunctionDef) and not top.decorator_list:
                defined.append((str(path.relative_to(SRC)), top.name))
    dead = [f"{where}: {name}" for where, name in defined if name not in used]
    assert dead == []


def test_no_code_reads_a_dropped_table_or_column() -> None:
    found = [
        f"{path.relative_to(SRC)}: {m.group(0)}"
        for path in _sources()
        if path != MIGRATIONS
        for pattern in DROPPED
        for m in re.finditer(pattern, path.read_text(), re.IGNORECASE)
    ]
    assert found == []
