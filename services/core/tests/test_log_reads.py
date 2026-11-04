"""The workspace Log reads Hermes's run stores (each profile's cron executions.db)
again only when the store changed: its query scans and sorts every run (no index
of Hermes's serves it) on every page of the log."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from test_library import env, ws  # noqa: F401 - fixture


def _runs(path: Any, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS executions (id INTEGER PRIMARY KEY, job_id TEXT,"
            " status TEXT, started_at TEXT, finished_at TEXT, error TEXT)"
        )
        db.execute(
            "INSERT INTO executions (job_id, status, started_at, finished_at, error)"
            " VALUES ('j', 'failed', ?, ?, 'boom')",
            (f"2026-10-0{n}T10:00:00+00:00", f"2026-10-0{n}T10:00:01+00:00"),
        )


def test_the_log_reads_hermess_runs_again_only_when_they_changed(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    from agos_core.hermes_gateway import store_rows

    a = ws(client, "Alpha")
    store = core.engine.profile_home(a) / "cron" / "executions.db"
    _runs(store, 1)
    opened: list[str] = []
    rows = store_rows._rows

    def counted(path: Any, sql: str, args: tuple[Any, ...]) -> list[Any]:
        opened.append(str(path))
        return rows(path, sql, args)

    monkeypatch.setattr(store_rows, "_rows", counted)
    url = f"/workspaces/{a}/log"
    first = client.get(url).json()["entries"]
    assert sum(e["id"].startswith("cron:") for e in first) == 1
    asked = opened.count(str(store))
    assert asked == 1
    client.get(url)
    assert opened.count(str(store)) == asked
    _runs(store, 2)  # Hermes ran the job again
    again = client.get(url).json()["entries"]
    assert sum(e["id"].startswith("cron:") for e in again) == 2
    assert opened.count(str(store)) == asked + 1
