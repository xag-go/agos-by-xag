"""The check that a Hermes source tree still has each contract entry as AGOS uses
it (read with `ast`, never imported), its report and its CLI
(`python -m agos_core.engine.hermes_contract`; engine/hermes_contract.py).

Must not: import Hermes's code (it is read as text) or hold contract entries (uses_*.py).
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.engine.contract.base import Use
from agos_core.engine.contract.entries import CONTRACT
from agos_core.engine.hermes_contract_ast import Params, call_problems, params_of
from agos_core.engine.hermes_contract_ast import binds as _binds
from agos_core.engine.hermes_contract_ast import decorated as _decorated
from agos_core.engine.hermes_contract_ast import top_level as _top_level

__all__ = [
    "Finding",
    "Found",
    "Tree",
    "check",
    "check_one",
    "default_root",
    "is_hermes",
    "main",
    "report",
]

# ---- reading a Hermes source tree ---------------------------------------------------------


@dataclass
class Found:
    kind: str  # function / class / constant / module / lazy
    node: Any = None
    module: str = ""
    method_of: str = ""  # a method: the class it is defined in


class Tree:
    """A Hermes checkout, read with ast (never imported)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._parsed: dict[str, ast.Module | None] = {}

    def path(self, module: str) -> Path | None:
        base = self.root.joinpath(*module.split("."))
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def parse(self, module: str) -> ast.Module | None:
        if module not in self._parsed:
            path = self.path(module)
            try:
                self._parsed[module] = ast.parse(path.read_text()) if path else None
            except (OSError, SyntaxError, ValueError):
                self._parsed[module] = None
        return self._parsed[module]

    def _package(self, module: str) -> str:
        path = self.path(module)
        if path is not None and path.name == "__init__.py":
            return module
        return module.rpartition(".")[0]

    def _source_of(self, module: str, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        base = self._package(module)
        for _ in range(node.level - 1):
            base = base.rpartition(".")[0]
        return f"{base}.{node.module}" if node.module else base

    def find(self, module: str, name: str, depth: int = 0) -> Found | None:
        """`name` at the top of `module` (following Hermes's own re-exports)."""
        if depth > 8:
            return None
        tree = self.parse(module)
        if tree is None:
            return None
        lazy = False
        for stmt in _top_level(tree.body):
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == name:
                return Found("function", stmt, module)
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "__getattr__":
                lazy = True
            if isinstance(stmt, ast.ClassDef) and stmt.name == name:
                return Found("class", stmt, module)
            if isinstance(stmt, ast.Assign) and any(_binds(t, name) for t in stmt.targets):
                return Found("constant", stmt, module)
            if isinstance(stmt, ast.AnnAssign) and _binds(stmt.target, name):
                return Found("constant", stmt, module)
            if isinstance(stmt, ast.ImportFrom):
                for alias in stmt.names:
                    if (alias.asname or alias.name) != name:
                        continue
                    source = self._source_of(module, stmt)
                    found = self.find(source, alias.name, depth + 1)
                    if found is None and self.parse(f"{source}.{alias.name}") is not None:
                        found = Found("module", None, f"{source}.{alias.name}")
                    if found is not None:
                        return found
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    if alias.asname == name and self.parse(alias.name) is not None:
                        return Found("module", None, alias.name)
        if self.parse(f"{module}.{name}") is not None:
            return Found("module", None, f"{module}.{name}")
        return Found("lazy", None, module) if lazy else None

    def bases(self, cls: Found) -> list[Found]:
        out = []
        for base in cls.node.bases:
            found: Found | None = None
            if isinstance(base, ast.Name):
                found = self.find(cls.module, base.id)
            elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
                holder = self.find(cls.module, base.value.id)
                if holder is not None and holder.kind == "module":
                    found = self.find(holder.module, base.attr)
            if found is not None and found.kind == "class":
                out.append(found)
        return out

    def member(self, cls: Found, name: str, seen: set[int] | None = None) -> Found | None:
        """A method or attribute of a class, its bases included (Hermes's MRO, near enough)."""
        seen = seen if seen is not None else set()
        if id(cls.node) in seen:
            return None
        seen.add(id(cls.node))
        for stmt in _top_level(cls.node.body):
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == name:
                if _decorated(stmt, "property") or _decorated(stmt, "cached_property"):
                    return Found("constant", stmt, cls.module, cls.node.name)
                return Found("function", stmt, cls.module, cls.node.name)
            if isinstance(stmt, ast.Assign) and any(_binds(t, name) for t in stmt.targets):
                return Found("constant", stmt, cls.module, cls.node.name)
            if isinstance(stmt, ast.AnnAssign) and _binds(stmt.target, name):
                return Found("constant", stmt, cls.module, cls.node.name)
        for stmt in cls.node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(stmt):
                    target = node.target if isinstance(node, ast.AnnAssign) else None
                    targets = node.targets if isinstance(node, ast.Assign) else [target]
                    flat: list[Any] = []
                    for t in targets:
                        flat.extend(t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])
                    for t in flat:
                        if (
                            isinstance(t, ast.Attribute)
                            and isinstance(t.value, ast.Name)
                            and t.value.id == "self"
                            and t.attr == name
                        ):
                            return Found("constant", node, cls.module, cls.node.name)
        for base in self.bases(cls):
            found = self.member(base, name, seen)
            if found is not None:
                return found
        return None

    def hooks(self) -> set[str]:
        tree = self.parse("hermes_cli.plugins")
        names: set[str] = set()
        for stmt in _top_level(tree.body if tree else []):
            if isinstance(stmt, ast.Assign):
                targets: list[ast.expr] = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            if any(_binds(t, "VALID_HOOKS") for t in targets) and stmt.value is not None:
                for node in ast.walk(stmt.value):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        names.add(node.value)
        return names


def _dataclass_fields(
    tree: Tree, cls: Found, seen: set[int] | None = None
) -> tuple[set[str], set[str]] | None:
    """(fields, required fields) of a dataclass, its dataclass bases included; None
    when it isn't one."""
    seen = seen if seen is not None else set()
    seen.add(id(cls.node))
    fields: set[str] = set()
    required: set[str] = set()
    is_dataclass = any(
        (isinstance(d, ast.Name) and d.id == "dataclass")
        or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
        or (
            isinstance(d, ast.Call)
            and getattr(d.func, "id", getattr(d.func, "attr", "")) == "dataclass"
        )
        for d in cls.node.decorator_list
    )
    for base in tree.bases(cls):
        if id(base.node) in seen:
            continue
        inherited = _dataclass_fields(tree, base, seen)
        if inherited is not None:
            fields |= inherited[0]
            required |= inherited[1]
            is_dataclass = True
    if not is_dataclass:
        return None
    for stmt in cls.node.body:
        if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
            continue
        if "ClassVar" in ast.unparse(stmt.annotation):
            continue
        value = stmt.value
        if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "field":
            kws = {k.arg: k.value for k in value.keywords}
            init = kws.get("init")
            if isinstance(init, ast.Constant) and init.value is False:
                continue
            fields.add(stmt.target.id)
            if "default" not in kws and "default_factory" not in kws:
                required.add(stmt.target.id)
            continue
        fields.add(stmt.target.id)
        if value is None:
            required.add(stmt.target.id)
    return fields, required


@dataclass(frozen=True)
class Finding:
    use: Use
    ok: bool
    why: str = ""


def check_one(tree: Tree, use: Use, hooks: set[str] | None = None) -> Finding:
    def bad(why: str) -> Finding:
        return Finding(use, False, why)

    if use.kind == "hook":
        known = tree.hooks() if hooks is None else hooks
        return Finding(use, True) if use.name in known else bad("not one of Hermes's plugin hooks")
    if use.kind in ("module", "text"):
        path = tree.path(use.module)
        if path is None:
            return bad("module is gone")
        if use.kind == "text" and use.text not in path.read_text():
            return bad(f"no longer says {use.text!r}")
        return Finding(use, True)
    if tree.parse(use.module) is None:
        return bad("module is gone")
    head, _, member = use.name.partition(".")
    found = tree.find(use.module, head)
    if found is None:
        return bad("is gone")
    if found.kind == "lazy":
        return Finding(use, True, "module __getattr__: not checked further")
    if member:
        if found.kind != "class":
            return bad(f"'{head}' is no longer a class")
        owner = found
        found = tree.member(owner, member)
        if found is None:
            return bad("is gone")
    kind = use.kind
    if kind in ("attr", "constant"):
        return Finding(use, True)
    if kind == "class":
        if found.kind != "class":
            return bad("is no longer a class")
        if not use.kw and not use.pos:
            return Finding(use, True)
        init = tree.member(found, "__init__")
        if init is not None and init.kind == "function":
            problems = call_problems(params_of(init.node, bound=True), use.pos, use.kw)
            return bad("; ".join(problems)) if problems else Finding(use, True)
        fields = _dataclass_fields(tree, found)
        if fields is None:
            return Finding(use, True, "no __init__ / dataclass fields to check")
        names, required = fields
        params = Params(positional=[], keyword=names, required_keyword=required, varkw=False)
        problems = call_problems(params, 0, use.kw)
        return bad("; ".join(problems)) if problems else Finding(use, True)
    if found.kind == "class" and kind == "function":
        init = tree.member(found, "__init__")
        if init is None or init.kind != "function":
            return Finding(use, True)
        found = init
    if found.kind != "function":
        if isinstance(found.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return Finding(use, True)  # a property
        return Finding(use, True, "not a def (an alias); signature not checked")
    bound = bool(member) or bool(found.method_of)
    params = params_of(found.node, bound=bound)
    if kind == "override":
        mine = set(use.accepts)
        problems = []
        for name in params.positional + sorted(params.keyword - set(params.positional)):
            if name not in mine and not use.more:
                problems.append(f"Hermes now passes '{name}' (AGOS's version doesn't take it)")
        theirs = params.keyword | set(params.positional)
        for name in use.accepts:
            if name not in theirs:
                problems.append(f"no parameter '{name}' any more (AGOS's version takes it)")
        order = [n for n in params.positional if n in mine]
        if not problems and order != [n for n in use.accepts if n in order]:
            problems.append(f"parameter order is now ({params.shown()})")
        mine_pos = [n for n in use.accepts if n in params.positional]
        if use.more and params.positional[: len(mine_pos)] != mine_pos:
            problems.append(
                f"parameters are now ({params.shown()}), AGOS reads ({', '.join(use.accepts)}) first"
            )
        return bad("; ".join(dict.fromkeys(problems))) if problems else Finding(use, True)
    problems = call_problems(params, use.pos, use.kw)
    return bad("; ".join(problems)) if problems else Finding(use, True)


def default_root() -> Path:
    return Path(os.environ.get("HERMES_AGENT_SRC") or Path.home() / ".hermes" / "hermes-agent")


def is_hermes(root: Path) -> bool:
    return (Path(root) / "hermes_cli" / "plugins.py").is_file()


def check(root: Path | None = None, uses: Iterable[Use] = CONTRACT) -> list[Finding]:
    tree = Tree(Path(root) if root is not None else default_root())
    hooks = tree.hooks()
    return [check_one(tree, use, hooks) for use in uses]


def report(findings: list[Finding], root: Path) -> str:
    broken = [f for f in findings if not f.ok]
    lines = [f"Hermes contract check: {root}"]
    for f in findings:
        mark = "OK  " if f.ok else "FAIL"
        note = f" — {f.why}" if f.why else ""
        tail = f"  [{f.use.area}: {f.use.feature}]" if not f.ok else ""
        lines.append(f"{mark} {f.use.kind:<8} {f.use.key}{note}{tail}")
    by_area: dict[str, int] = {}
    for f in findings:
        by_area[f.use.area] = by_area.get(f.use.area, 0) + 1
    lines.append("")
    lines.append("entries by area: " + ", ".join(f"{a} {n}" for a, n in sorted(by_area.items())))
    lines.append(
        f"{len(findings)} entries: {len(findings) - len(broken)} ok, {len(broken)} broken"
        + ("" if not broken else " — DO NOT upgrade Hermes until AGOS is changed for these")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]).expanduser() if args else default_root()
    if not is_hermes(root):
        print(f"not a Hermes source tree: {root}", file=sys.stderr)
        return 2
    findings = check(root)
    print(report(findings, root))
    return 1 if any(not f.ok for f in findings) else 0
