"""SQLite's own checks of a database file: `PRAGMA integrity_check` (pages, indexes,
free list) and `PRAGMA foreign_key_check` (rows pointing at a row that is gone).

Opened read-only on its own connection, so a check of the live agos.db (WAL) never
blocks the core's writers. Used by the weekly check (actions/ops_watch.py) and by
the restore test on the restored copy (actions/backups.py rehearse), with the
row counts, values and liveness reads of the backup and diagnostics pages."""

from __future__ import annotations

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from agos_core.db import sql
from agos_core.db.connection import open_read_only

MAX_PROBLEMS = 20


@dataclass(frozen=True)
class DbCheck:
    ok: bool
    tables: int
    problems: list[str] = field(default_factory=list)


def check(path: Path) -> DbCheck:
    try:
        conn = open_read_only(path)
    except sqlite3.Error as error:
        return DbCheck(ok=False, tables=0, problems=[f"can't open: {type(error).__name__}"])
    try:
        problems: list[str] = []
        tables = int(
            conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        )
        rows = conn.execute("PRAGMA integrity_check(20)").fetchall()  # MAX_PROBLEMS
        problems += [str(r[0]) for r in rows if str(r[0]) != "ok"]
        for table, rowid, parent, _fk in conn.execute("PRAGMA foreign_key_check").fetchmany(
            MAX_PROBLEMS
        ):
            problems.append(f"foreign key: {table} row {rowid} points at a missing {parent} row")
        return DbCheck(ok=not problems, tables=tables, problems=problems[:MAX_PROBLEMS])
    except sqlite3.Error as error:
        return DbCheck(ok=False, tables=0, problems=[f"check failed: {type(error).__name__}"])
    finally:
        conn.close()


def row_counts(path: Path, tables: Collection[str]) -> dict[str, int]:
    """Rows in each of these tables of the database file (-1: a table it lacks)."""
    conn = open_read_only(path)
    try:
        out = {}
        for table in tables:
            try:
                out[table] = int(
                    conn.execute(
                        sql.text("SELECT COUNT(*) FROM {t}", t=sql.name(table, tables))
                    ).fetchone()[0]
                )
            except sqlite3.OperationalError:
                out[table] = -1
        return out
    finally:
        conn.close()


def answers(db: sqlite3.Connection) -> bool:
    """The database answers a query."""
    return bool(db.execute("SELECT 1").fetchone()[0] == 1)


def distinct_values(db: sqlite3.Connection, pairs: Collection[tuple[str, str]]) -> set[str]:
    """Every value held in these (table, column) pairs (a table an older database
    lacks gives none)."""
    tables = {t for t, _ in pairs}
    columns = {c for _, c in pairs}
    found: set[str] = set()
    for table, column in pairs:
        try:
            rows = db.execute(
                sql.text(
                    "SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL",
                    c=sql.name(column, columns),
                    t=sql.name(table, tables),
                )
            ).fetchall()
        except sqlite3.Error:
            continue
        found |= {str(r[0]) for r in rows}
    return found
