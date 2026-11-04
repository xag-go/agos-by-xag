"""Who calls a function that runs SQL by id, and whether every one of them re-checked.

Owns: the reference graph of `agos_core` (each top-level function -> the functions that
name it: a call, or the function passed on, e.g. to `asyncio.to_thread`), and the
caller rule of the workspace-scope scan: a repository function that picks a row by id
is scoped when EVERY function that names it re-checks the workspace first (or is itself
only named by functions that do). A function nobody names (a route, a registry entry),
or one named at module level (a dispatch table), is never scoped by its callers.
Must not: decide what a re-check is (the scan's `_rechecks` does) or read the database.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Graph", "Ref", "build"]

_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Ref:
    path: str  # relative to src/agos_core
    function: str  # qualified name of the function that names it ("<module>": none)
    line: int


Key = tuple[str, str]  # (path, top-level function name)
Rechecks = Callable[[str, str, ast.AST], bool]  # (path, qualified name, node) -> re-checks


@dataclass
class Graph:
    functions: dict[tuple[str, str], ast.AST]  # (path, qualified name) -> node
    refs: dict[Key, list[Ref]]  # who names each top-level function
    resolve: Callable[[str, ast.AST], Key | None]  # a Name/Attribute in a module -> its def
    trees: dict[str, ast.Module]  # path -> its parsed module

    def callee(self, path: str, call: ast.Call) -> Key | None:
        """The top-level function a call in module `path` runs (None: a method, a
        builtin, anything outside agos_core)."""
        return self.resolve(path, call.func)

    def checked(self, path: str, name: str, rechecks: Rechecks) -> bool:
        """Every function that names `path::name` re-checks the workspace (or is in
        turn only named by such functions)."""
        memo: dict[tuple[str, str], bool] = {}
        return self._checked((path, name.split(".")[0]), rechecks, memo, set())

    def blockers(self, path: str, name: str, rechecks: Rechecks) -> list[str]:
        """The functions up the call chains that neither re-check nor are only named by
        functions that do (what keeps `path::name` a finding): fix or record those."""
        return sorted(r for r in self.walk(path, name, rechecks) if " " in r)

    def walk(self, path: str, name: str, rechecks: Rechecks) -> set[str]:
        """Every `path::function` up the call chains of `path::name` until a re-check,
        plus the blockers (`path::function (...)` / `path:line (module level)`)."""
        start = (path, name.split(".")[0])
        out: set[str] = set()
        seen: set[tuple[str, str]] = set()
        todo = [start]
        while todo:
            key = todo.pop()
            if key in seen:
                continue
            seen.add(key)
            out.add(f"{key[0]}::{key[1]}")
            node = self.functions.get(key)
            if key != start and node is not None and rechecks(key[0], key[1], node):
                continue
            refs = self.refs.get(key, [])
            if not refs:
                out.add(f"{key[0]}::{key[1]} (named by nothing: a route or a registry entry)")
            for ref in refs:
                if ref.function == "<module>":
                    out.add(f"{ref.path}:{ref.line} (module level)")
                    continue
                parts = ref.function.split(".")
                inner = [".".join(parts[:d]) for d in range(len(parts), 0, -1)]
                out.update(f"{ref.path}::{q}" for q in inner)
                if any(
                    (n := self.functions.get((ref.path, q))) is not None
                    and rechecks(ref.path, q, n)
                    for q in inner
                ):
                    continue
                todo.append((ref.path, parts[0]))
        return out

    def _checked(
        self,
        key: tuple[str, str],
        rechecks: Rechecks,
        memo: dict[tuple[str, str], bool],
        busy: set[tuple[str, str]],
    ) -> bool:
        if key in memo:
            return memo[key]
        if key in busy:
            return False  # a cycle proves nothing
        node = self.functions.get(key)
        if node is not None and rechecks(key[0], key[1], node):
            return True
        busy.add(key)
        refs = self.refs.get(key, [])
        ok = bool(refs) and all(self._ref_checked(r, rechecks, memo, busy) for r in refs)
        busy.discard(key)
        memo[key] = ok
        return ok

    def _ref_checked(
        self,
        ref: Ref,
        rechecks: Rechecks,
        memo: dict[tuple[str, str], bool],
        busy: set[tuple[str, str]],
    ) -> bool:
        if ref.function == "<module>":
            return False
        parts = ref.function.split(".")
        # The naming function, or any function around it, re-checked (a closure
        # shares its scope); else the outermost one must be checked by its callers.
        for depth in range(len(parts), 0, -1):
            node = self.functions.get((ref.path, ".".join(parts[:depth])))
            if node is not None and rechecks(ref.path, ".".join(parts[:depth]), node):
                return True
        return self._checked((ref.path, parts[0]), rechecks, memo, busy)


def _dotted(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["agos_core", *parts])


def _functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    stack: list[tuple[str, ast.AST]] = [("", tree)]
    while stack:
        prefix, node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (*_FUNC, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if isinstance(child, _FUNC):
                    yield name, child
                stack.append((name + ".", child))


def _imports(
    tree: ast.Module, dotted: str, is_package: bool
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """(module aliases: name -> dotted module, imported names: name -> (module, name))."""
    package = dotted if is_package else dotted.rsplit(".", 1)[0]
    modules: dict[str, str] = {}
    names: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")
                up = up[: len(up) - (node.level - 1)]
                base = ".".join(up + ([base] if base else []))
            for alias in node.names:
                local = alias.asname or alias.name
                modules[local] = f"{base}.{alias.name}"
                names[local] = (base, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
    return modules, names


def build(src: Path) -> Graph:
    """The reference graph of every module under `src` (the agos_core package)."""
    trees: dict[str, ast.Module] = {}
    for path in sorted(src.rglob("*.py")):
        trees[path.relative_to(src).as_posix()] = ast.parse(path.read_text(), filename=str(path))
    by_dotted = {_dotted(rel): rel for rel in trees}
    functions: dict[tuple[str, str], ast.AST] = {}
    top: dict[str, set[str]] = {}
    for rel, tree in trees.items():
        for name, node in _functions(tree):
            functions[(rel, name)] = node
        top[rel] = {n.name for n in tree.body if isinstance(n, _FUNC)}
    imports = {
        rel: _imports(tree, _dotted(rel), rel.endswith("__init__.py"))
        for rel, tree in trees.items()
    }

    def resolve(rel: str, name: str, hops: int = 0) -> tuple[str, str] | None:
        """Where `name` in module `rel` is defined (follows re-exports)."""
        if name in top.get(rel, set()):
            return rel, name
        if hops > 5:
            return None
        found = imports[rel][1].get(name)
        if found is None or found[0] not in by_dotted:
            return None
        return resolve(by_dotted[found[0]], found[1], hops + 1)

    def of_node(rel: str, node: ast.AST) -> Key | None:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = imports[rel][0].get(node.value.id)
            return resolve(by_dotted[module], node.attr) if module in by_dotted else None
        if isinstance(node, ast.Name):
            return resolve(rel, node.id)
        return None

    refs: dict[Key, list[Ref]] = {}
    for rel, tree in trees.items():
        for where, node in _named(tree):
            if isinstance(node, ast.Name) and (
                not isinstance(node.ctx, ast.Load)
                or node.id in _locals(functions.get((rel, where)))
            ):
                continue  # a parameter or local variable of that name, not the function
            target = of_node(rel, node)
            if target is not None and target != (rel, where.split(".")[0]):  # not itself
                refs.setdefault(target, []).append(Ref(rel, where, getattr(node, "lineno", 0)))
    return Graph(functions, refs, of_node, trees)


def _locals(func: ast.AST | None) -> set[str]:
    """The parameters and assigned names of a function (they shadow a module's function)."""
    if not isinstance(func, _FUNC):
        return set()
    args = func.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
    names |= {
        n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
    }
    return names


def _named(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """(qualified name of the enclosing function or "<module>", Name/Attribute node)."""
    stack: list[tuple[str, ast.AST]] = [("<module>", tree)]
    while stack:
        where, node = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (*_FUNC, ast.ClassDef)):
                inner = child.name if where == "<module>" else f"{where}.{child.name}"
                stack.append((inner, child))
                continue
            if isinstance(child, (ast.Name, ast.Attribute)):
                yield where, child
            stack.append((where, child))
