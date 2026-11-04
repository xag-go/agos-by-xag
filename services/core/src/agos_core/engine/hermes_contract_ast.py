"""Pure syntax-tree helpers of the Hermes contract checker (engine/hermes_contract.py):
the statements a module or class body binds, and whether AGOS's call still fits a
Hermes function's parameters. Moved out of hermes_contract.py (a frozen big file)."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field


def top_level(body: Iterable[ast.stmt]) -> Iterable[ast.stmt]:
    """Statements of a module / class body, inside its if / try blocks too."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from top_level(stmt.body)
            yield from top_level(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield from top_level(stmt.body)
            for handler in stmt.handlers:
                yield from top_level(handler.body)
            yield from top_level(stmt.orelse)
            yield from top_level(stmt.finalbody)


def binds(target: ast.expr | None, name: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(binds(e, name) for e in target.elts)
    return False


def decorated(fn: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (isinstance(target, ast.Name) and target.id == name) or (
            isinstance(target, ast.Attribute) and target.attr == name
        ):
            return True
    return False


@dataclass
class Params:
    positional: list[str] = field(default_factory=list)  # may be passed by position
    required_positional: list[str] = field(default_factory=list)
    keyword: set[str] = field(default_factory=set)  # may be passed by name
    required_keyword: set[str] = field(default_factory=set)  # keyword-only, no default
    varargs: bool = False
    varkw: bool = False

    def shown(self) -> str:
        return ", ".join(self.positional + sorted(self.keyword - set(self.positional)))


def params_of(fn: ast.FunctionDef | ast.AsyncFunctionDef, *, bound: bool) -> Params:
    args = fn.args
    positional = [*args.posonlyargs, *args.args]
    if bound and positional and not decorated(fn, "staticmethod"):
        positional = positional[1:]
    first_default = len(positional) - len(args.defaults)
    posonly = {a.arg for a in args.posonlyargs}
    out = Params(
        positional=[a.arg for a in positional],
        required_positional=[a.arg for a in positional[: max(first_default, 0)]],
        keyword={a.arg for a in positional if a.arg not in posonly}
        | {a.arg for a in args.kwonlyargs},
        required_keyword={
            a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d is None
        },
        varargs=args.vararg is not None,
        varkw=args.kwarg is not None,
    )
    return out


def call_problems(params: Params, pos: int, kw: tuple[str, ...]) -> list[str]:
    """Why AGOS's call (pos positional arguments, then keywords kw) no longer fits."""
    out = []
    if pos > len(params.positional) and not params.varargs:
        out.append(f"takes {len(params.positional)} positional argument(s), AGOS passes {pos}")
    for name in params.required_positional[pos:]:
        if name not in kw:
            out.append(f"new required parameter '{name}' AGOS doesn't pass")
    for name in sorted(params.required_keyword - set(kw)):
        out.append(f"new required parameter '{name}' AGOS doesn't pass")
    taken = params.keyword - set(params.positional[:pos])
    for name in kw:
        if name not in taken and not params.varkw:
            out.append(f"no parameter '{name}' any more (AGOS passes it)")
    return out
