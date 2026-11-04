"""Migration 147 (db/schema_reliability.py): the job queue and the SLO samples.
Additive (new tables only) and replayable."""

from __future__ import annotations

import hashlib

from agos_core.db.connection import open_database
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.schema_kanban_kit import KANBAN_ASKS_KIT
from agos_core.db.schema_reliability import RELIABILITY


def test_migration_147_is_reliability_and_144_kept_its_text() -> None:
    assert MIGRATIONS[146] is RELIABILITY
    assert MIGRATIONS[143] is KANBAN_ASKS_KIT  # moved out of migrations.py, same text
    assert hashlib.sha256(KANBAN_ASKS_KIT.encode()).hexdigest()[:16] == "f4bd62a1ecbd9bea"


def test_a_new_database_has_the_job_and_slo_tables() -> None:
    db = open_database(":memory:")
    tables = {str(r[0]) for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "slo_samples"} <= tables
    assert db.execute("PRAGMA user_version").fetchone()[0] >= 147


def test_the_migration_survives_a_second_run() -> None:
    db = open_database(":memory:")
    db.execute("INSERT INTO jobs (kind, run_at, created_at) VALUES ('k', 'x', 'x')")
    db.executescript(RELIABILITY)
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_one_waiting_job_per_key_and_one_sample_per_once_key() -> None:
    db = open_database(":memory:")
    job = (
        "INSERT OR IGNORE INTO jobs (kind, dedupe_key, status, run_at, created_at)"
        " VALUES ('k', 'every', ?, 'x', 'x')"
    )
    db.execute(job, ("done",))
    db.execute(job, ("done",))  # finished jobs never hold the key
    db.execute(job, ("pending",))
    db.execute(job, ("pending",))
    assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3
    sample = "INSERT OR IGNORE INTO slo_samples (sli, once_key, at) VALUES ('first_output', ?, 'x')"
    db.execute(sample, ("turn:1",))
    db.execute(sample, ("turn:1",))
    db.execute(sample, (None,))
    db.execute(sample, (None,))
    assert db.execute("SELECT COUNT(*) FROM slo_samples").fetchone()[0] == 3
