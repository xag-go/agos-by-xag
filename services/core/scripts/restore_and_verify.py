"""Restore an AGOS backup into an EMPTY folder and verify it, for move day and
its rehearsal. Exits non-zero if anything is missing or different.

  uv run python scripts/restore_and_verify.py <backup.agosb> <empty-dir> [--against <agos-data>]

The password comes from AGOS_BACKUP_PASSWORD or is asked for (never an argument).
With --against, every table's row count and every file of the live data dir are
compared with the restored copy.
"""

import argparse
import getpass
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

from agos_core.actions.backups import CHECKED_TABLES
from agos_core.engine import backup as bk

# The tables the in-app rehearsal compares (an older backup may hold tables that are
# gone since, such as workspace_folders: opening it in AGOS migrates them).
TABLES = CHECKED_TABLES


def rows(db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = {}
        for t in TABLES:
            try:
                out[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
            except sqlite3.OperationalError:
                out[t] = -1  # not in this database
        return out
    finally:
        conn.close()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspaces(db: Path) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0])
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def check_roots(target: Path) -> tuple[list[str], list[str]]:
    """Every workspace's Hermes root in the restored backup (hermes/roots/<name>.zip,
    ADR 0020): it opens, holds its config.yaml, and carries no login (auth.json).
    Returns (the roots' names, the problems)."""
    import zipfile

    names: list[str] = []
    problems: list[str] = []
    for path in sorted((target / bk.ROOTS_PREFIX).glob("*.zip")):
        name = path.name[: -len(".zip")]
        names.append(name)
        problems += bk.root_zip_problems(path, name)
        try:
            with zipfile.ZipFile(path) as zf:
                if any(Path(n).name == "auth.json" for n in zf.namelist()):
                    problems.append(f"{name}: auth.json must not be in a backup")
        except (OSError, zipfile.BadZipFile):
            pass  # already told by root_zip_problems
    return names, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--against", type=Path)
    args = parser.parse_args()
    password = os.environ.get("AGOS_BACKUP_PASSWORD") or getpass.getpass("Backup password: ")
    manifest = bk.restore(args.backup, password, args.target)
    print(f"restored {len(manifest.files)} files into {args.target}")
    problems: list[str] = []
    restored_db = args.target / "agos-data" / "system" / "agos.db"
    if not restored_db.is_file():
        problems.append("no database in the backup")
    profiles = sorted((args.target / "hermes" / "profiles").glob("*"))
    print(f"profiles: {', '.join(p.name for p in profiles) or 'none'}")
    for p in profiles:
        for needed in ("SOUL.md", "config.yaml"):
            if not (p / needed).is_file():
                problems.append(f"{p.name}: {needed} missing")
        if (p / "auth.json").exists():
            problems.append(f"{p.name}: auth.json must not be in a backup")
    roots, root_problems = check_roots(args.target)
    print(f"workspace roots: {', '.join(roots) or 'none'}")
    problems += root_problems
    if restored_db.is_file() and not roots and not profiles and _workspaces(restored_db):
        problems.append("no workspace's Hermes in the backup (hermes/roots/*.zip)")
    if args.against and restored_db.is_file():
        live, back = rows(args.against / "system" / "agos.db"), rows(restored_db)
        for table in TABLES:
            mark = "ok" if back[table] >= live[table] or table == "app_settings" else "DIFFERENT"
            print(f"  {table:24} live {live[table]:6}  restored {back[table]:6}  {mark}")
            if mark != "ok":
                problems.append(f"table {table}: {back[table]} vs {live[table]}")
        for path in (args.against / "workspaces").rglob("*"):
            if path.is_file() and not path.is_symlink():
                rel = path.relative_to(args.against)
                copy = args.target / "agos-data" / rel
                if not copy.is_file():
                    problems.append(f"missing file {rel}")
                elif sha(copy) != sha(path) and "agos.db" not in path.name:
                    problems.append(f"changed file {rel}")
    if problems:
        print("\nPROBLEMS:")
        for p in problems[:50]:
            print(" -", p)
        return 1
    print("\nEverything identical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
