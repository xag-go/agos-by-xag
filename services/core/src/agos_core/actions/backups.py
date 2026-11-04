"""Settings → Server & backup: backups, restore rehearsal, machine status.

Hermes's part of a backup is only Hermes's own `hermes backup` (the shared home and
each workspace root, engine/backup.py). What stays AGOS's here has no Hermes
equivalent: the password and AES encryption, agos.db and the workspaces' files,
the daily/weekly schedule with its retention, and the restore rehearsal.

No key is in a backup (ADR 0023, engine/backup.py): which files in a Hermes home
are credential stores is Hermes's own answer (`hermes_private`); when Hermes can't
answer, the backup fails rather than keep one. The rehearsal says which keys a
restore needs re-entered.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import health
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.records import Record
from agos_core.engine import backup as bk
from agos_core.engine import read_cache
from agos_core.engine.hermes import EngineError
from agos_core.security.secrets import decrypt_secret, encrypt_secret

log = logging.getLogger("agos.backup")

Schedule = Literal["off", "daily", "weekly"]
# Tables compared after a restore rehearsal: everything the owner would miss.
# (An older backup may still hold workspace_folders: the core's migrations move it
# when that backup is opened, db/migrations.py step 26.)
CHECKED_TABLES = (
    "workspaces",
    "chats",
    "message_rows",
    "message_attachments",
    "automations",
    "library_items",
    "channel_connections",
    "chat_addresses",
    "app_settings",
    "activity",
)


class BackupFile(Record):
    name: str
    size: int
    created_at: str


class BackupStatus(Record):
    folder: str
    schedule: Schedule
    keep: int
    has_password: bool
    last_backup_at: str | None
    last_backup_ok: bool | None
    last_error: str | None
    last_rehearsal_at: str | None
    last_rehearsal: str | None
    files: list[BackupFile]
    disk_free_gb: float
    disk_total_gb: float
    data_size_mb: float
    # What the owner should know above the backups (no password, backups failing):
    # actions/ops_watch.py, which also sends them to Settings → Errors.
    warnings: list[str] = Field(default_factory=list)


class NoRoom(ActionError):
    """Not enough free disk beside the backups to restore one for a test."""


class Rehearsal(Record):
    ok: bool
    files: int
    tables: dict[str, list[int]]  # table -> [source rows, restored rows]
    missing: list[str]
    detail: str
    # Keys a restore needs re-entered by hand ("NAME (where)"; ADR 0023): the backup
    # holds none. Empty for a backup made before (it still holds its keys).
    reenter: list[str] = Field(default_factory=list)


def backup_dir(core: Core) -> Path:
    configured = os.environ.get("AGOS_BACKUP_DIR")
    folder = Path(configured) if configured else core.layout.root.parent / "agos-backups"
    if core.layout.root.resolve() in [folder.resolve(), *folder.resolve().parents]:
        raise ActionError("The backup folder can't be inside AGOS's data folder.")
    return folder


def _roots(core: Core) -> dict[str, Any]:
    """Each workspace on its own Hermes root: Hermes's own backup of that root."""
    engine = core.engine
    if engine is None:
        return {}
    out: dict[str, Any] = {}
    for ws in workspaces_repo.live_ids(core.db):
        if (engine.root(ws) / "config.yaml").is_file():
            out[engine.profile(ws)] = lambda target, ws=ws: engine.backup_root(ws, target)
    return out


def _root_dirs(core: Core) -> tuple[Path, ...]:
    """The roots folder when it sits in AGOS's data: backed up by Hermes, not walked."""
    engine = core.engine
    if engine is None:
        return ()
    return (engine.settings.roots_dir,)


def _password(core: Core) -> str | None:
    sealed = get_setting(core.db, "backup_password", None)
    return decrypt_secret(core.master_key, sealed, "backup-password") if sealed else None


def set_password(core: Core, password: str) -> None:
    if len(password) < 10:
        raise ActionError(
            "Use at least 10 characters. Keep it somewhere safe: without it the backup can't be opened."
        )
    set_setting(
        core.db, "backup_password", encrypt_secret(core.master_key, password, "backup-password")
    )


def set_schedule(core: Core, schedule: Schedule, keep: int) -> None:
    set_setting(core.db, "backup_schedule", {"schedule": schedule, "keep": max(1, min(keep, 60))})


def gap(schedule: str) -> timedelta:
    """The time between two scheduled backups."""
    return timedelta(days=7 if schedule == "weekly" else 1)


def _schedule(core: Core) -> tuple[Schedule, int]:
    value = get_setting(core.db, "backup_schedule", {"schedule": "daily", "keep": 7})
    return value.get("schedule", "daily"), int(value.get("keep", 7))


def _files(folder: Path) -> list[BackupFile]:
    if not folder.is_dir():
        return []
    files = sorted(
        [*folder.glob("agos-backup-*.agosb"), *folder.glob("xag-backup-*.xagb")],
        key=lambda p: p.name.split("-backup-", 1)[1],
        reverse=True,
    )
    return [
        BackupFile(
            name=f.name,
            size=f.stat().st_size,
            created_at=datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(),
        )
        for f in files
    ]


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(path):
        for name in names:
            with contextlib.suppress(OSError):
                total += (Path(dirpath) / name).stat().st_size
    return total


# The data folder's size is a walk of every file in it (the Hermes roots' installs
# included: 13-15 s cold on live, 3 s warm), and a number that moves all the time:
# kept in memory, walked again behind the page at most every _SIZE_EVERY_S. Only a
# page before the first walk waits (the read-ahead after start usually made it).
_SIZE: read_cache.ReadCache[int] = read_cache.ReadCache("backup_data_size", max_entries=4)
_SIZE_EVERY_S: float = 600


def _data_size(core: Core) -> int:
    root = core.layout.root
    return _SIZE.get(
        str(root), int(time.time() // _SIZE_EVERY_S), lambda: _dir_size(root), stale_ok=True
    )


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): the first walk of the data folder."""
    _data_size(core)


def status(core: Core) -> BackupStatus:
    folder = backup_dir(core)
    schedule, keep = _schedule(core)
    last = get_setting(core.db, "backup_last", {})
    rehearsal = get_setting(core.db, "backup_rehearsal", {})
    usage = shutil.disk_usage(core.layout.root)
    return BackupStatus(
        folder=str(folder),
        schedule=schedule,
        keep=keep,
        has_password=_password(core) is not None,
        last_backup_at=last.get("at"),
        last_backup_ok=last.get("ok"),
        last_error=last.get("error"),
        last_rehearsal_at=rehearsal.get("at"),
        last_rehearsal=rehearsal.get("summary"),
        files=_files(folder),
        disk_free_gb=round(usage.free / 1e9, 1),
        disk_total_gb=round(usage.total / 1e9, 1),
        data_size_mb=round(_data_size(core) / 1e6, 1),
        warnings=_warnings(core),
    )


def _warnings(core: Core) -> list[str]:
    from agos_core.actions import isolation, ops_watch

    # Workspace isolation first: its lines matter more than a late backup.
    return [*isolation.warnings(core), *ops_watch.backup_warnings(core)]


_PRIVATE = (
    "import json, sys\n"
    "from hermes_cli.profiles import profile_path_is_private\n"
    "parts = json.load(sys.stdin)\n"
    "print('AGOS-PRIVATE ' + json.dumps([bool(profile_path_is_private(tuple(p))) for p in parts]))\n"
)


def hermes_private(core: Core) -> bk.Private | None:
    """Hermes's own answer to which paths in a Hermes home are credential stores
    (H: hermes_cli/profiles.py profile_path_is_private, the list its profile export
    never ships). None without Hermes (AGOS's own names still go)."""
    engine = core.engine
    if engine is None:
        return None
    settings = engine.settings

    def ask(parts: list[tuple[str, ...]]) -> list[bool]:
        import json

        from agos_core.engine.hermes import with_runtime
        from agos_core.engine.models import hermes_python
        from agos_core.hermes_gateway import process as hermes_process

        try:
            done = hermes_process.run_process(
                [hermes_python(settings), "-c", _PRIVATE],
                input=json.dumps([list(p) for p in parts]),
                timeout=120,
                env=with_runtime({"HOME": str(settings.host_home), "PATH": "/usr/bin:/bin"}),
            )
            line = next(
                ln for ln in done.stdout.splitlines()[::-1] if ln.startswith("AGOS-PRIVATE ")
            )
            answer = json.loads(line[len("AGOS-PRIVATE ") :])
        except (OSError, hermes_process.SubprocessError, StopIteration, ValueError) as error:
            # Fail closed: a backup that may hold a key is never made.
            raise bk.BackupError(
                "Hermes couldn't say which files hold keys, so no backup was made."
            ) from error
        return [bool(a) for a in answer]

    return ask


def reenter_text(core: Core, manifest: bk.Manifest) -> str:
    """'Re-enter these keys in Settings → Keys: …' for a restore (empty for an older
    backup, which still holds its keys)."""
    names = manifest.reenter()
    if manifest.keys_out is None or not names:
        return ""
    prefix = core.engine.settings.profile_prefix if core.engine is not None else ""

    def shown(line: str) -> str:
        if prefix:
            line = line.replace(f"({prefix}", "(workspace ").replace(f", {prefix}", ", workspace ")
        return line

    return "Re-enter these keys in Settings → Keys: " + ", ".join(shown(n) for n in names) + "."


def run_backup(core: Core) -> BackupFile:
    password = _password(core)
    if password is None:
        raise ActionError("Set a backup password first.")
    folder = backup_dir(core)
    name = f"agos-backup-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.agosb"
    at = datetime.now(UTC).isoformat()
    engine = core.engine
    try:
        # AGOS's own data; everything of Hermes is Hermes's own backup (`hermes
        # backup` of the shared home and of each root, restored by `hermes import`),
        # sealed in the same file. AGOS never copies a Hermes file itself.
        manifest = bk.create(
            core.layout.root,
            folder / name,
            password,
            hermes_backup=(lambda out: engine.backup(out)) if engine is not None else None,
            roots=_roots(core),
            exclude=_root_dirs(core),
            private=hermes_private(core),
        )
        missing = bk.verify_against_source(manifest, core.layout.root, _root_dirs(core))
        if missing:
            log.warning("files created during the backup: %s", missing[:5])
    except (OSError, bk.BackupError, EngineError) as error:
        set_setting(core.db, "backup_last", {"at": at, "ok": False, "error": str(error)[:300]})
        raise ActionError(f"Backup failed: {error}") from error
    _, keep = _schedule(core)
    for old in _files(folder)[keep:]:
        (folder / old.name).unlink(missing_ok=True)
    set_setting(
        core.db, "backup_last", {"at": at, "ok": True, "error": None, "files": len(manifest.files)}
    )
    return next(f for f in _files(folder) if f.name == name)


def _rows(db_path: Path) -> dict[str, int]:
    return health.row_counts(db_path, CHECKED_TABLES)


ROOM_FACTOR = 2  # free disk needed beside the backups: this many times AGOS's data


def _room(core: Core, folder: Path) -> None:
    """Refuses (NoRoom) when the folder's disk has less than ROOM_FACTOR x the data."""
    need = ROOM_FACTOR * _data_size(core)
    free = shutil.disk_usage(folder).free
    if free < need:
        raise NoRoom(
            f"not enough free disk to restore a backup for the test ({free / 1e9:.1f} GB "
            f"free beside the backups, about {need / 1e9:.1f} GB needed).",
            507,
        )


def rehearse(core: Core, name: str | None = None) -> Rehearsal:
    """Restores a backup into an EMPTY folder beside the backups (the data disk, never
    /tmp, which may be RAM) and checks it on its own terms: every file against the
    backup's own manifest (bk.restore), Hermes's zips open, every checked table is
    there, and SQLite's check of the restored database. Live data that moved on
    since the backup (new chats, new files) is fine: the counts are shown, not
    compared. NoRoom when the disk has less than ROOM_FACTOR x the data free."""
    password = _password(core)
    if password is None:
        raise ActionError("Set a backup password first.")
    folder = backup_dir(core)
    files = _files(folder)
    if not files:
        raise ActionError("There is no backup yet.")
    chosen = folder / (name or files[0].name)
    if chosen.parent.resolve() != folder.resolve() or not chosen.is_file():
        raise ActionError("That backup doesn't exist.")
    _room(core, folder)
    with tempfile.TemporaryDirectory(prefix=".agos-rehearsal-", dir=folder) as tmp:
        target = Path(tmp) / "restored"
        try:
            manifest = bk.restore(chosen, password, target)
        except bk.BackupError as error:
            result = Rehearsal(ok=False, files=0, tables={}, missing=[], detail=str(error))
            _remember(core, result)
            return result
        restored_db = target / "agos-data" / "system" / "agos.db"
        live = _rows(core.layout.database)
        back = _rows(restored_db) if restored_db.is_file() else {}
        # SQLite's own check of the restored copy (pages, indexes, foreign keys).
        db_check = health.check(restored_db) if restored_db.is_file() else None
        tables = {t: [live.get(t, -1), back.get(t, -1)] for t in CHECKED_TABLES}
        # Every file of the manifest is there and identical (bk.restore checked
        # each sha256); what live has gained since is not the backup's fault.
        missing: list[str] = []
        for rel in manifest.files:
            if rel.startswith(bk.ROOTS_PREFIX):
                missing += bk.root_zip_problems(target / rel, rel[len(bk.ROOTS_PREFIX) : -4])
        if bk.HERMES_ZIP in manifest.files:  # the shared home's own backup: it opens
            missing += bk.hermes_zip_problems(target / bk.HERMES_ZIP, [])
        # A table missing from the backup is a broken backup; rows live added (or
        # removed) since are the owner's work, not a difference.
        short = [t for t, (_a, b) in tables.items() if b < 0]
        bad_db = db_check is None or not db_check.ok
        ok = not short and not missing and not bad_db
        detail = (
            f"Restored {len(manifest.files)} files; every file matches the backup and "
            "the database passed SQLite's check."
            if ok
            else f"Problems: tables missing {', '.join(short) or 'none'}; "
            f"{len(missing)} problem(s) in Hermes's part."
        )
        if bad_db:
            detail += " The restored database failed SQLite's check: " + (
                "; ".join(db_check.problems[:3]) if db_check is not None else "it is missing"
            )
        again = reenter_text(core, manifest)
        result = Rehearsal(
            ok=ok,
            files=len(manifest.files),
            tables=tables,
            missing=missing[:20],
            detail=f"{detail} {again}".strip(),
            reenter=manifest.reenter(),
        )
    _remember(core, result)
    return result


def _remember(core: Core, result: Rehearsal) -> None:
    set_setting(
        core.db,
        "backup_rehearsal",
        {
            "at": datetime.now(UTC).isoformat(),
            "summary": ("OK — " if result.ok else "FAILED — ") + result.detail,
        },
    )


def due(core: Core, now: datetime | None = None) -> bool:
    schedule, _ = _schedule(core)
    if schedule == "off" or _password(core) is None:
        return False
    last = get_setting(core.db, "backup_last", {}).get("at")
    moment = now or datetime.now(UTC)
    if not last:
        return True
    return moment - datetime.fromisoformat(last) >= gap(schedule)


async def run_forever(core: Core) -> None:
    while True:
        try:
            if await asyncio.to_thread(due, core):
                await asyncio.to_thread(run_backup, core)
                log.info("scheduled backup done")
        except ActionError as error:
            # An ERROR on agos.* is an issue in Settings → Errors and tells the owner
            # (once a day at most: a failed try waits a schedule's gap, like a good one).
            log.error("scheduled backup failed: %s", error.message)
        except Exception:
            log.exception("backup loop failed")
        await asyncio.sleep(15 * 60)


def record_server_rehearsal(core: Core, ok: bool, summary: str) -> None:
    set_setting(
        core.db,
        "server_rehearsal",
        {"at": datetime.now(UTC).isoformat(), "ok": ok, "summary": summary[:300]},
    )
