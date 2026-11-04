"""Retention (agos_core/background/retention.py, docs/operations.md): one daily job
deletes AGOS's old machine records and never the owner's content. Owner default
(he may change it): System Log lines > 90 days, operation runs > 180 days, delivered
outbox rows > 30 days, finished jobs > 30 days, journals of completed sagas > 90
days, SLO samples > 400 days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.background import retention, schedule
from agos_core.db.activity import add_activity
from agos_core.db.connection import open_database
from agos_core.db.workspaces import insert_workspace
from agos_core.jobs import queue, recurring, runner

NOW = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)


def _at(days: int) -> str:
    return queue.stamp(NOW - timedelta(days=days))


@pytest.fixture
def core() -> Any:
    db = open_database(":memory:")
    insert_workspace(db, workspace_id="w", name="W", description="")
    return SimpleNamespace(db=db)


def _ids(core: Any, table: str) -> list[int]:
    return [int(r[0]) for r in core.db.execute("SELECT id FROM " + table + " ORDER BY id")]


def _log(core: Any, days: int) -> int:
    cursor = core.db.execute(
        "INSERT INTO system_log (workspace_id, level, source, text, created_at)"
        " VALUES (NULL, 'error', 'agos', 'x', ?)",
        (_at(days),),
    )
    return int(cursor.lastrowid)


def _run(core: Any, days: int, status: str) -> int:
    cursor = core.db.execute(
        "INSERT INTO op_runs (operation, actor, status, created_at, finished_at)"
        " VALUES ('op', 'owner', ?, ?, ?)",
        (status, _at(days), None if status == "running" else _at(days)),
    )
    return int(cursor.lastrowid)


def _push(core: Any, days: int, status: str) -> int:
    cursor = core.db.execute(
        "INSERT INTO outbox (channel, payload, status, next_at, created_at, sent_at)"
        " VALUES ('push', '{}', ?, ?, ?, ?)",
        (status, _at(days), _at(days), _at(days) if status == "sent" else None),
    )
    return int(cursor.lastrowid)


def _job(core: Any, days: int, status: str) -> int:
    cursor = core.db.execute(
        "INSERT INTO jobs (kind, status, run_at, created_at, finished_at) VALUES ('k', ?, ?, ?, ?)",
        (status, _at(days), _at(days), _at(days) if status in ("done", "dead") else None),
    )
    return int(cursor.lastrowid)


def _saga(core: Any, days: int, status: str) -> int:
    cursor = core.db.execute(
        "INSERT INTO sagas (name, workspace_id, status, started_at, finished_at)"
        " VALUES ('workspace.create', 'w', ?, ?, ?)",
        (status, _at(days), _at(days)),
    )
    saga = int(cursor.lastrowid)
    core.db.execute(
        "INSERT INTO saga_steps (saga_id, seq, name, status, at) VALUES (?, 1, 's', 'done', ?)",
        (saga, _at(days)),
    )
    return saga


def test_old_machine_records_go_and_recent_or_open_ones_stay(core: Any) -> None:
    old_log, new_log = _log(core, 91), _log(core, 89)
    old_run, new_run, running = (
        _run(core, 181, "done"),
        _run(core, 179, "failed"),
        _run(core, 400, "running"),
    )
    old_sent, new_sent = _push(core, 31, "sent"), _push(core, 29, "sent")
    waiting, failed = _push(core, 60, "pending"), _push(core, 60, "failed")
    old_done, old_dead, new_done = (
        _job(core, 31, "done"),
        _job(core, 31, "dead"),
        _job(core, 29, "done"),
    )
    pending_job = _job(core, 60, "pending")
    old_saga, open_saga, new_saga = (
        _saga(core, 91, "done"),
        _saga(core, 200, "needs_attention"),
        _saga(core, 10, "done"),
    )
    gone = retention.run(core, now=NOW)
    assert gone == {
        "system_log": 1,
        "op_runs": 1,
        "outbox": 1,
        "jobs": 2,
        "sagas": 1,
        "slo_samples": 0,
    }
    assert _ids(core, "system_log") == [new_log] and old_log not in _ids(core, "system_log")
    assert _ids(core, "op_runs") == [new_run, running] and old_run not in _ids(core, "op_runs")
    assert _ids(core, "outbox") == [new_sent, waiting, failed] and old_sent not in _ids(
        core, "outbox"
    )
    assert _ids(core, "jobs") == [new_done, pending_job]
    assert {old_done, old_dead}.isdisjoint(_ids(core, "jobs"))
    assert _ids(core, "sagas") == [open_saga, new_saga] and old_saga not in _ids(core, "sagas")
    # The completed saga's steps went with it.
    steps = core.db.execute("SELECT saga_id FROM saga_steps ORDER BY saga_id").fetchall()
    assert [int(r[0]) for r in steps] == [open_saga, new_saga]


def test_his_content_is_never_touched(core: Any) -> None:
    add_activity(core.db, "w", kind="workspace.created", text="Workspace created")
    core.db.execute("UPDATE activity SET created_at = ?", (_at(3000),))
    retention.run(core, now=NOW)
    assert len(_ids(core, "activity")) == 1
    assert retention.TABLES == (
        "system_log",
        "op_runs",
        "outbox",
        "jobs",
        "sagas",
        "slo_samples",
    )


def test_retention_is_one_daily_job(core: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recurring, "EVERY", {})
    monkeypatch.setattr(runner, "HANDLERS", {})
    schedule.register()
    assert recurring.EVERY[retention.KIND].interval == timedelta(days=1)
    _log(core, 91)
    runner.HANDLERS[retention.KIND](core, {})
    assert core.db.execute("SELECT count(*) FROM system_log").fetchone()[0] == 0
