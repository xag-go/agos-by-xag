"""Moving an old board (AGOS's old <root>/agos-kanban pin) into Hermes's own default
board of a root, for the root migration (migrate_root.py copies the shared home's
board into a new root).

Hermes's default board home of a root outside ~/.hermes is the root itself, shared by
<root>/profiles/* (hermes_cli/kanban_db.py kanban_home, hermes_constants.py
get_default_hermes_root): its database is <root>/kanban.db and its files
(workspaces, attachments, logs, other boards, the `current` board) are under
<root>/kanban (kanban_db.py kanban_db_path, workspaces_root, attachments_root,
worker_logs_dir, boards_root).

The database is copied with SQLite's backup (WAL included) and the absolute paths
Hermes keeps in it are pointed at the new home; every table must have the same row
count as the old one, else nothing is switched. The one-time move of every live
root at core start is done (it ran on the live install) and gone. This is the only
module that knows the old path.

Owns: that copy (part of the Hermes Gateway: it opens and rewrites a copy of Hermes's
board database). Must not: write the board Hermes uses (only the copy, before the
switch), or change a card.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from pathlib import Path

from agos_core.db import sql
from agos_core.hermes_gateway import hermes_db

OLD_DIR = "agos-kanban"
MOVED_DIR = "agos-kanban.moved"
ENV_LINE = "HERMES_KANBAN_HOME="
_COPY = "kanban.db.agos-moving"
# Absolute paths Hermes keeps in the board (kanban_db.py: tasks/task_runs
# workspace_path, task_attachments stored_path).
_PATHS: tuple[tuple[str, str], ...] = (
    ("tasks", "workspace_path"),
    ("task_runs", "workspace_path"),
    ("task_attachments", "stored_path"),
)


class MoveError(RuntimeError):
    pass


def _has_line(env: Path) -> bool:
    return any(line.startswith(ENV_LINE) for line in env.read_text().splitlines())


def forget_line(env: Path) -> None:
    """The old pin leaves the .env (Hermes's default board home applies)."""
    from agos_core.engine import envfile

    if env.is_file() and _has_line(env):
        envfile.rewrite(env, (ENV_LINE,), [])


def move_board(old: Path, root: Path, *, keep_source: bool) -> None:
    """The board in `old` (a database and its `kanban` folder) becomes Hermes's
    default board of `root`. `keep_source` copies the files (the old place stays
    as it was) instead of moving them."""
    src, dst = old / "kanban.db", root / "kanban.db"
    if not _free_or_same(src, dst):
        raise MoveError(f"{dst} already holds other cards")
    root.mkdir(parents=True, exist_ok=True)
    copy = root / _COPY
    _drop_db(copy)
    with contextlib.closing(hermes_db.connect_ro(src, timeout=30)) as s:
        with contextlib.closing(sqlite3.connect(copy)) as t:
            s.backup(t)
            _repoint(t, f"{old}/", f"{root}/")
            t.commit()
            t.execute("PRAGMA journal_mode=DELETE")
        before = counts(s)
    after = _counts_of(copy)
    if before != after:
        _drop_db(copy)
        raise MoveError(f"row counts differ after the copy: {before} != {after}")
    _drop_db(dst)
    copy.replace(dst)
    _place_files(old, root, keep_source=keep_source)
    if not keep_source:
        target = root / MOVED_DIR
        n = 1
        while target.exists():
            n += 1
            target = root / f"{MOVED_DIR}.{n}"
        old.rename(target)


def counts(db: sqlite3.Connection) -> dict[str, int]:
    """Rows in each of the board's tables (cards, runs, comments, events, links,
    attachments, notify subscriptions)."""
    names = [
        str(r[0])
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    # The names come from Hermes's board file, which its gateway can write: quoted
    # as SQL identifiers ("" inside), never pasted as they are.
    return {
        n: int(db.execute(sql.text("SELECT COUNT(*) FROM {t}", t=sql.quoted(n))).fetchone()[0])
        for n in names
    }


def _counts_of(path: Path) -> dict[str, int]:
    with contextlib.closing(hermes_db.connect_ro(path, timeout=30)) as db:
        return counts(db)


def _free_or_same(src: Path, dst: Path) -> bool:
    """Hermes's board of the root has no card yet, or holds exactly the old board's
    cards (a move cut short after the switch)."""
    if not dst.is_file():
        return True
    try:
        theirs = _card_ids(dst)
        if not theirs:
            return True
        return src.is_file() and theirs == _card_ids(src)
    except sqlite3.Error:
        return False


def _card_ids(path: Path) -> set[str]:
    with contextlib.closing(hermes_db.connect_ro(path, timeout=30)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name = 'tasks'").fetchone():
            return set()
        return {str(r[0]) for r in db.execute("SELECT id FROM tasks")}


def _repoint(db: sqlite3.Connection, old: str, new: str) -> None:
    like = old.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    for table, column in _PATHS:
        cols = {
            str(r[1]) for r in db.execute(sql.text("PRAGMA table_info({t})", t=sql.quoted(table)))
        }
        if column in cols:
            db.execute(
                sql.text(
                    "UPDATE {t} SET {c} = ? || substr({c}, ?) WHERE {c} LIKE ? ESCAPE '\\'",
                    t=sql.quoted(table),
                    c=sql.quoted(column),
                ),
                (new, len(old) + 1, like),
            )


def _drop_db(path: Path) -> None:
    for extra in ("", "-wal", "-shm", "-journal"):
        path.with_name(path.name + extra).unlink(missing_ok=True)


def _place_files(old: Path, root: Path, *, keep_source: bool) -> None:
    """Everything besides the database (the `kanban` folder, Hermes's small marker
    files) into the root; what is already there is kept."""
    for item in sorted(old.iterdir()):
        if item.name.startswith("kanban.db") or item.name.endswith(".lock"):
            continue
        _merge(item, root / item.name, keep_source=keep_source)


def _merge(src: Path, dst: Path, *, keep_source: bool) -> None:
    if src.is_dir() and not src.is_symlink():
        if dst.exists() and not dst.is_dir():
            return
        if not dst.exists():
            if keep_source:
                shutil.copytree(src, dst, symlinks=True)
            else:
                src.rename(dst)
            return
        for child in sorted(src.iterdir()):
            if not child.name.endswith(".lock"):
                _merge(child, dst / child.name, keep_source=keep_source)
        return
    if dst.exists() or dst.is_symlink():
        return
    if keep_source:
        shutil.copy2(src, dst, follow_symlinks=False)
    else:
        src.rename(dst)
