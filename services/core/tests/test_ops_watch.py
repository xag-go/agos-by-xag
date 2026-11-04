"""The ops watch (actions/ops_watch.py, db/health.py): backup warnings, the monthly
restore test, the weekly database check, disk/RAM alerts and old restore folders."""

import logging
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_api
from fastapi.testclient import TestClient

from agos_core.actions import backups, error_issues, ops_watch
from agos_core.actions.errors import ActionError
from agos_core.db import health
from agos_core.db.connection import open_database
from agos_core.engine import backup as bk

client = test_api.client  # the API tests' fixture
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def core_of(c: TestClient) -> Any:
    return c.app.state.core  # type: ignore[attr-defined]


def open_issues(core: Any) -> list[str]:
    return [i.message for i in error_issues.listed(core.db, status="open")]


# ---- SQLite -----------------------------------------------------------------------


def test_every_connection_has_foreign_keys_on(tmp_path: Path) -> None:
    db = open_database(tmp_path / "agos.db")
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_healthy_database_passes_the_check(tmp_path: Path) -> None:
    db = open_database(tmp_path / "agos.db")
    db.close()
    found = health.check(tmp_path / "agos.db")
    assert found.ok and found.problems == [] and found.tables > 10


def test_a_broken_foreign_key_is_found(tmp_path: Path) -> None:
    path = tmp_path / "x.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        "CREATE TABLE a (id INTEGER PRIMARY KEY);"
        "CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));"
        "INSERT INTO b VALUES (1, 99);"
    )
    raw.commit()
    raw.close()
    found = health.check(path)
    assert not found.ok
    assert any("foreign key" in p for p in found.problems)


def test_a_corrupt_file_is_not_ok(tmp_path: Path) -> None:
    path = tmp_path / "bad.db"
    path.write_bytes(b"SQLite format 3\x00" + os.urandom(4096))
    assert not health.check(path).ok


def test_the_weekly_check_logs_an_error_when_the_database_is_bad(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    monkeypatch.setattr(
        health, "check", lambda _p: health.DbCheck(ok=False, tables=3, problems=["boom"])
    )
    ops_watch.check_database(core, NOW)
    assert any("database check failed" in m for m in open_issues(core))
    # Done this week: not again until 7 days later.
    assert not ops_watch.database_due(core, NOW + timedelta(days=6))
    assert ops_watch.database_due(core, NOW + timedelta(days=7))


# ---- backups ----------------------------------------------------------------------


def test_no_password_is_a_warning_and_an_error_once_a_day(client: TestClient) -> None:
    core = core_of(client)
    warnings = ops_watch.backup_warnings(core, NOW)
    assert any("No backup password" in w for w in warnings)
    ops_watch.check_backups(core, NOW)
    ops_watch.check_backups(core, NOW + timedelta(hours=1))
    issues = [i for i in error_issues.listed(core.db, status="open") if "password" in i.message]
    assert len(issues) == 1 and issues[0].count == 1
    ops_watch.check_backups(core, NOW + timedelta(hours=25))
    issues = [i for i in error_issues.listed(core.db, status="open") if "password" in i.message]
    assert issues[0].count == 2


def test_a_backup_older_than_48_hours_is_a_warning(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    backups.set_password(core, "a long password")
    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(folder))
    assert any("no backup yet" in w.lower() for w in ops_watch.backup_warnings(core, NOW))
    old = folder / "agos-backup-20261030-100000.agosb"
    old.write_bytes(b"x")
    stamp = (NOW - timedelta(hours=50)).timestamp()
    os.utime(old, (stamp, stamp))
    assert any("50 hours" in w for w in ops_watch.backup_warnings(core, NOW))
    stamp = (NOW - timedelta(hours=3)).timestamp()
    os.utime(old, (stamp, stamp))
    assert ops_watch.backup_warnings(core, NOW) == []
    backups.set_schedule(core, "off", 7)
    os.utime(old, (0, 0))
    assert ops_watch.backup_warnings(core, NOW) == []  # the owner turned them off


def test_the_backups_page_carries_the_warnings(client: TestClient) -> None:
    body = client.get("/backups").json()
    assert any("No backup password" in w for w in body["warnings"])


def test_the_monthly_restore_test_runs_when_due_and_failure_is_an_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    backups.set_password(core, "a long password")
    ran: list[str] = []

    def rehearse(_core: Any, name: str | None = None) -> backups.Rehearsal:
        ran.append("x")
        return backups.Rehearsal(ok=False, files=3, tables={}, missing=["a"], detail="bad")

    monkeypatch.setattr(backups, "rehearse", rehearse)
    monkeypatch.setattr(
        backups, "_files", lambda _f: [backups.BackupFile(name="b", size=1, created_at="")]
    )
    ops_watch.check_restore(core, NOW)
    assert ran == ["x"]
    assert any("restore test failed" in m for m in open_issues(core))
    ops_watch.check_restore(core, NOW + timedelta(days=29))
    assert ran == ["x"]
    ops_watch.check_restore(core, NOW + timedelta(days=30))
    assert ran == ["x", "x"]


def test_the_restore_test_also_checks_the_restored_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    core = core_of(client)
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    backups.set_password(core, "a long password")
    backups.run_backup(core)
    monkeypatch.setattr(
        health, "check", lambda _p: health.DbCheck(ok=False, tables=1, problems=["page 4 bad"])
    )
    result = backups.rehearse(core)
    assert not result.ok and "page 4 bad" in result.detail


# ---- old restore folders ----------------------------------------------------------


def test_old_restore_side_folders_go_the_newest_stays(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    data = core.layout.root
    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(folder))
    old = time.time() - 20 * 86400
    names = ["20261001T000000Z", "20261005T000000Z", "20261009T000000Z"]
    for name in names:
        side = data.parent / f"{data.name}.before-restore-{name}"
        (side / "system").mkdir(parents=True)
        os.utime(side, (old, old))
    fresh = data.parent / f"{data.name}.before-restore-20261101T000000Z"
    fresh.mkdir()
    stale_tmp = folder / "restore-20261001T000000Z"
    stale_tmp.mkdir()
    os.utime(stale_tmp, (old, old))
    new_tmp = folder / "restore-20261102T110000Z"
    new_tmp.mkdir()
    removed = ops_watch.clean_side_folders(core, NOW)
    assert fresh.is_dir() and new_tmp.is_dir()
    assert not stale_tmp.exists()
    assert all(not (data.parent / f"{data.name}.before-restore-{n}").exists() for n in names)
    assert len(removed) == 4


def test_a_single_old_side_folder_is_kept(client: TestClient) -> None:
    core = core_of(client)
    data = core.layout.root
    side = data.parent / f"{data.name}.before-restore-20261001T000000Z"
    side.mkdir()
    old = time.time() - 40 * 86400
    os.utime(side, (old, old))
    assert ops_watch.clean_side_folders(core) == []
    assert side.is_dir()


# ---- disk and RAM -----------------------------------------------------------------


def test_low_disk_alerts_once_after_five_minutes_and_again_after_recovery(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    core = core_of(client)
    watch = ops_watch.Resources()
    low = {"disk": 0.05, "ram": 0.5}
    caplog.set_level(logging.INFO, logger="agos.ops")
    t = NOW
    for _ in range(5):
        watch.sample(core, low, t)
        t += timedelta(minutes=1)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    watch.sample(core, low, t)
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and "disk" in errors[0].getMessage().lower()
    watch.sample(core, low, t + timedelta(minutes=1))
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1
    watch.sample(core, {"disk": 0.5, "ram": 0.5}, t + timedelta(minutes=2))
    for n in range(7):
        watch.sample(core, low, t + timedelta(minutes=3 + n))
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 2


def test_low_ram_for_a_moment_does_not_alert(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    core = core_of(client)
    watch = ops_watch.Resources()
    caplog.set_level(logging.INFO, logger="agos.ops")
    t = NOW
    for n in range(20):
        ram = 0.05 if n % 3 else 0.5  # never 5 minutes in a row
        watch.sample(core, {"disk": 0.5, "ram": ram}, t + timedelta(minutes=n))
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_the_machine_readers_answer_fractions(client: TestClient) -> None:
    found = ops_watch.read_free(core_of(client))
    assert 0 < found["disk"] <= 1
    assert 0 < found["ram"] <= 1


# ---- the independent review of eng/ops -------------------------------------------


def test_side_folders_age_from_the_stamp_in_their_name_not_their_mtime(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H3: `agos restore` moves the data folder aside with `mv`, which keeps its old
    mtime: a copy put aside today must not go in the next 15 minutes."""
    core = core_of(client)
    data = core.layout.root
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    months_ago = time.time() - 90 * 86400
    today = data.parent / f"{data.name}.before-restore-20261102T110000Z"
    newest = data.parent / f"{data.name}.before-restore-20261102T113000Z"
    for side in (today, newest):
        side.mkdir()
        os.utime(side, (months_ago, months_ago))  # the old data folder's own mtime
    old_named = data.parent / f"{data.name}.before-restore-20261001T000000Z"
    old_named.mkdir()  # fresh mtime, old stamp
    removed = ops_watch.clean_side_folders(core, NOW)
    assert today.is_dir() and newest.is_dir()
    assert removed == [old_named] and not old_named.exists()


def test_a_crashed_restore_test_folder_is_cleaned_after_a_day(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    folder = tmp_path / "backups"
    (folder / ".agos-rehearsal-abc").mkdir(parents=True)
    old = time.time() - 2 * 86400
    os.utime(folder / ".agos-rehearsal-abc", (old, old))
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(folder))
    ops_watch.clean_side_folders(core)
    assert not (folder / ".agos-rehearsal-abc").exists()


def test_the_monthly_restore_test_passes_when_live_moved_on_since_the_backup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H4: the real restore test (nothing mocked) of a good backup, after the owner
    kept working: new chats and new files in live are not the backup's fault."""
    core = core_of(client)
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    ws = test_api.create_workspace(client, "Shop")
    backups.set_password(core, "a long password")
    backups.run_backup(core)
    client.post(f"/workspaces/{ws}/chats", json={"title": "after the backup"})
    new_file = core.layout.root / "workspaces" / ws / "files" / "after.txt"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("made after the backup")
    ops_watch.check_restore(core, NOW)
    marks = ops_watch._marks(core)
    assert marks["restore_ok"] is True, get_rehearsal(core)
    assert not any("restore test failed" in m for m in open_issues(core))
    # It ran beside the backups (the data disk), and left nothing there.
    assert not list((tmp_path / "backups").glob(".agos-rehearsal-*"))


def get_rehearsal(core: Any) -> Any:
    from agos_core.db.app_settings import get_setting

    return get_setting(core.db, "backup_rehearsal", {})


def test_the_restore_test_runs_on_the_data_disk_never_tmp(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M6: /tmp may be RAM; the test restores beside the backups."""
    core = core_of(client)
    folder = tmp_path / "backups"
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(folder))
    backups.set_password(core, "a long password")
    backups.run_backup(core)
    seen: list[Path] = []
    real = bk.restore

    def spy(path: Path, password: str, target: Path) -> Any:
        seen.append(target)
        return real(path, password, target)

    monkeypatch.setattr(bk, "restore", spy)
    assert backups.rehearse(core).ok
    assert seen and folder in seen[0].parents


def test_the_restore_test_is_skipped_without_room_and_told_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M6: under ~2x the data free, no restore test (it would fill the disk)."""
    core = core_of(client)
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    backups.set_password(core, "a long password")
    backups.run_backup(core)
    monkeypatch.setattr(backups, "_data_size", lambda _core: 10**12)
    ran: list[Path] = []
    monkeypatch.setattr(bk, "restore", lambda *a: ran.append(a[2]))
    ops_watch.check_restore(core, NOW)
    assert ran == []
    skipped = [i for i in error_issues.listed(core.db, status="open") if "skipped" in i.message]
    assert len(skipped) == 1 and "not enough free disk" in skipped[0].message
    assert ops_watch._marks(core).get("restore_ok") is None  # not a failed test
    ops_watch.check_restore(core, NOW + timedelta(days=1))
    skipped = [i for i in error_issues.listed(core.db, status="open") if "skipped" in i.message]
    assert skipped[0].count == 1  # told once a week, tried again daily


def test_a_weekly_schedule_is_not_stale_after_three_days(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H5: the warning follows the schedule (daily 48 h, weekly 8 days)."""
    core = core_of(client)
    backups.set_password(core, "a long password")
    backups.set_schedule(core, "weekly", 4)
    folder = tmp_path / "backups"
    folder.mkdir()
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(folder))
    made = folder / "agos-backup-20261030-100000.agosb"
    made.write_bytes(b"x")
    for days, warned in ((3, False), (7, False), (9, True)):
        stamp = (NOW - timedelta(days=days)).timestamp()
        os.utime(made, (stamp, stamp))
        assert bool(ops_watch.backup_warnings(core, NOW)) is warned, days


def test_no_backup_a_day_after_the_password_was_set_is_an_alert(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8: backups failing from day one (no file ever made) reach the owner."""
    core = core_of(client)
    backups.set_password(core, "a long password")
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    ops_watch.check_backups(core, NOW)
    ops_watch.check_backups(core, NOW + timedelta(hours=12))
    assert not [m for m in open_issues(core) if "backup" in m.lower()]
    ops_watch.check_backups(core, NOW + timedelta(hours=25))
    assert any("No backup has been made" in m for m in open_issues(core))


def test_a_failed_scheduled_backup_is_an_issue(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M8: the backup loop's failure is an ERROR (Settings → Errors, the owner told)."""
    import asyncio

    core = core_of(client)
    monkeypatch.setattr(backups, "due", lambda _core: True)

    def fails(_core: Any) -> None:
        raise ActionError("Backup failed: disk full")

    monkeypatch.setattr(backups, "run_backup", fails)

    async def stop(_s: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(backups.run_forever(core))
    assert any("scheduled backup failed" in m for m in open_issues(core))


def test_update_snapshots_never_go_into_a_backup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """M7: deploy/agos's snapshots hold the roots' .env files: never in a backup."""
    core = core_of(client)
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(tmp_path / "backups"))
    snap = core.layout.root / "system" / "update-snapshots" / "update-20261102T000000Z"
    snap.mkdir(parents=True)
    (snap / "roots.tar").write_bytes(b"TELEGRAM_BOT_TOKEN=x")
    backups.set_password(core, "a long password")
    made = backups.run_backup(core)
    manifest = bk.restore(tmp_path / "backups" / made.name, "a long password", tmp_path / "out")
    assert not [f for f in manifest.files if "update-snapshots" in f]


def test_staging_makes_no_backup_warnings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGOS_STAGING", "1")
    assert ops_watch.backup_warnings(core_of(client), NOW) == []
