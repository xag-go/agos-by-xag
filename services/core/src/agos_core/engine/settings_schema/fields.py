"""A Hermes setting as a field: built from Hermes's schema, defaults and comments; keys Hermes's list doesn't hold.
Must not: run Hermes or cache anything.

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from typing import Any

from agos_core.engine.settings_schema.groups import group_of

__all__ = [
    "Field",
    "build",
    "comments",
    "leaves",
    "unlisted",
]


@dataclass(frozen=True)
class Field:
    """One Hermes setting, as Hermes describes it."""

    key: str
    type: str  # boolean / number / string / select / list / object
    description: str
    default: Any
    options: list[str] = field(default_factory=list)
    in_defaults: bool = True  # False: Hermes reads it, but DEFAULT_CONFIG doesn't list it
    # Hermes names a credential with this key (hermes_cli/config.py
    # _is_secret_config_key, read with the schema): its value is never shown.
    secret: bool = False

    @property
    def group(self) -> str:
        return group_of(self.key)


def leaves(config: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Every setting of a defaults mapping: its leaves, and its EMPTY mappings
    (a section whose entries are the owner's: `providers`, `personalities`...)."""
    out: dict[str, Any] = {}
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if path == "_config_version":
            continue
        if isinstance(value, dict) and value:
            out.update(leaves(value, path))
        else:
            out[path] = value
    return out


def _title(key: str) -> str:
    """The name the dashboard shows when it has no description (its own rule)."""
    return key.replace(".", " → ").replace("_", " ").title()


def comments(source: str, name: str = "DEFAULT_CONFIG") -> dict[str, str]:
    """The comment Hermes wrote right above each key of `name` in its source (and
    one at the end of the key's own line), joined into one text, per dotted key."""
    lines: dict[int, str] = {}
    code_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                lines[tok.start[0]] = tok.string.lstrip("#").strip()
            elif tok.type not in (
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.ENDMARKER,
            ):
                for line in range(tok.start[0], tok.end[0] + 1):
                    code_lines.add(line)
        tree = ast.parse(source)
    except (SyntaxError, tokenize.TokenError):
        return {}
    root = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
        ),
        None,
    )
    out: dict[str, str] = {}

    def above(line: int) -> str:
        found: list[str] = []
        at = line - 1
        while at in lines and at not in code_lines:
            found.append(lines[at])
            at -= 1
        text = " ".join(reversed(found))
        if line in lines:
            text = f"{text} {lines[line]}".strip()
        return text

    def walk(node: ast.expr, prefix: str) -> None:
        if not isinstance(node, ast.Dict):
            return
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            path = f"{prefix}.{key.value}" if prefix else key.value
            text = above(key.lineno)
            if text:
                out[path] = text
            walk(value, path)

    if root is not None:
        walk(root, "")
    return out


def build(
    schema: dict[str, Any],
    defaults: dict[str, Any],
    source: str,
    secret: set[str] | frozenset[str] = frozenset(),
) -> list[Field]:
    """Hermes's settings, in Hermes's order: its schema's fields, then the empty
    sections of its defaults that the schema's walk skips. `secret`: the keys
    Hermes names credentials (its own _is_secret_config_key)."""
    notes = comments(source)
    flat = leaves(defaults)
    out: list[Field] = []
    seen: set[str] = set()

    def note(key: str, given: str) -> str:
        # The schema's own words win (an override, e.g. terminal.backend); where it
        # has only the key's name, Hermes's comment in config_defaults.py.
        if given and given != _title(key):
            return given
        parent = key.rsplit(".", 1)[0] if "." in key else ""
        return notes.get(key) or (notes.get(parent, "") if parent else "") or given or _title(key)

    for key, entry in schema.items():
        if not isinstance(entry, dict):
            continue
        options = entry.get("options")
        out.append(
            Field(
                key=key,
                type=str(entry.get("type") or "string"),
                description=note(key, str(entry.get("description") or "")),
                default=flat.get(key),
                options=[str(o) for o in options] if isinstance(options, list) else [],
                secret=key in secret,
            )
        )
        seen.add(key)
    for key, value in flat.items():
        if key in seen or any(key.startswith(f"{s}.") for s in seen):
            continue
        out.append(
            Field(
                key=key,
                type="object" if isinstance(value, dict) else _type(value),
                description=note(key, ""),
                default=value,
                secret=key in secret,
            )
        )
    return out


def _type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def unlisted(key: str, value: Any, *, secret: bool = False) -> Field:
    """A setting Hermes reads that its defaults don't list (AGOS writes it, or the
    workspace's Hermes has it set). `secret`: Hermes's masker hides its value."""
    return Field(
        key=key,
        type=_type(value),
        description=(
            "Not in the engine's list of defaults: its code reads it directly, or it was "
            "set here by hand."
        ),
        default=None,
        in_defaults=False,
        secret=secret,
    )
