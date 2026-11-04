"""Finds SQL that reads or writes a row by its id without the workspace in sight.

Workspaces are fully isolated: every read by id is scoped by `workspace_id` in the same
query, or the same function re-checks that the row belongs to the workspace. This scan
walks the SQL text in `db/` and `actions/` (string literals, implicit concatenation and
f-string parts) and reports each statement whose WHERE picks rows by `id`, `rowid` or
`<x>_id` (`= ?`, `IN (?, ...)`, `:name`; not `IN (SELECT ...)`) with no `workspace_id` in
the statement and no ownership re-check in its function: a comparison on the ROW's
workspace (`row["workspace_id"]`, `found.workspace_id`), an ownership helper by its exact
name (`in_workspace`, `belongs`), its own scoped query, or a call with the workspace to
a guard (a function anywhere in agos_core whose query is scoped, or that takes the
workspace and re-checks with it; `asyncio.to_thread(f, ...)` counts as calling `f`).

A finding is also scoped by its callers (workspace_scope_callers.py) when EVERY function
that names its function re-checks, or is in turn only named by such functions, up to:
- a route of the owner's machine-wide pages (no `{workspace_id}` in its path; only the
  owner's web holds their internal token, a workspace's Hermes has only its bridge);
- an entry point recorded in workspace_scope_guards.json with the guard that scopes it
  (a machine loop walking its own rows, a one-off move at start).
A function named by nothing (a route) or in a table at module level stays a finding.

Each finding gets a risk:
- high: the table has its own `workspace_id` column (the query could scope itself and
  doesn't), the statement writes (UPDATE/DELETE) and it sits in actions/, where an id
  from a caller meets the database;
- medium: the same table kind, for a read, or a db/ repository write by primary key
  (the caller must hold an id it already scoped: check the callers);
- low: the table has no `workspace_id` column (a child row reached through its parent's
  id, or a machine-wide table); scoped by whoever got the parent id.

The baseline (workspace_scope_baseline.json) only shrinks: tests/security/
test_workspace_scope.py fails on a new finding and on a fixed one still recorded.
`python tests/security/workspace_scope_scan.py [--update | --report [--why]]` from
services/core (`--why`: the unchecked entry points that keep each finding open).
"""

from __future__ import annotations

import ast
import functools
import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

if __package__ in (None, ""):  # run as a script from services/core
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from security import workspace_scope_callers as callers

__all__ = [
    "BASELINE",
    "GUARDS",
    "Finding",
    "allowed_roots",
    "explained",
    "findings",
    "keyed",
    "scan_functions",
    "scan_source",
    "workspace_tables",
]

CORE = Path(__file__).resolve().parents[2]
SRC = CORE / "src" / "agos_core"
ROOTS = ("db", "actions")
BASELINE = Path(__file__).with_name("workspace_scope_baseline.json")
GUARDS = Path(__file__).with_name("workspace_scope_guards.json")
# A workspace's own Hermes calls these routers with its bridge key (not owner pages).
_BRIDGE_ROUTES = re.compile(r"^api/(hermes_bridge|bridge_\w+)\.py$")

_SQL = re.compile(r"\b(SELECT|UPDATE|DELETE)\b", re.I)
_WHERE = re.compile(r"\bWHERE\b(?P<cond>.*)", re.I | re.S)
_BY_ID = re.compile(
    # `IN (SELECT ...)` picks ids in SQL itself (no id from a caller): not a finding.
    r"(?<![\w.])(?:\w+\.)?(?P<col>rowid|id|\w+_id)\s*(?:=\s*(?:\?|:\w+)|\bIN\s*\((?!\s*SELECT\b))",
    re.I,
)
_TABLE = re.compile(r"\b(?:FROM|UPDATE|INTO|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
# Ownership helpers by their exact name. (A substring match took `tell_owner`,
# `shown` and `unknown` for re-checks and hid findings.)
_OWN_CALL = re.compile(r"^_?(in_workspace|belongs|check_workspace)$")
# An argument that carries the caller's workspace (`workspace_id`, `ws`, `row.workspace_id`).
_WS_ARG = re.compile(r"\b(workspace_id|ws)\b")


@dataclass(frozen=True)
class Finding:
    path: str  # relative to src/agos_core
    function: str
    kind: str  # SELECT / UPDATE / DELETE
    table: str
    column: str
    risk: str
    line: int
    checked_by: str | None = None  # the callers that re-check (then not a finding)

    @property
    def key(self) -> str:
        return f"{self.path}::{self.function}::{self.kind} {self.table} by {self.column}"


def workspace_tables() -> set[str]:
    """Tables that have their own workspace_id column (the real schema)."""
    sys.path.insert(0, str(CORE / "src"))
    from agos_core.db.connection import open_database

    db = open_database(":memory:")
    try:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {
            n
            for n in names
            if any(
                c[1] == "workspace_id"
                for c in db.execute("SELECT * FROM pragma_table_info(?)", (n,))
            )
        }
    finally:
        db.close()


def _scoped_sql(func: ast.AST) -> bool:
    """The function itself runs SQL scoped by workspace_id (it loaded the row there)."""
    for node in ast.walk(func):
        for text, _line in _texts_of(node):
            if _SQL.search(text) and _WHERE.search(text) and "workspace_id" in text:
                return True
    return False


def _rechecks(func: ast.AST, is_guard: Callable[[ast.Call], bool]) -> bool:
    """An ownership re-check in the function: a comparison on the row's workspace_id,
    a call to an ownership helper, its own workspace-scoped query, or a call with the
    workspace to a guard (a helper whose query is scoped, `_one(core, workspace_id, id)`,
    or that re-checks with the workspace it takes)."""
    if _scoped_sql(func):
        return True
    for node in ast.walk(func):
        if isinstance(node, ast.Compare):
            if any(_rows_workspace(side) for side in (node.left, *node.comparators)):
                return True
        elif isinstance(node, ast.Call):
            call = _unwrapped(node)
            if _OWN_CALL.search(ast.unparse(call.func).rsplit(".", 1)[-1]):
                return True
            args = [ast.unparse(a) for a in call.args] + [
                ast.unparse(k.value) for k in call.keywords
            ]
            if any(_WS_ARG.search(a) for a in args) and is_guard(call):
                return True
    return False


# Runs its first argument with the rest: `asyncio.to_thread(f, core, workspace_id, id)`.
_RUNNERS = {"to_thread", "in_thread", "run_in_threadpool"}


def _unwrapped(call: ast.Call) -> ast.Call:
    """The call a thread runner makes (`f(core, workspace_id, id)`), else the call itself."""
    name = ast.unparse(call.func).rsplit(".", 1)[-1]
    if name in _RUNNERS and call.args:
        return ast.Call(func=call.args[0], args=call.args[1:], keywords=call.keywords)
    return call


def _short_names(names: set[str]) -> Callable[[ast.Call], bool]:
    """A guard test by the callee's bare name (one module on its own: `scan_source`)."""
    return lambda call: ast.unparse(call.func).rsplit(".", 1)[-1] in names


def _rows_workspace(node: ast.AST) -> bool:
    """`row["workspace_id"]` or `found.workspace_id`: the row's own workspace (a bare
    `workspace_id is None` checks the caller's argument, not the row)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "workspace_id"
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "workspace_id"
    if isinstance(node, ast.Call):  # str(row["workspace_id"]), row.get("workspace_id")
        return any(_rows_workspace(a) for a in node.args) or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and any(isinstance(a, ast.Constant) and a.value == "workspace_id" for a in node.args)
        )
    return False


def _functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """(qualified name, node) of every function, innermost last; module level as '<module>'."""
    stack: list[tuple[str, ast.AST]] = [("", tree)]
    while stack:
        prefix, node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    yield name, child
                stack.append((name + ".", child))


def _modules() -> Iterator[tuple[str, list[tuple[str, ast.AST]]]]:
    for root in ROOTS:
        for path in sorted((SRC / root).rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            yield path.relative_to(SRC).as_posix(), list(_functions(tree))


def findings(tables: set[str] | None = None) -> list[Finding]:
    """Every unexplained finding: neither its function nor all of its callers re-check."""
    return [f for f in _all(tables) if f.checked_by is None]


def explained(tables: set[str] | None = None) -> list[Finding]:
    """The findings whose every caller re-checks the workspace (not in the baseline)."""
    return [f for f in _all(tables) if f.checked_by is not None]


@dataclass
class _Context:
    graph: callers.Graph
    guards: set[tuple[str, str]]
    allowed: dict[str, str]

    def is_guard(self, rel: str) -> Callable[[ast.Call], bool]:
        return lambda call: self.graph.callee(rel, call) in self.guards

    def rechecks(self, rel: str, name: str, node: ast.AST) -> bool:
        return (
            f"{rel}::{name}" in self.allowed
            or _owner_route(rel, node, self.graph.trees.get(rel))
            or _rechecks(node, self.is_guard(rel))
        )


@functools.cache
def _context() -> _Context:
    graph = callers.build(SRC)
    return _Context(graph, _guards(graph), allowed_roots())


def _all(tables: set[str] | None) -> list[Finding]:
    scoped = workspace_tables() if tables is None else tables
    ctx = _context()
    out: dict[str, Finding] = {}
    for rel, funcs in _modules():
        for finding in scan_functions(rel, funcs, scoped, ctx.is_guard(rel)):
            out.setdefault(finding.key, finding)
    for key, finding in out.items():
        if ctx.graph.checked(finding.path, finding.function, ctx.rechecks):
            refs = ctx.graph.refs.get((finding.path, finding.function.split(".")[0]), [])
            where = sorted({f"{r.path}::{r.function}" for r in refs}) or ["allowed"]
            out[key] = replace(finding, checked_by=", ".join(where))
    return sorted(out.values(), key=lambda f: f.key)


def blockers(finding: Finding) -> list[str]:
    """What keeps a finding open: the unchecked entry points above it."""
    ctx = _context()
    return ctx.graph.blockers(finding.path, finding.function, ctx.rechecks)


def used_roots() -> set[str]:
    """The allowed roots some finding's call chain really reaches (the rest are stale)."""
    ctx = _context()
    bare = _Context(ctx.graph, ctx.guards, {})
    reached: set[str] = set()
    for finding in _all(None):
        reached |= ctx.graph.walk(finding.path, finding.function, bare.rechecks)
    return reached & set(ctx.allowed)


def allowed_roots() -> dict[str, str]:
    """Entry points recorded with the guard that scopes them (GUARDS: path::function ->
    one line naming the guard): a machine loop walking its own rows, a one-off move
    at start, an owner-only page. Every function they reach counts as checked."""
    found: dict[str, str] = json.loads(GUARDS.read_text())
    return found


def _prefixed(tree: ast.Module | None) -> bool:
    """The module's `router` puts the workspace (or the bridge) in a prefix."""
    for node in tree.body if tree is not None else []:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "router" for t in node.targets
        ):
            return any(
                isinstance(k.value, ast.Constant) and "{" in str(k.value.value)
                for k in getattr(node.value, "keywords", [])
                if k.arg == "prefix"
            )
    return False


def _owner_route(rel: str, func: ast.AST, tree: ast.Module | None) -> bool:
    """A route of the owner's own machine-wide pages: `@router.<verb>(path)` in api/
    with no `{workspace_id}` in its path. Those routers need the internal token
    (api/app.py `protected`), which only the owner's web holds (the cage keeps it from
    every agent); a workspace's Hermes reaches the core only through the bridge router
    (api/hermes_bridge.py, its own key per workspace), never one of these."""
    if not rel.startswith("api/") or _BRIDGE_ROUTES.match(rel) or _prefixed(tree):
        return False
    for deco in getattr(func, "decorator_list", []):
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and isinstance(deco.func.value, ast.Name)
            and deco.func.value.id == "router"
            and deco.args
            and isinstance(deco.args[0], ast.Constant)
            and isinstance(deco.args[0].value, str)
        ):
            return "{workspace_id}" not in deco.args[0].value
    return False


def _calls_into(
    graph: callers.Graph, rel: str, known: frozenset[tuple[str, str]]
) -> Callable[[ast.Call], bool]:
    def test(call: ast.Call) -> bool:
        return graph.callee(rel, call) in known

    return test


def _guards(graph: callers.Graph) -> set[tuple[str, str]]:
    """Top-level functions anywhere in agos_core whose own query is workspace-scoped
    (ask_row, in_workspace...), and those that take the workspace and re-check with it
    (`_row(core, workspace_id, item_id)` comparing the row's workspace_id)."""
    tops = {
        (rel, name): f
        for (rel, name), f in graph.functions.items()
        if "." not in name and isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    found = {key for key, f in tops.items() if _scoped_sql(f)}
    while True:
        more = {
            (rel, name)
            for (rel, name), f in tops.items()
            if (rel, name) not in found
            and isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(_WS_ARG.search(a.arg) for a in f.args.args + f.args.kwonlyargs)
            and _rechecks(f, _calls_into(graph, rel, frozenset(found)))
        }
        if not more:
            return found
        found |= more


def scan_functions(
    rel: str,
    funcs: list[tuple[str, ast.AST]],
    scoped: set[str],
    is_guard: Callable[[ast.Call], bool],
) -> Iterator[Finding]:
    """The findings of one module's functions."""
    inner: dict[int, str] = {}
    for name, func in funcs:  # outer first: a nested function's nodes are its own
        for node in ast.walk(func):
            inner[id(node)] = name
    for name, func in funcs:
        if _rechecks(func, is_guard):
            continue
        for node in ast.walk(func):
            if inner.get(id(node)) != name:
                continue
            for text, line in _texts_of(node):
                finding = _check(text, rel, name, line, scoped)
                if finding is not None:
                    yield finding


def scan_source(source: str, rel: str, scoped: set[str]) -> list[Finding]:
    """The findings of one module's text (fetchers from that module only)."""
    funcs = list(_functions(ast.parse(source)))
    fetchers = {name.rsplit(".", 1)[-1] for name, f in funcs if _scoped_sql(f)}
    return list(scan_functions(rel, funcs, scoped, _short_names(fetchers)))


def _texts_of(node: ast.AST) -> Iterator[tuple[str, int]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value, node.lineno
    elif isinstance(node, ast.JoinedStr):
        yield (
            "".join(
                v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "?"
                for v in node.values
            ),
            node.lineno,
        )


def _check(text: str, rel: str, function: str, line: int, scoped: set[str]) -> Finding | None:
    kind = _SQL.search(text)
    where = _WHERE.search(text)
    if kind is None or where is None or "workspace_id" in text:
        return None
    by_id = [m.group("col") for m in _BY_ID.finditer(where.group("cond"))]
    if not by_id:
        return None
    tables = _TABLE.findall(text)
    if not tables:
        return None
    table = tables[0]
    verb = kind.group(1).upper()
    if table not in scoped:
        risk = "low"
    elif verb in ("UPDATE", "DELETE") and rel.startswith("actions/"):
        risk = "high"
    else:
        risk = "medium"
    return Finding(rel, function, verb, table, by_id[0].lower(), risk, line)


def keyed(found: list[Finding]) -> dict[str, str]:
    return {f.key: f.risk for f in found}


def main(argv: list[str]) -> int:
    found = findings()
    if "--update" in argv:
        BASELINE.write_text(json.dumps(keyed(found), indent=2, sort_keys=True) + "\n")
        print(f"workspace scope: {len(found)} findings recorded")
        return 0
    if "--report" in argv:
        for f in found:
            print(f"{f.risk:6} {f.path}:{f.line} {f.function} {f.kind} {f.table} by {f.column}")
            if "--why" in argv:
                for root in blockers(f):
                    print(f"         open at {root}")
    counts = {r: sum(1 for f in found if f.risk == r) for r in ("high", "medium", "low")}
    print(f"workspace scope: {len(found)} findings {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
