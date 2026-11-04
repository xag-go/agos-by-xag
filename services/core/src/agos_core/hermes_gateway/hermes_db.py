"""The one way AGOS opens Hermes's own databases (ADR 0024): kanban.db, state.db and
the like, always read-only (SQLite URI `mode=ro`: never a write, never a new file).
The SQL stays with its caller for now (one reader per database is plan G3); errors
are sqlite3.Error as before."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_ro(
    path: Path | str, *, timeout: float = 5.0, check_same_thread: bool = True
) -> sqlite3.Connection:
    """A read-only connection to a Hermes database (the caller closes it)."""
    return sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, timeout=timeout, check_same_thread=check_same_thread
    )
