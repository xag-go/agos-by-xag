"""SQL text whose shape depends on the call, built only from checked pieces.

Owns: the `?` marks of an `IN (...)` list, table/column names picked from a constant
set (or read from a database file: then always quoted), `col = ?` assignment lists, and filling those pieces into a query template.
Must not: put a value into SQL text. Values always travel as `?` parameters; a piece
is either marks or a name that passed `name()` against the caller's constant set.

    db.execute(sql.text("SELECT * FROM t WHERE id IN ({ids})", ids=sql.marks(len(ids))), ids)
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable

__all__ = ["Piece", "assignments", "marks", "name", "or_null", "quoted", "text"]

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Piece(str):
    """SQL text made by this module (marks or checked names); `text()` takes only these."""

    __slots__ = ()


def marks(count: int) -> Piece:
    """`?, ?, ?` for an IN list of `count` values (empty for none: SQLite reads `IN ()`)."""
    if count < 0:
        raise ValueError("a negative number of SQL marks")
    return Piece(", ".join("?" * count))


def name(value: str, allowed: Collection[str]) -> Piece:
    """A table or column name, only when it is one of the caller's constant names."""
    if value not in allowed or not _NAME.match(value):
        raise ValueError(f"not a known SQL name: {value!r}")
    return Piece(value)


def quoted(value: str) -> Piece:
    """A table or column name read from a database file (not from the caller's
    constants): always a double-quoted SQL identifier, any `"` inside doubled, so the
    name is never read as SQL."""
    return Piece('"' + value.replace('"', '""') + '"')


def assignments(columns: Iterable[str], allowed: Collection[str]) -> Piece:
    """`a = ?, b = ?` for an UPDATE, each column checked against `allowed`."""
    return Piece(", ".join(f"{name(c, allowed)} = ?" for c in columns))


def or_null(columns: Iterable[str], have: Collection[str], allowed: Collection[str]) -> Piece:
    """A select list of `columns`: each one the table has, else `NULL AS <column>`."""
    return Piece(
        ", ".join(name(c, allowed) if c in have else f"NULL AS {name(c, allowed)}" for c in columns)
    )


def text(template: str, **pieces: Piece) -> str:
    """`template` with its `{slot}`s filled; every filling must be a `Piece`."""
    for slot, piece in pieces.items():
        if not isinstance(piece, Piece):
            raise TypeError(f"SQL slot {slot!r} needs sql.marks()/sql.name(), not a plain str")
    return template.format_map(pieces)
