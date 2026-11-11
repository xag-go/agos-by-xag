"""Keys a Hermes platform adapter reads but its defaults don't list, found in Hermes's own source.
Must not: cache anything.

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.engine import read_cache
from agos_core.engine.settings_schema.fields import Field, _type

__all__ = [
    "EXTRA_PLATFORM",
    "EXTRA_PREFIX",
    "ExtraKey",
    "extra_fields",
    "hermes_root",
    "platform_extras",
]

# --- keys Hermes's Telegram adapter reads that DEFAULT_CONFIG doesn't list --------

# Hermes has no list of a platform's `extra` keys (gateway/platform_registry.py
# PlatformEntry carries none, and DEFAULT_CONFIG lists only some under `telegram`):
# its adapter reads each with `extra.get("<key>", default)` or
# `extra_or_secret(extra, "<key>", "<ENV>", default)` (gateway/platforms/_shared.py
# :103, env first), directly or through small helpers taking the key as a
# parameter. AGOS finds those reads in Hermes's own source (ast), so a key a Hermes
# upgrade adds shows by itself; no AGOS list.
EXTRA_PLATFORM = "telegram"
EXTRA_PREFIX = f"platforms.{EXTRA_PLATFORM}.extra."


@dataclass(frozen=True)
class ExtraKey:
    key: str  # the extra's own name ("group_topics")
    env: str  # the env name that wins over it ("" when none)
    default: Any
    where: str  # "plugins/platforms/telegram/adapter.py:7018"
    doc: str  # the docstring of the Hermes function reading it


# Per adapter folder: the keys its source reads, kept while its files are unchanged.
_EXTRAS: read_cache.ReadCache[list[ExtraKey]] = read_cache.ReadCache(
    "platform_extras", max_entries=8
)


def _is_extra(node: ast.expr) -> bool:
    """`extra`, `self.config.extra`, `_telegram_extra`, `(x.extra or {})`."""
    if isinstance(node, ast.BoolOp):
        return any(_is_extra(v) for v in node.values)
    if isinstance(node, ast.Name):
        return node.id.endswith("extra")
    if isinstance(node, ast.Attribute):
        return node.attr == "extra"
    return False


def _const(node: ast.expr | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def platform_extras(hermes_root: Path, platform: str = EXTRA_PLATFORM) -> list[ExtraKey]:
    """The `extra.*` keys a platform adapter reads (its source walked once, kept while
    its files are unchanged: only a Hermes update rewrites them, and the walk of
    Telegram's ~0.5 MB took ~0.1 s on every page)."""
    folder = hermes_root / "plugins" / "platforms" / platform
    files = sorted(folder.glob("*.py"))
    stamp = (tuple(str(p) for p in files), read_cache.file_stamp(*files))
    found = _EXTRAS.get(str(folder), stamp, lambda: _platform_extras(hermes_root, files))
    return list(found)


def _platform_extras(hermes_root: Path, files: list[Path]) -> list[ExtraKey]:
    found: dict[str, ExtraKey] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = str(path.relative_to(hermes_root))
        # Helpers: functions passing one of their parameters as the key.
        helpers: dict[str, tuple[int, int | None, int | None]] = {}
        funcs = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for fn in funcs:
            params = [a.arg for a in fn.args.args if a.arg != "self"]
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                key_arg, env_arg, default_arg = _read_args(node)
                if isinstance(key_arg, ast.Name) and key_arg.id in params:
                    env_at = (
                        params.index(env_arg.id)
                        if isinstance(env_arg, ast.Name) and env_arg.id in params
                        else None
                    )
                    default_at = (
                        params.index(default_arg.id)
                        if isinstance(default_arg, ast.Name) and default_arg.id in params
                        else params.index("default")
                        if "default" in params
                        else None
                    )
                    helpers.setdefault(fn.name, (params.index(key_arg.id), env_at, default_at))

        def owner(
            line: int, funcs: list[Any] = funcs
        ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
            inside = [f for f in funcs if f.lineno <= line <= (f.end_lineno or f.lineno)]
            return (
                min(inside, key=lambda f: (f.end_lineno or f.lineno) - f.lineno) if inside else None
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            key_arg, env_arg, default_arg = _read_args(node)
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else (node.func.id if isinstance(node.func, ast.Name) else "")
            )
            if name in helpers and not isinstance(key_arg, ast.Constant):
                k_at, e_at, d_at = helpers[name]
                args = list(node.args)
                key_arg = args[k_at] if k_at < len(args) else None
                env_arg = args[e_at] if e_at is not None and e_at < len(args) else None
                default_arg = args[d_at] if d_at is not None and d_at < len(args) else None
            key = _const(key_arg)
            if not isinstance(key, str) or not key.isidentifier():
                continue
            env = _const(env_arg)
            reader = owner(node.lineno)
            doc = (ast.get_docstring(reader) or "").split("\n\n")[0].strip() if reader else ""
            if key in found:
                continue
            found[key] = ExtraKey(
                key=key,
                env=env if isinstance(env, str) else "",
                default=_const(default_arg),
                where=f"{rel}:{node.lineno}",
                doc=" ".join(doc.split()),
            )
    return [found[k] for k in sorted(found)]


def _read_args(node: ast.Call) -> tuple[ast.expr | None, ast.expr | None, ast.expr | None]:
    """(key, env, default) of an extra read, or Nones."""
    func = node.func
    args = list(node.args)
    if isinstance(func, ast.Attribute) and func.attr == "get" and _is_extra(func.value):
        return (args[0] if args else None, None, args[1] if len(args) > 1 else None)
    name = (
        func.id
        if isinstance(func, ast.Name)
        else (func.attr if isinstance(func, ast.Attribute) else "")
    )
    if name.lstrip("_") == "extra_or_secret" and len(args) >= 3:
        return (args[1], args[2], args[3] if len(args) > 3 else None)
    return (None, None, None)


def extra_fields(hermes_root: Path, listed: set[str]) -> list[Field]:
    """Rows for the extras Hermes's adapter reads that its lists don't hold."""
    out: list[Field] = []
    for extra in platform_extras(hermes_root):
        key = EXTRA_PREFIX + extra.key
        if {key, f"{EXTRA_PLATFORM}.{extra.key}", f"{EXTRA_PLATFORM}.extra.{extra.key}"} & listed:
            continue  # Hermes's own list has it (DEFAULT_CONFIG's `telegram` section)
        default = extra.default
        if isinstance(default, str) and default.lower() in ("true", "false"):
            default = default.lower() == "true"
        env = f" The .env line {extra.env} wins over it." if extra.env else ""
        what = f"{extra.doc} " if extra.doc else ""
        out.append(
            Field(
                key=key,
                type=_type(default) if default is not None else "string",
                description=f"{what}Read by the engine's Telegram adapter ({extra.where}); "
                f"not in the engine's list of defaults.{env}",
                default=default,
                in_defaults=False,
            )
        )
    return out


def hermes_root(source: Path) -> Path:
    """Hermes's source tree, from where its defaults file is."""
    return source.resolve().parent.parent
