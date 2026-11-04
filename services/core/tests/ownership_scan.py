"""Reads, from the code itself, every app_settings key AGOS uses and every table and
column its migrations leave (the inputs of test_ownership.py).

A key is found where the code names it:
- `get_setting(db, KEY, …)` / `set_setting(db, KEY, …)` / `delete_setting(db, KEY)`
  (agos_core.db.app_settings);
- SQL on app_settings: `key = '…'`, `key LIKE '…%'`, or `key = ?` / `LIKE ?` with
  the key passed as the first parameter.
KEY may be a literal, a module constant (in any module), `CONST + x`,
`CONST.format(x)`, an f-string, or a small helper that returns one of those. A
variable part becomes `*`, so `HELD + workspace_id` is `digest.held.*`. A key the
scan can't read is reported as unreadable (and fails the test): write it so it can.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

_SQL_KEY = re.compile(r"\bkey\s*(?:=|LIKE)\s*'([^']*)'", re.I)
_SQL_PARAM = re.compile(r"\bkey\s*(?:=|LIKE)\s*\?", re.I)
_SQL_CONCAT = re.compile(r"'([^']+)'\s*\|\|")  # 'prefix.' || id (migrations)


_TABLE = re.compile(r"\b(FROM|INTO|UPDATE)\s+app_settings\b", re.I)


def _first_param(node: ast.Call) -> ast.expr | None:
    """The first SQL parameter of `execute(sql, (p, …))`."""
    params = node.args[1] if len(node.args) > 1 else None
    if isinstance(params, (ast.Tuple, ast.List)) and params.elts:
        return params.elts[0]
    return None


def _row_key(expr: ast.expr | None) -> bool:
    """`r["key"]`: a key read back from app_settings itself."""
    return (
        isinstance(expr, ast.Subscript)
        and isinstance(expr.slice, ast.Constant)
        and expr.slice.value == "key"
    )


@dataclass(frozen=True)
class Use:
    key: str | None  # None: the scan couldn't read it
    where: str  # file:line


def _modules(skip_migrations: bool = True) -> dict[str, ast.Module]:
    out = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if "__pycache__" in rel or (skip_migrations and rel == "db/migrations.py"):
            continue
        out[rel] = ast.parse(path.read_text(), filename=rel)
    return out


def _constants(modules: dict[str, ast.Module]) -> dict[str, dict[str, str]]:
    """Per module: its module-level string constants (NAME = "…")."""
    out: dict[str, dict[str, str]] = {}
    for rel, tree in modules.items():
        found: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value, targets = node.value, list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                value, targets = node.value, [node.target]
            else:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for t in targets:
                    if isinstance(t, ast.Name):
                        found[t.id] = value.value
        out[rel] = found
    return out


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


class _Resolver:
    def __init__(self, modules: dict[str, ast.Module]) -> None:
        self.modules = modules
        self.consts = _constants(modules)
        self.everywhere: dict[str, str] = {}
        for found in self.consts.values():
            self.everywhere.update(found)

    def key(
        self, expr: ast.expr, rel: str, local: dict[str, ast.expr], depth: int = 0
    ) -> str | None:
        if depth > 6:
            return None
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name):
            if expr.id in local:  # a local name: its value, or a variable part
                return self.key(local[expr.id], rel, {}, depth + 1) or "*"
            if expr.id in self.consts.get(rel, {}):
                return self.consts[rel][expr.id]
            if expr.id in self.everywhere and expr.id.isupper():
                return self.everywhere[expr.id]
            return "*"  # a variable part (a workspace id, an address, …)
        if isinstance(expr, ast.Attribute):
            if expr.attr in self.everywhere and expr.attr.isupper():
                return self.everywhere[expr.attr]
            return "*"
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left = self.key(expr.left, rel, local, depth + 1)
            right = self.key(expr.right, rel, local, depth + 1)
            return None if left is None or right is None else left + right
        if isinstance(expr, ast.JoinedStr):
            parts = []
            for v in expr.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append("*")
            return "".join(parts)
        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Attribute) and func.attr == "format":
                base = self.key(func.value, rel, local, depth + 1)
                return None if base is None else re.sub(r"\{[^}]*\}", "*", base)
            if isinstance(func, ast.Name) and func.id == "str":
                return "*"
            if isinstance(func, ast.Name) and func.id in _functions(self.modules[rel]):
                returns = [
                    n.value
                    for n in ast.walk(_functions(self.modules[rel])[func.id])
                    if isinstance(n, ast.Return) and n.value is not None
                ]
                got = {self.key(r, rel, {}, depth + 1) for r in returns}
                return got.pop() if len(got) == 1 else None
            return None
        if isinstance(expr, ast.Subscript):
            return None
        return None


def _norm(key: str) -> str:
    """`%` (SQL LIKE) as `*`; everything after the first variable part is one `*`
    (a key is a fixed name or a fixed prefix + an id)."""
    key = key.replace("%", "*")
    return key[: key.index("*") + 1] if "*" in key else key


def _scopes(tree: ast.Module) -> list[ast.AST]:
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    found: list[ast.AST] = [n for n in ast.walk(tree) if isinstance(n, kinds)]
    return [*found, tree]


def _locals(scope: ast.AST) -> dict[str, ast.expr]:
    out: dict[str, ast.expr] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                out[t.id] = node.value
    return out


def _sql_text(expr: ast.expr) -> str:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "?" for v in expr.values)
    return ""


def key_uses() -> list[Use]:
    """Every place the code names an app_settings key."""
    modules = _modules()
    resolve = _Resolver(modules)
    uses: set[Use] = set()
    for rel, tree in modules.items():
        if rel == "db/app_settings.py":
            continue  # the accessors themselves
        settings_aliases = {
            a.asname or a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module == "agos_core.db"
            for a in n.names
            if a.name == "app_settings"
        } | {
            a.asname
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for a in n.names
            if a.name == "agos_core.db.app_settings" and a.asname
        }
        for scope in _scopes(tree):
            local = _locals(scope)
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # A bare call or the module's (`app_settings.get_setting(...)`, the split style).
                name = func.id if isinstance(func, ast.Name) else ""
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    name = func.attr if func.value.id in settings_aliases else ""
                where = f"{rel}:{node.lineno}"
                if name in ("get_setting", "set_setting", "delete_setting") and len(node.args) >= 2:
                    got = resolve.key(node.args[1], rel, local)
                    uses.add(Use(_norm(got) if got else None, where))
                    continue
                sql = next((t for a in node.args if "app_settings" in (t := _sql_text(a))), "")
                if not sql or not _TABLE.search(sql):
                    continue
                for literal in _SQL_KEY.findall(sql):
                    uses.add(Use(_norm(literal), where))
                if _SQL_PARAM.search(sql):
                    first = _first_param(node)
                    if _row_key(first):
                        continue  # a key read back by a SELECT … LIKE seen above
                    got = resolve.key(first, rel, local) if first is not None else None
                    uses.add(Use(_norm(got) if got else None, where))
    return sorted(uses, key=lambda u: (u.key or "", u.where))


def deleted_keys() -> set[str]:
    """Keys (patterns) something deletes: `DELETE FROM app_settings WHERE key …` in
    the code (a key read back with `r["key"]` counts for the LIKE patterns the same
    function selected) or in a migration."""
    from agos_core.db.migrations import MIGRATIONS

    out: set[str] = set()
    for sql in MIGRATIONS:
        for statement in sql.split(";"):
            if re.search(r"DELETE FROM app_settings", statement, re.I):
                out.update(_norm(k) for k in _SQL_KEY.findall(statement))
    modules = _modules()
    resolve = _Resolver(modules)
    for rel, tree in modules.items():
        for scope in _scopes(tree):
            local = _locals(scope)
            calls = [n for n in ast.walk(scope) if isinstance(n, ast.Call)]
            texts = [
                (c, next((t for a in c.args if "app_settings" in (t := _sql_text(a))), ""))
                for c in calls
            ]
            selected = {
                _norm(k)
                for _, sql in texts
                if re.search(r"SELECT\b.*\bFROM app_settings", sql, re.I | re.S)
                for k in re.findall(r"\bkey\s+LIKE\s*'([^']*)'", sql, re.I)
            }
            for call, sql in texts:
                func = call.func
                called = func.id if isinstance(func, ast.Name) else ""
                if isinstance(func, ast.Attribute):
                    called = func.attr
                if called == "delete_setting" and len(call.args) >= 2:
                    # The accessor (db/app_settings.py): its key is the second argument.
                    if got := resolve.key(call.args[1], rel, local):
                        out.add(_norm(got))
                    continue
                if not re.search(r"DELETE FROM app_settings", sql, re.I):
                    continue
                out.update(_norm(k) for k in _SQL_KEY.findall(sql))
                first = _first_param(call)
                if _row_key(first):
                    out.update(selected)
                elif first is not None and (got := resolve.key(first, rel, local)):
                    out.add(_norm(got))
    return out


def migration_keys() -> set[str]:
    """Keys the migrations put into app_settings and no later migration deletes."""
    from agos_core.db.migrations import MIGRATIONS

    alive: dict[str, int] = {}
    for index, sql in enumerate(MIGRATIONS):
        for statement in sql.split(";"):
            if re.search(r"INSERT(\s+OR\s+\w+)?\s+INTO\s+app_settings", statement, re.I):
                values = re.search(r"(?:SELECT|VALUES\s*\()\s*'([^']+)'(\s*\|\|)?", statement, re.I)
                if values:
                    key = values.group(1) + ("*" if values.group(2) else "")
                    alive[_norm(key)] = index
            if re.search(r"DELETE FROM app_settings", statement, re.I):
                for literal in _SQL_KEY.findall(statement):
                    pattern = _norm(literal)
                    for key in list(alive):
                        if key == pattern or (
                            pattern.endswith("*") and key.startswith(pattern[:-1])
                        ):
                            del alive[key]
    return set(alive)


def schema() -> dict[str, list[str]]:
    """{table or view: [columns]} as every migration leaves it."""
    from agos_core.db import hermes_text
    from agos_core.db.connection import _migrate

    db = sqlite3.connect(":memory:")
    hermes_text.install(db)
    _migrate(db)
    out = {}
    for (name,) in db.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ):
        out[str(name)] = [str(r[1]) for r in db.execute(f'PRAGMA table_info("{name}")')]
    db.close()
    return out


# ---- files AGOS names outside its database ---------------------------------------

_FILE = re.compile(
    r"^[\w.\-{}/]*[\w}]\.(json|jsonl|deliveries|yaml|yml|md|txt|log|csv|db|token|key|lock"
    r"|pid|py|zip|conf|tmp|service|png|jpg|webp|svg|ok)$"
)
# The registry itself names every registered file: reading it would make every entry
# look "named" and the "none is gone" check could never fail. It is the db/ownership/
# package: its tables by area, its keys, its files part, re-exported by __init__.py.
REGISTRY = "db/ownership/"
REGISTRY_MODULES = frozenset(REGISTRY + p.name for p in (SRC / "db" / "ownership").glob("*.py"))


def _piece(
    value: ast.expr, rel: str, consts: dict[str, dict[str, str]], every: dict[str, str]
) -> str:
    """One part of an f-string: its text, an UPPER module constant's value (so
    `f"{JOB_PREFIX}{id}.py"` is the exact `agos-job-{}.py`), else `{}`."""
    if isinstance(value, ast.Constant):
        return str(value.value)
    inner = value.value if isinstance(value, ast.FormattedValue) else value
    if isinstance(value, ast.FormattedValue) and value.format_spec is None:
        name = (
            inner.id
            if isinstance(inner, ast.Name)
            else inner.attr
            if isinstance(inner, ast.Attribute)
            else ""
        )
        if name.isupper():
            found = consts.get(rel, {}).get(name, every.get(name))
            if found is not None:
                return found
    return "{}"


def file_names() -> dict[str, set[str]]:
    """Every file name the code names (a literal or an f-string, its variable parts
    as `{}`), with the modules that name it: what the files registry must cover.
    Bare extensions (".json") and search globs ("*/SKILL.md") are not files. The
    registry modules themselves are not read (see REGISTRY_MODULES)."""
    found: dict[str, set[str]] = {}
    modules = {k: v for k, v in _modules(skip_migrations=True).items() if k not in REGISTRY_MODULES}
    consts = _constants(modules)
    every: dict[str, str] = {}
    for c in consts.values():
        every.update(c)
    for name, tree in modules.items():
        parts = {
            id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values
        }  # an f-string's pieces are read with it, not alone
        for node in ast.walk(tree):
            if id(node) in parts:
                continue
            text: str | None = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
            elif isinstance(node, ast.JoinedStr):
                text = "".join(_piece(v, name, consts, every) for v in node.values)
            if not text or "*" in text or not _FILE.match(text):
                continue
            if re.fullmatch(r"\.\w+", text) or text.startswith("/"):
                continue  # an extension, or an absolute path (a sandbox's own /tmp)
            found.setdefault(text, set()).add(name)
    return found
