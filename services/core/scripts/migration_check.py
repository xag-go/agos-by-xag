"""Expand/contract check for schema migrations (docs/operations.md, "Schema changes").

Every migration since FIRST is applied, one at a time, on top of the ones before it,
with the core's own migrator (db/connection.py). After each one, every table and
column that existed before it must still exist: a migration only adds (expand). A
table rebuild (SQLite's recipe: CREATE x_new, copy, DROP x, RENAME x_new TO x) passes
when it keeps every column. A rollback to the previous release then still finds
every table and column it reads.

Removing something (contract) is allowed only as its own step, named in the
migration's SQL, after the release that stopped using it shipped:

    -- agos: contract <table>            (a whole table goes)
    -- agos: contract <table>.<column>   (one column goes; a rename is a new column
                                           added earlier, then this)

Migration 141 (AGOS became single-user, db/logins_gone.py) shipped before this rule
and is recorded below as its contract.

    python scripts/migration_check.py      # check (CI, core job)

Owns: that rule. Must not: change a migration or a database file (it runs in memory).
"""

from __future__ import annotations

import re
import sqlite3
import sys

from agos_core.db import connection
from agos_core.db.migrations import MIGRATIONS

__all__ = ["FIRST", "check", "main", "removed"]

FIRST = 140
_CONTRACT = re.compile(r"^\s*-- agos: contract (\w+(?:\.\w+)?)\s*$", re.M)

# Shipped before the rule (2026-10): the login tables went with the logins.
SHIPPED_CONTRACTS: dict[int, frozenset[str]] = {
    141: frozenset(
        {
            "sessions",
            "login_failures",
            "member_workspaces",
            "members",
            "owner",
            "chats.member_id",
            "chats.former_member",
        }
    ),
}

Schema = dict[str, frozenset[str]]


def _schema(db: sqlite3.Connection) -> Schema:
    tables = [
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return {
        table: frozenset(
            str(row[1]) for row in db.execute("SELECT * FROM pragma_table_info(?)", (table,))
        )
        for table in tables
    }


def removed(before: Schema, after: Schema) -> set[str]:
    """What `after` lost: whole tables by name, columns of kept tables as table.column."""
    gone: set[str] = set()
    for table, columns in before.items():
        if table not in after:
            gone.add(table)
            continue
        gone.update(f"{table}.{column}" for column in columns - after[table])
    return gone


def _allowed(index: int, sql: str) -> set[str]:
    return set(_CONTRACT.findall(sql)) | set(SHIPPED_CONTRACTS.get(index, frozenset()))


def check(migrations: tuple[str, ...] = MIGRATIONS, first: int = FIRST) -> list[str]:
    """One line per removal that no contract step names; empty when all is additive."""
    saved = connection.MIGRATIONS
    problems: list[str] = []
    try:
        connection.MIGRATIONS = migrations[: first - 1]
        db = connection.open_database(":memory:")
        for index in range(first, len(migrations) + 1):
            before = _schema(db)
            connection.MIGRATIONS = migrations[:index]
            connection._migrate(db)
            sql = migrations[index - 1]
            for name in sorted(removed(before, _schema(db)) - _allowed(index, sql)):
                problems.append(
                    f"migration {index} removes {name} with no '-- agos: contract {name}' step"
                )
        db.close()
    finally:
        connection.MIGRATIONS = saved
    return problems


def main() -> int:
    problems = check()
    for line in problems:
        print(f"::error::{line}")
    if problems:
        print("Expand first, contract later: docs/operations.md, 'Schema changes'.")
        return 1
    print(f"migrations {FIRST}-{len(MIGRATIONS)}: additive (expand/contract rule holds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
