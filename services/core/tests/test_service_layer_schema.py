"""Migration 146 (db/schema_service_layer.py): the Service Layer's tables, the
operation runs (audit + idempotency), the saga journal and the outbox."""

from __future__ import annotations

import sqlite3

from agos_core.db.connection import open_database
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.schema_errors import ERROR_ISSUES
from agos_core.db.schema_service_layer import SERVICE_LAYER


def _tables(db: sqlite3.Connection) -> set[str]:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(r[0]) for r in rows}


def test_migration_146_is_the_service_layer_and_145_kept_its_text() -> None:
    assert len(MIGRATIONS) >= 146
    assert MIGRATIONS[145] is SERVICE_LAYER
    assert MIGRATIONS[144] is ERROR_ISSUES  # moved out of migrations.py, same text


def test_a_new_database_has_the_service_layer_tables() -> None:
    db = open_database(":memory:")
    assert {"op_runs", "sagas", "saga_steps", "outbox"} <= _tables(db)
    assert db.execute("PRAGMA user_version").fetchone()[0] >= 146


def test_the_migration_survives_a_second_run() -> None:
    db = open_database(":memory:")
    db.execute(
        "INSERT INTO outbox (channel, payload, next_at, created_at) VALUES ('push', '{}', 'x', 'x')"
    )
    db.executescript(SERVICE_LAYER)
    assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


def test_one_idempotency_key_per_operation_and_one_outbox_row_per_dedupe_key() -> None:
    db = open_database(":memory:")
    insert = (
        "INSERT OR IGNORE INTO op_runs (operation, actor, idempotency_key, created_at)"
        " VALUES (?, 'owner', ?, 'x')"
    )
    db.execute(insert, ("create_workspace", "k1"))
    db.execute(insert, ("create_workspace", "k1"))
    db.execute(insert, ("delete_workspace", "k1"))
    db.execute(insert, ("create_workspace", None))
    db.execute(insert, ("create_workspace", None))
    assert db.execute("SELECT COUNT(*) FROM op_runs").fetchone()[0] == 4
    push = (
        "INSERT OR IGNORE INTO outbox (channel, payload, dedupe_key, next_at, created_at)"
        " VALUES ('push', '{}', ?, 'x', 'x')"
    )
    db.execute(push, ("error:1",))
    db.execute(push, ("error:1",))
    assert db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
