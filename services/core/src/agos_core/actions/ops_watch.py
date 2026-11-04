"""The ops watch: one loop that keeps an eye on the machine and the safety nets.

Every minute: free disk on AGOS's data folder and free memory (`MemAvailable`).
Below `LOW` (10%) for `LOW_FOR` (5 minutes) in a row = one ERROR on `agos.ops`;
again only after it was fine in between. An ERROR on an `agos.*` logger is how
every AGOS alert travels: the System Log, Settings → Errors and the owner's
`agos.error` notification (actions/error_alerts.py), once per issue.

Every `SLOW_EVERY` minutes:
- backups: no backup password (so no backups at all), no backup at all `NONE_FOR`
  after the watch first saw a password, or the newest backup older than its
  schedule's gap plus `LATE` (daily: 48 h, weekly: 8 days) while the schedule is on
  → an ERROR at most once a day per kind; Settings → Server & backup shows the same
  lines (`backup_warnings`);
- the monthly restore test: `backups.rehearse` of the newest backup into an empty
  folder beside the backups (on the data disk, never /tmp): every file checked
  against the backup's own manifest, every table there, the restored database
  checked by SQLite. Live data newer than the backup is fine. Unless one ran in the
  last `RESTORE_EVERY`; failure = ERROR; not enough free disk = skipped (an ERROR at
  most once a week, a retry the next day);
- the weekly database check: SQLite's integrity and foreign-key checks of agos.db
  (db/health.py); failure = ERROR;
- old side folders: the data copies `agos restore` puts aside
  (`<data>.before-restore-<stamp>`; the newest one always stays, the others go
  `SIDE_KEEP_DAYS` after their <stamp>) and a crashed restore's temporary folders
  (`<backups>/restore-<stamp>`, a day after their <stamp>). The age is the stamp in
  the name, never the folder's mtime: `mv` keeps the old data folder's mtime, which
  can be months old.

Backups stay on this machine (the owner's choice); nothing is copied elsewhere.
A staging copy (AGOS_STAGING=1) makes no backups of its own: no backup warnings,
no restore test there.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agos_core.actions import backups
from agos_core.db import health
from agos_core.db.app_settings import get_setting, set_setting

log = logging.getLogger("agos.ops")
backup_log = logging.getLogger("agos.backup")

KEY = "ops.watch"
LOW = 0.10
LOW_FOR = timedelta(minutes=5)
LATE = timedelta(hours=24)  # a backup this late past its schedule's gap = failing
NONE_FOR = timedelta(hours=24)  # a password and still no backup after this = failing
TELL_AGAIN = timedelta(hours=24)
SKIPPED_AGAIN = timedelta(days=7)
RESTORE_EVERY = timedelta(days=30)
DATABASE_EVERY = timedelta(days=7)
SIDE_KEEP_DAYS = 14
TEMP_KEEP = timedelta(days=1)
SAMPLE_S = 60
SLOW_EVERY = 15  # samples between two slow passes

NO_BACKUPS = (
    "No backup password is set, so AGOS makes no backups. "
    "Set one in Settings → Server & backup (or run agos backup)."
)


def staging() -> bool:
    return os.environ.get("AGOS_STAGING", "") == "1"


def _marks(core: Any) -> dict[str, Any]:
    value = get_setting(core.db, KEY, {})
    return value if isinstance(value, dict) else {}


def _mark(core: Any, **values: Any) -> None:
    set_setting(core.db, KEY, {**_marks(core), **values})


def _at(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


# ---- backups ----------------------------------------------------------------------


def _warnings(core: Any, now: datetime) -> list[tuple[str, str]]:
    if staging():
        return []
    if backups._password(core) is None:
        return [("password", NO_BACKUPS)]
    schedule, _ = backups._schedule(core)
    if schedule == "off":
        return []
    folder = backups.backup_dir(core)
    newest = max(
        (f.stat().st_mtime for f in folder.glob("agos-backup-*.agosb")) if folder.is_dir() else (),
        default=None,
    )
    if newest is None:
        since = _at(_marks(core).get("none_since"))
        if since is not None and now - since >= NONE_FOR:
            return [
                (
                    "none",
                    "No backup has been made since the backup password was set: scheduled "
                    "backups are failing. See the last backup's result in Settings → Server & backup.",
                )
            ]
        return [("none", "There is no backup yet. The first one runs within 15 minutes.")]
    age = now - datetime.fromtimestamp(newest, UTC)
    if age >= stale_after(schedule):
        hours = int(age.total_seconds() // 3600)
        return [
            (
                "stale",
                f"The newest backup is {hours} hours old: scheduled backups are failing. "
                "See the last backup's result in Settings → Server & backup.",
            )
        ]
    return []


def stale_after(schedule: str) -> timedelta:
    """How old the newest backup may get before it means backups are failing."""
    return backups.gap(schedule) + LATE


def backup_warnings(core: Any, now: datetime | None = None) -> list[str]:
    """The lines Settings → Server & backup shows above the backups."""
    return [text for _kind, text in _warnings(core, now or datetime.now(UTC))]


def check_backups(core: Any, now: datetime) -> None:
    marks = _marks(core)
    told = dict(marks.get("backup_told") or {})
    found = _warnings(core, now)
    # When the watch first saw a password and no backup: the clock for "none".
    no_backup = any(kind == "none" for kind, _ in found)
    none_since = (marks.get("none_since") or now.isoformat()) if no_backup else None
    _mark(core, none_since=none_since)
    for kind, text in _warnings(core, now):
        since = _at(none_since)
        if kind == "none" and (since is None or now - since < NONE_FOR):
            continue  # the first backup is on its way: the page says so, no alert
        last = _at(told.get(kind))
        if last is not None and now - last < TELL_AGAIN:
            continue
        backup_log.error("%s", text)
        told[kind] = now.isoformat()
    _mark(core, backup_told=told)


def check_restore(core: Any, now: datetime) -> None:
    """The monthly restore test of the newest backup."""
    if staging() or backups._password(core) is None:
        return
    if not backups._files(backups.backup_dir(core)):
        return
    marks = _marks(core)
    manual = _at(get_setting(core.db, "backup_rehearsal", {}).get("at"))
    last = max((t for t in (_at(marks.get("restore_at")), manual) if t), default=None)
    if last is not None and now - last < RESTORE_EVERY:
        return
    skipped = _at(marks.get("restore_skipped_at"))
    if skipped is not None and now - skipped < TELL_AGAIN:
        return  # no room yesterday: try again tomorrow
    try:
        result = backups.rehearse(core)
    except backups.NoRoom as error:
        told = _at(marks.get("restore_skip_told"))
        if told is None or now - told >= SKIPPED_AGAIN:
            backup_log.error("monthly restore test skipped: %s", error.message)
            _mark(core, restore_skipped_at=now.isoformat(), restore_skip_told=now.isoformat())
        else:
            backup_log.warning("monthly restore test skipped: %s", error.message)
            _mark(core, restore_skipped_at=now.isoformat())
        return
    except Exception as error:  # noqa: BLE001 - reported, the loop goes on
        _mark(core, restore_at=now.isoformat(), restore_ok=False)
        backup_log.error("monthly restore test failed: %s", type(error).__name__)
        return
    _mark(core, restore_at=now.isoformat(), restore_ok=result.ok)
    if result.ok:
        backup_log.info("monthly restore test OK: %s", result.detail)
    else:
        backup_log.error("monthly restore test failed: %s", result.detail[:300])


# ---- the database -----------------------------------------------------------------


def database_due(core: Any, now: datetime) -> bool:
    last = _at(_marks(core).get("database_at"))
    return last is None or now - last >= DATABASE_EVERY


def check_database(core: Any, now: datetime) -> None:
    if not database_due(core, now):
        return
    found = health.check(core.layout.database)
    _mark(core, database_at=now.isoformat(), database_ok=found.ok)
    if found.ok:
        log.info("weekly database check OK (%d tables)", found.tables)
    else:
        log.error("weekly database check failed: %s", "; ".join(found.problems[:5])[:500])


# ---- side folders -----------------------------------------------------------------


def _stamp_of(name: str) -> datetime | None:
    """The <stamp> (20261102T120000Z, UTC) a side folder's name ends with."""
    try:
        return datetime.strptime(name[-16:], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def clean_side_folders(core: Any, now: datetime | None = None) -> list[Path]:
    moment = now or datetime.now(UTC)
    data: Path = core.layout.root
    side = re.compile(rf"^{re.escape(data.name)}\.before-restore-\d{{8}}T\d{{6}}Z$")
    removed: list[Path] = []
    found = sorted(
        (
            p
            for p in data.parent.iterdir()
            if side.match(p.name) and p.is_dir() and not p.is_symlink()
        ),
        key=lambda p: p.name,
    )
    keep = timedelta(days=SIDE_KEEP_DAYS)
    for path in found[:-1]:  # the newest copy always stays
        stamp = _stamp_of(path.name)
        if stamp is not None and moment - stamp >= keep:
            removed.append(path)
    with contextlib.suppress(Exception):
        folder = backups.backup_dir(core)
        if folder.is_dir():
            temp = re.compile(r"^restore-\d{8}T\d{6}Z$")
            for p in folder.iterdir():
                if not temp.match(p.name) or not p.is_dir() or p.is_symlink():
                    continue
                stamp = _stamp_of(p.name)
                if stamp is not None and moment - stamp >= TEMP_KEEP:
                    removed.append(p)
            # A restore test the core never finished (killed mid-way): a fresh
            # mkdtemp folder, so its own mtime is its age.
            old = moment.timestamp() - TEMP_KEEP.total_seconds()
            removed += [
                p
                for p in folder.glob(".agos-rehearsal-*")
                if p.is_dir() and not p.is_symlink() and p.stat().st_mtime < old
            ]
    for path in removed:
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            log.warning("old restore folder not removed (files AGOS can't delete): %s", path.name)
        else:
            log.info("old restore folder removed: %s", path.name)
    return removed


# ---- disk and memory --------------------------------------------------------------


def read_free(core: Any) -> dict[str, float]:
    """Free disk (on the data folder) and available memory, as fractions of the total."""
    usage = shutil.disk_usage(core.layout.root)
    out = {"disk": usage.free / usage.total if usage.total else 1.0, "ram": 1.0}
    with contextlib.suppress(OSError, ValueError):
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, _, rest = line.partition(":")
            info[name] = int(rest.split()[0])
        if info.get("MemTotal"):
            out["ram"] = info.get("MemAvailable", info["MemTotal"]) / info["MemTotal"]
    return out


_WORDS = {
    "disk": "Low disk space: {pct}% free on AGOS's data disk. Free some space "
    "(docs/runbooks/disk-full.md) before backups and agents start failing.",
    "ram": "Low memory: {pct}% of the machine's memory is free for 5 minutes. "
    "Agents may get slow or be stopped; pause a busy workspace or add memory.",
}


@dataclass
class Resources:
    """Low since when, and whether the owner was already told, per resource."""

    low_since: dict[str, datetime] = field(default_factory=dict)
    told: set[str] = field(default_factory=set)

    def sample(self, core: Any, free: dict[str, float], now: datetime) -> None:
        for name, fraction in free.items():
            if fraction >= LOW:
                if name in self.told:
                    log.info("%s is fine again (%d%% free)", name, round(fraction * 100))
                self.low_since.pop(name, None)
                self.told.discard(name)
                continue
            since = self.low_since.setdefault(name, now)
            if name not in self.told and now - since >= LOW_FOR:
                log.error("%s", _WORDS[name].format(pct=round(fraction * 100, 1)))
                self.told.add(name)


# ---- the loop ---------------------------------------------------------------------


def slow_pass(core: Any, now: datetime) -> None:
    from agos_core.actions import staging as staging_copy

    try:
        staging_copy.quiet(core)  # a staging copy: any cron job (re)created is paused
    except Exception:
        log.exception("staging: cron jobs not paused")
    for step in (check_backups, check_restore, check_database):
        try:
            step(core, now)
        except Exception:
            log.exception("ops watch step %s failed", step.__name__)
    try:
        clean_side_folders(core)
    except Exception:
        log.exception("ops watch: old restore folders not cleaned")


async def run_forever(core: Any) -> None:
    watch = Resources()
    tick = 0
    while True:
        await asyncio.sleep(SAMPLE_S)
        tick += 1
        try:
            free = await asyncio.to_thread(read_free, core)
            watch.sample(core, free, datetime.now(UTC))
        except Exception:
            log.exception("ops watch: disk/memory not read")
        if tick % SLOW_EVERY == 0:
            await asyncio.to_thread(slow_pass, core, datetime.now(UTC))
