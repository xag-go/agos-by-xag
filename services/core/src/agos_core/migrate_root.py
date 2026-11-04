"""Move one workspace onto its own Hermes root (ADR 0020), safely.

    python -m agos_core.migrate_root <workspace> --dry-run
    python -m agos_core.migrate_root <workspace> --run
    python -m agos_core.migrate_root <workspace> --check

Run as the AGOS user with AGOS's own environment (the same AGOS_* settings as
agos-core: AGOS_DATA_DIR, AGOS_ENGINE=hermes, AGOS_HERMES_ROOTS…). agos-core may
keep running: while a workspace migrates, AGOS leaves its gateway alone (the
`.agos-migrating` marker) and queues what arrives for it. Roots are AGOS's only
layout: a workspace still in the shared home is not run until it is moved.

--run, one workspace at a time:
 1. checks (the old profile is there, the root is not, disk space);
 2. marks the workspace as migrating; stops its gateway(s) (Hermes's own stop);
 3. backs up: a tar of the old profile folders (the Co-Founder's, its members', its
    Kanban board) and a copy of AGOS's database (sqlite backup) plus the rows of
    this workspace AGOS touches, as JSON;
 4. COPIES (never moves) the Co-Founder's profile into the new root (its default
    home) and each member into <root>/profiles/<a-agent>: sessions, state.db,
    memories (memory_store.db, MEMORY.md, USER.md), skills, cron, SOUL, config
    (gateway.standalone removed), .env (Telegram token, API_SERVER_KEY), app tokens;
    General Settings' keys are written into each home; no login is copied (a
    refresh token is single-use: the root signs in on its own, AGOS shows it);
 5. marks the root as AGOS's (`.agos-root`): from now on AGOS uses it;
 6. makes each group chat a Hermes room (made by the new gateway);
 7. starts the root's gateway (Hermes's service, or AGOS's own process);
 8. runs the checklist and writes report.json beside the backup.
A failure before the switch removes the copy and starts the old gateway again
(the old profiles are never changed). There is no rollback after the switch: AGOS
runs no workspace from the shared home any more; the backup keeps the old profiles.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

from agos_core.config import load_settings
from agos_core.context import Core, open_core
from agos_core.engine import hermes_contract
from agos_core.engine.hermes import (
    ROOT_MARKER,
    EngineError,
    HermesEngine,
    _http_ok,
    scrub_foreign_processes,
)
from agos_core.hermes_gateway import hermes_db, kanban_move
from agos_core.hermes_gateway import process as hermes_process

MIGRATING = ".agos-migrating"
# Left out of the copy: what belongs to a running process, never data.
SKIP_NAMES = {
    "gateway.pid",
    "gateway_state.json",
    "processes.json",
    "gateway.lock",
    ".agos-applied",
    "auth.json",
    "auth.lock",
}
SKIP_DIRS = {"cache", "installs", "tools", "__pycache__", "audio_cache", "image_cache"}
# AGOS tables with rows of the workspace that this tool reads or writes.
TABLES = (
    "chats",
    "chat_turns",
    "hermes_inbox",
    "group_rooms",
    "room_events",
    "channel_connections",
    "chat_addresses",
)
# The shared launcher of the Hermes install (never rewritten by a root).
LAUNCHERS = ("hermes-agent/.hermes/bin/hermes", "hermes-agent/.hermes/bin/hermes-acp")


def say(*parts: Any) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


class OldProfiles:
    """A workspace's profiles in the shared home (the layout before ADR 0020),
    driven by name with Hermes's own CLI (`hermes -p <profile>`): AGOS itself runs
    them no more, only this tool stops (and, after a failed copy, restarts) them."""

    def __init__(self, engine: HermesEngine, workspace_id: str) -> None:
        self.engine = engine
        self.ws = workspace_id

    def _cli(self, key: str, *args: str, timeout: float = 120) -> str:
        return self.engine._cli("-p", self.engine.profile(key), *args, timeout=timeout)

    def running(self, key: str) -> bool:
        home = self.engine.legacy_home(key)
        values: dict[str, str] = {}
        with contextlib.suppress(OSError):
            for line in (home / ".env").read_text().splitlines():
                name, sep, value = line.partition("=")
                if sep:
                    values[name.strip()] = value.strip()
        port = values.get("API_SERVER_PORT", "")
        if port.isdigit() and _http_ok(f"http://127.0.0.1:{int(port)}/health"):
            return True
        return self.engine._gateway_up(home)

    def stop(self, key: str, wait_s: float = 60) -> None:
        scrub_foreign_processes(self.engine.legacy_home(key))
        with contextlib.suppress(EngineError):
            self._cli(key, "gateway", "stop", timeout=wait_s)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and self.running(key):
            time.sleep(0.5)

    def unit(self) -> Path:
        name = f"hermes-gateway-{self.engine.profile(self.ws)}.service"
        return self.engine.settings.host_home / ".config" / "systemd" / "user" / name

    def uninstall(self) -> None:
        self._cli(self.ws, "gateway", "uninstall")

    def start(self) -> None:
        """The old Co-Founder's gateway again, as it ran before: Hermes's service, or
        (supervisor "spawn") a process of its own."""
        home = self.engine.legacy_home(self.ws)
        if self.engine.settings.gateway_supervisor == "spawn":
            self.engine.runner.spawn(
                [
                    self.engine.settings.hermes_bin,
                    "-p",
                    self.engine.profile(self.ws),
                    *("gateway", "run", "--replace", "--force", "-q"),
                ],
                log_file=home / "logs" / "agos-gateway.log",
                env=self.engine._env(),
            )
            return
        self._cli(
            self.ws, "gateway", "install", "--no-start-now", "--start-on-login", "--if-missing"
        )
        self._cli(self.ws, "gateway", "start")


class Migration:
    def __init__(self, core: Core, workspace_id: str) -> None:
        if core.engine is None:
            raise SystemExit("AGOS_ENGINE=hermes is needed")
        self.core = core
        self.engine: HermesEngine = core.engine
        self.ws = workspace_id
        self.roots: Path = self.engine.settings.roots_dir
        row = core.db.execute(
            "SELECT id FROM workspaces WHERE id = ? AND deleted_at IS NULL", (workspace_id,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"no workspace {workspace_id!r}")
        from agos_core.db.workspaces import name_of

        self.name = name_of(core.db, workspace_id)
        self.profile = self.engine.profile(workspace_id)
        self.old = self.engine.legacy_home(workspace_id)
        self.old_gateways = OldProfiles(self.engine, workspace_id)
        self.root = self.engine.root(workspace_id)
        self.backups = core.layout.root / "backups" / "migrate-root"

    # ---- what is where -----------------------------------------------------------------

    def members(self) -> list[tuple[str, Path]]:
        """(member part "a-<agent>", old home) of each of its members in the shared home."""
        folder = self.engine.settings.hermes_home / "profiles"
        out = []
        for p in sorted(folder.glob(f"{self.profile}--*")):
            sub = p.name[len(self.profile) + 2 :]
            if p.is_dir() and sub and "--" not in sub:
                out.append((sub, p))
        return out

    def kanban_old(self) -> Path:
        return self.engine.settings.hermes_home / "agos-kanban" / self.ws

    def group_chats(self) -> list[int]:
        return [
            int(r["id"])
            for r in self.core.db.execute(
                "SELECT id FROM chats WHERE workspace_id = ? AND kind = 'group' AND deleted_at IS NULL",
                (self.ws,),
            )
        ]

    def launchers(self) -> dict[str, str]:
        base = Path(self.engine.settings.hermes_home)
        out = {}
        for rel in LAUNCHERS:
            path = base / rel
            if path.is_file():
                out[str(path)] = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - a fingerprint
        return out

    # ---- dry run -------------------------------------------------------------------------

    def plan(self) -> dict[str, Any]:
        problems = []
        if not (self.old / "config.yaml").is_file():
            problems.append(f"the old profile {self.old} is missing")
        if (self.root / ROOT_MARKER).is_file():
            problems.append(f"already migrated: {self.root}")
        elif self.root.exists() and any(self.root.iterdir()):
            problems.append(f"{self.root} exists and is not empty")
        sizes = {str(self.old): _size(self.old)}
        for _, home in self.members():
            sizes[str(home)] = _size(home)
        need = sum(sizes.values()) * 2 + 1_500_000_000  # copy + backup + the root's own runtime
        where = self.roots if self.roots.exists() else self.roots.parent
        free = shutil.disk_usage(where).free
        if free < need:
            problems.append(f"not enough disk: {free >> 20} MB free, ~{need >> 20} MB needed")
        return {
            "workspace": self.ws,
            "name": self.name,
            "from": {
                "cofounder": str(self.old),
                "members": {s: str(h) for s, h in self.members()},
                "kanban": str(self.kanban_old()) if self.kanban_old().is_dir() else None,
            },
            "to": {
                "root": str(self.root),
                "members": {s: str(self.root / "profiles" / s) for s, _ in self.members()},
            },
            "group_chats_to_rooms": self.group_chats(),
            "gateway": {
                "stop": self.old_gateways.unit().name
                if self.old_gateways.unit().is_file()
                else "AGOS-spawned process"
            },
            "sizes_bytes": sizes,
            "backup_to": str(self.backups),
            "problems": problems,
        }

    # ---- run -------------------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        plan = self.plan()
        if plan["problems"]:
            raise SystemExit("not migrating: " + "; ".join(plan["problems"]))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = self.backups / f"{self.ws}-{stamp}"
        backup.mkdir(parents=True)
        launchers = self.launchers()
        (backup / "launchers.json").write_text(json.dumps(launchers, indent=1))
        self.root.parent.mkdir(parents=True, exist_ok=True)
        marker = self.root.parent / f"{self.profile}{MIGRATING}"
        marker.write_text(json.dumps({"workspace": self.ws, "since": stamp, "backup": str(backup)}))
        try:
            say("1/7 stopping the workspace's gateway(s)")
            self._stop_old()
            say("2/7 backing up to", backup)
            self._backup(backup)
            say("3/7 copying the Co-Founder and its members into", self.root)
            self._copy()
            say("4/7 the root is AGOS's now")
            (self.root / ROOT_MARKER).write_text(
                json.dumps(
                    {
                        "workspace": self.ws,
                        "profile": self.profile,
                        "migrated": stamp,
                        "backup": str(backup),
                    },
                    sort_keys=True,
                )
            )
            self._settings()
        except BaseException:
            say("FAILED before the switch: rolling back")
            self._undo_copy(marker)
            self._start_old()
            raise
        finally:
            marker.unlink(missing_ok=True)
        say("5/7 group chats → Hermes rooms")
        rooms = self._rooms()
        say("6/7 starting the root's gateway")
        started, error = True, ""
        try:
            self.engine.start(self.ws, wait_s=180)
        except (EngineError, OSError) as failed:
            started, error = False, str(failed)
        say("7/7 checklist")
        report = {
            "workspace": self.ws,
            "backup": str(backup),
            "root": str(self.root),
            "rooms": rooms,
            "gateway_started": started,
            "gateway_error": error,
            "checklist": self.checklist(launchers),
        }
        (backup / "report.json").write_text(json.dumps(report, indent=1))
        return report

    def check(self) -> dict[str, Any]:
        """The checklist again, on a workspace already moved (report-check.json beside
        its latest backup; the launchers compared with what that backup saw)."""
        if not (self.root / ROOT_MARKER).is_file():
            raise SystemExit(f"{self.root} is not a migrated root: nothing to check")
        found = sorted(self.backups.glob(f"{self.ws}-*"))
        backup = found[-1] if found else None
        launchers = self.launchers()
        if backup is not None and (backup / "launchers.json").is_file():
            launchers = json.loads((backup / "launchers.json").read_text())
        report = {
            "workspace": self.ws,
            "root": str(self.root),
            "backup": str(backup) if backup else None,
            "checklist": self.checklist(launchers),
        }
        if backup is not None:
            (backup / "report-check.json").write_text(json.dumps(report, indent=1))
        return report

    def _stop_old(self) -> None:
        old = self.old_gateways
        for key in [f"{self.ws}--{s}" for s, _ in self.members()] + [self.ws]:
            with contextlib.suppress(EngineError, OSError):
                if old.running(key):
                    old.stop(key, wait_s=60)
        if old.running(self.ws):
            raise SystemExit("the old gateway did not stop: nothing was changed")
        # Off at boot too: an old service left enabled would start next to the root's
        # after a reboot (two gateways on one Telegram bot). A failure before the
        # switch installs it again (OldProfiles.start).
        if old.unit().is_file():
            try:
                old.uninstall()
            except EngineError as error:
                raise SystemExit(f"the old gateway's service was not removed: {error}") from None

    def _backup(self, backup: Path) -> None:
        with tarfile.open(backup / "profiles.tar.gz", "w:gz") as tar:
            tar.add(self.old, arcname=self.old.name, filter=_no_runtime)
            for _, home in self.members():
                tar.add(home, arcname=home.name, filter=_no_runtime)
            if self.kanban_old().is_dir():
                tar.add(self.kanban_old(), arcname=f"agos-kanban/{self.ws}")
        target = sqlite3.connect(backup / "agos.db")
        with target:
            source = sqlite3.connect(self.core.layout.database)
            source.backup(target)
            source.close()
        target.close()
        rows: dict[str, list[dict[str, Any]]] = {}
        for table in TABLES:
            with contextlib.suppress(sqlite3.Error):
                rows[table] = [
                    dict(r)
                    for r in self.core.db.execute(
                        f"SELECT * FROM {table} WHERE workspace_id = ?", (self.ws,)
                    )
                ]
        (backup / "rows.json").write_text(json.dumps(rows, indent=1, default=str))
        (backup / "launchers.json").write_text(json.dumps(self.launchers(), indent=1))

    def _copy(self) -> None:
        _copytree(self.old, self.root)
        for sub, home in self.members():
            _copytree(home, self.root / "profiles" / sub)
        if (self.kanban_old() / "kanban.db").is_file():
            # Hermes's own default board of the root (kanban_move: the paths it keeps
            # point at the root; the old board is not changed).
            kanban_move.move_board(self.kanban_old(), self.root, keep_source=True)
        for home in [self.root] + [self.root / "profiles" / s for s, _ in self.members()]:
            _drop_standalone(home / "config.yaml")
            kanban_move.forget_line(home / ".env")

    def _settings(self) -> None:
        """What AGOS writes into a root (container key, no shim, the runtime, General
        Settings' keys) — AGOS's own code, now that the root is marked."""
        from agos_core.actions import general_sync, library

        with contextlib.suppress(Exception):
            library.apply_workspace(self.core, self.ws)
        for _, home in general_sync.homes(self.core, self.ws):
            general_sync.sync_home(self.core, home)

    def _rooms(self) -> dict[str, Any]:
        from agos_core.actions import rooms

        out: dict[str, Any] = {}
        for chat in self.group_chats():
            try:
                room = rooms.ensure_room(self.core, self.ws, chat)
                out[str(chat)] = room["room_id"] if room else "no ready member yet (made later)"
            except Exception as error:  # noqa: BLE001 - reported
                out[str(chat)] = f"error: {error}"
        return out

    # ---- checklist ----------------------------------------------------------------------------

    def checklist(self, launchers: dict[str, str]) -> dict[str, Any]:
        from agos_core.actions import general_sync

        checks: dict[str, Any] = {}
        deadline = time.monotonic() + 180  # a gateway takes a while to come up
        state = _json(self.root / "gateway_state.json")
        while state.get("gateway_state") != "running" and time.monotonic() < deadline:
            time.sleep(3)
            state = _json(self.root / "gateway_state.json")
        checks["gateway running"] = state.get("gateway_state") == "running"
        platforms = state.get("platforms") or {}
        if (self.old / ".env").is_file() and "TELEGRAM_BOT_TOKEN=" in (
            self.old / ".env"
        ).read_text():
            checks["telegram connected"] = (platforms.get("telegram") or {}).get(
                "state"
            ) == "connected"
        # Nothing lost (the root only grows once it is in use).
        checks["sessions kept"] = _sessions(self.root) >= _sessions(self.old)
        for sub, home in self.members():
            checks[f"sessions kept ({sub})"] = _sessions(self.root / "profiles" / sub) >= _sessions(
                home
            )
        for name in ("memories/MEMORY.md", "memories/USER.md", "memory_store.db", "SOUL.md"):
            if (self.old / name).exists():
                checks[f"{name} kept"] = (self.root / name).exists()
        tokens_old = _files(self.old / "mcp-tokens")
        checks["app tokens kept"] = tokens_old <= _files(self.root / "mcp-tokens")
        checks["skills kept"] = _files(self.old / "skills") <= _files(self.root / "skills")
        checks["cron kept"] = _files(self.old / "cron") <= _files(self.root / "cron")
        checks["no gateway.standalone"] = (
            "standalone: true" not in (self.root / "config.yaml").read_text()
        )
        login = general_sync.login_state(self.core, self.ws)
        checks["model login"] = "needs login (Settings → Models)" if login["needsLogin"] else "ok"
        rooms_ok = [
            r["state"]
            for r in self.core.db.execute(
                "SELECT state FROM group_rooms WHERE workspace_id = ?", (self.ws,)
            )
        ]
        checks["rooms"] = rooms_ok or "no group chat"
        checks["cross-workspace refused"] = self._isolation()
        checks["launcher unchanged"] = launchers == self.launchers()
        return checks

    def _isolation(self) -> bool:
        """Hermes's own roster wall in this root: it accepts only its own profiles."""
        code = (
            "import json, os\n"
            "from pathlib import Path\n"
            "from gateway.hosted_room_discussion import validate_roster\n"
            "from tui_gateway.hosted_room_service import HostedRoomService as S\n"
            "service = object.__new__(S)\n"
            "service.db_path = Path(os.environ['HERMES_HOME']) / 'state.db'\n"
            "own = list(service.local_profiles())\n"
            "foreign = [{'member_id': 'cofounder', 'profile': 'default', 'handle': 'cofounder'},\n"
            "           {'member_id': 'x', 'profile': 'agos-other--a-x', 'handle': 'x'}]\n"
            "try:\n"
            "    validate_roster(foreign, local_profiles=own)\n"
            "    refused = False\n"
            "except Exception:\n"
            "    refused = True\n"
            "print('AGOS-OWN ' + json.dumps({'own': own, 'refused': refused}))\n"
        )
        try:
            argv = list(self.engine._runtime_argv())
        except (EngineError, OSError, ValueError):
            return False
        from agos_core.engine.hermes import JUDGE_RUN, child_env

        argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
        try:
            done = hermes_process.run_process(
                argv,
                input=code,
                timeout=300,
                env=child_env(self.engine.hermes_env(self.ws)),
            )
            hermes_contract.ran(done)
        except hermes_process.TimeoutExpired:
            say("   the isolation probe did not finish in time (a busy machine?): run --check")
            return False
        lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-OWN ")]
        if not lines:
            return False
        found = json.loads(lines[-1][9:])
        own = set(found["own"])
        # Only this root's own profiles, and Hermes refuses anyone else's.
        return (
            bool(found["refused"])
            and "default" in own
            and all(p == "default" or (self.root / "profiles" / p).is_dir() for p in own)
            and not any(p.startswith(self.engine.settings.profile_prefix) for p in own)
        )

    # ---- a failure before the switch ----------------------------------------------------

    def _undo_copy(self, marker: Path) -> None:
        if self.root.exists() and not (self.root / ROOT_MARKER).is_file():
            shutil.rmtree(self.root, ignore_errors=True)
        elif (self.root / ROOT_MARKER).is_file():
            (self.root / ROOT_MARKER).unlink()
            shutil.rmtree(self.root, ignore_errors=True)
        marker.unlink(missing_ok=True)

    def _start_old(self) -> None:
        with contextlib.suppress(EngineError, OSError):
            self.old_gateways.start()


# ---- helpers ------------------------------------------------------------------------------------


def _no_runtime(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    return None if any(p in SKIP_DIRS for p in parts) else info


def _copytree(src: Path, dst: Path) -> None:
    def ignore(folder: str, names: list[str]) -> set[str]:
        return {
            n for n in names if n in SKIP_NAMES or n in SKIP_DIRS or n.endswith((".pid", ".lock"))
        }

    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True, ignore=ignore, dirs_exist_ok=True)
    # SQLite files as consistent copies (a WAL may still hold the latest rows).
    for db in src.rglob("*.db"):
        rel = db.relative_to(src)
        if any(p in SKIP_DIRS for p in rel.parts):
            continue
        with contextlib.suppress(sqlite3.Error):
            source = hermes_db.connect_ro(db)
            target = sqlite3.connect(dst / rel)
            source.backup(target)
            source.close()
            target.close()
            for extra in ("-wal", "-shm"):
                (dst / rel).with_name(rel.name + extra).unlink(missing_ok=True)


def _drop_standalone(config: Path) -> None:
    """gateway.standalone was a shim for one gateway per profile: a root's gateway
    is its own host. Removed from the copy only (the old profile is untouched)."""
    if not config.is_file():
        return
    lines = config.read_text().splitlines()
    out, in_gateway = [], False
    for line in lines:
        if line and not line[0].isspace():
            in_gateway = line.split(":", 1)[0].strip() == "gateway"
        if in_gateway and line.strip().startswith("standalone:"):
            continue
        out.append(line)
    config.write_text("\n".join(out) + "\n")


def _size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and not p.is_symlink() and not any(x in SKIP_DIRS for x in p.parts):
            with contextlib.suppress(OSError):
                total += p.stat().st_size
    return total


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _sessions(home: Path) -> int:
    db = home / "state.db"
    if not db.is_file():
        return 0
    try:
        con = hermes_db.connect_ro(db)
        try:
            return int(con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return -1


def _files(folder: Path) -> set[str]:
    """The files of a folder, as the copy sees them (SQLite's -wal/-shm side files are
    merged into their database; locks and pid files are runtime, never copied)."""
    if not folder.is_dir():
        return set()
    return {
        str(p.relative_to(folder))
        for p in folder.rglob("*")
        if p.is_file()
        and not p.name.endswith(("-wal", "-shm", ".lock", ".pid"))  # the copy skips those
        and p.name not in SKIP_NAMES
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agos_core.migrate_root",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("workspace")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--check", action="store_true", help="the checklist again, after --run")
    args = parser.parse_args(argv)
    core = open_core(load_settings())
    migration = Migration(core, args.workspace)
    if args.dry_run:
        print(json.dumps(migration.plan(), indent=1))
        return 0
    result = migration.check() if args.check else migration.run()
    print(json.dumps(result, indent=1))
    failed = [k for k, v in result["checklist"].items() if v is False]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
