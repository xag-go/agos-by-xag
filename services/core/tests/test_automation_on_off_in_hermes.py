"""An automation's on/off is its Hermes cron job's `enabled` alone (H: cron/jobs.py
pause_job/resume_job). AGOS's `automations.enabled` holds his on/off only while
Hermes refused it (sync_error), and goes back to 0 once Hermes has it."""

import sqlite3
from typing import Any

from test_automations import MODEL, _row, env, new  # noqa: F401 — fixtures

from agos_core.actions import automations as actions
from agos_core.db.connection import _migrate
from agos_core.db.migrations import MIGRATIONS


def test_on_off_lives_in_hermes_only(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    aid = new(client, ws)
    job = cron.jobs["job1"]
    assert job["enabled"] is True and _row(core, aid)["enabled"] == 0  # no copy
    for on in (False, True, False):
        client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": on})
        assert job["enabled"] is on and _row(core, aid)["enabled"] == 0
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    body = {k: got[k] for k in ("name", "instructions", "schedule")} | {"model": MODEL, "on": True}
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code < 300
    assert job["enabled"] is True and _row(core, aid)["enabled"] == 0
    # Turned off in Hermes itself (its CLI): AGOS shows Hermes's.
    job.update(enabled=False, paused_reason="Turned off in AGOS")
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["on"] is False


def test_a_refused_on_off_waits_in_agos_until_hermes_takes_it(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    aid = new(client, ws)
    cron.down = True  # Hermes's cron refuses
    body: dict[str, Any] = {"name": "Daily brief", "instructions": "Summarize new files."}
    body |= {"schedule": "0 9 * * *", "model": MODEL, "on": False}
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code < 300
    row = _row(core, aid)
    assert row["sync_error"] and row["enabled"] == 0  # his "off", kept as asked
    body["on"] = True
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code < 300
    assert _row(core, aid)["enabled"] == 1
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["on"] is True and got["problem"].startswith("Not scheduled")
    cron.down = False
    actions.keep_in_step(core)  # tried again: Hermes takes it, AGOS's copy goes
    assert cron.jobs["job1"]["enabled"] is True
    assert _row(core, aid)["enabled"] == 0 and _row(core, aid)["sync_error"] is None


def test_an_automation_started_only_by_an_event_keeps_no_on_off(env: Any) -> None:  # noqa: F811
    """C6: with no time, its on/off is its Hermes webhook route's: AGOS's old one
    (left from a refused change) goes back to 0 once it has no schedule."""
    client, core, _cron, ws = env
    aid = new(client, ws)
    core.db.execute(
        "UPDATE automations SET enabled = 1, schedule = '0 9 * * *', sync_error = NULL"
        " WHERE id = ?",
        (aid,),
    )
    actions.sync_job(core, ws, aid, want=("", True))
    row = _row(core, aid)
    assert row["schedule"] == "" and row["hermes_job_id"] is None
    assert row["enabled"] == 0


def test_the_upgrade_drops_the_copies_hermes_holds() -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    step = next(i for i, m in enumerate(MIGRATIONS) if "automations.enabled only while" in m)
    for sql in MIGRATIONS[:step]:
        db.executescript(sql)
    db.execute(f"PRAGMA user_version = {step}")
    at = "2026-01-01T00:00:00Z"
    db.execute(
        "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES ('w', 'W', ?, ?)",
        (at, at),
    )
    for name, job, error in (
        ("held", "j1", None),
        ("refused", "j2", "Not scheduled: x"),
        ("new", None, None),
    ):
        db.execute(
            "INSERT INTO automations (workspace_id, name, file, schedule, enabled, created_at,"
            " updated_at, hermes_job_id, sync_error) VALUES ('w', ?, ?, '', 1, ?, ?, ?, ?)",
            (name, f"{name}.md", at, at, job, error),
        )
    _migrate(db)
    got = {r["name"]: r["enabled"] for r in db.execute("SELECT name, enabled FROM automations")}
    # "new" has no time: its on/off is its webhook route's (C6, migration 122).
    assert got == {"held": 0, "refused": 1, "new": 0}
