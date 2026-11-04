"""Rows of a Hermes SQLite store, read-only, kept while the store is unchanged.

Owns: one read-only query on a Hermes database (its cron executions.db, ...), cached
by the file's and its WAL's stamp: Hermes's stores have no index for these scans, and
pages like the workspace Log read them on every view.

Must not: write a Hermes store, or keep rows once the file changed.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from agos_core.engine.read_cache import ReadCache, sqlite_stamp
from agos_core.hermes_gateway import hermes_db

__all__ = ["read"]

# The rows each query gave, kept while that database and its WAL are unchanged.
_ROWS: ReadCache[list[Any]] = ReadCache("log-hermes-rows")


def read(path: Path, sql: str, args: tuple[Any, ...] = ()) -> list[Any]:
    """Rows of one of the workspace's Hermes databases, read-only; none if absent."""
    if not path.is_file():
        return []
    return _ROWS.get((str(path), sql, args), sqlite_stamp(path), lambda: _rows(path, sql, args))


def _rows(path: Path, sql: str, args: tuple[Any, ...]) -> list[Any]:
    try:
        with contextlib.closing(hermes_db.connect_ro(path, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            return list(db.execute(sql, args))
    except sqlite3.Error:
        return []
