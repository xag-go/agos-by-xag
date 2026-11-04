"""The old board's history, kept as a readable file before its tables go.

The old task engine is gone: Hermes's Kanban runs the work, and the old tasks were
moved there (finished ones with their last report). What is left of them in AGOS's
database (the tasks, their plans, the task chats' messages) is written once, per
workspace, to `files/archive/old-board-<date>.json` (the workspace's own folder,
like the other archives), then the tables go (a migration marked
`-- agos: archive-old-board`). Nothing is lost; nothing is copied twice.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MARK = "-- agos: archive-old-board"
HISTORY_MARK = "-- agos: archive-history"
# The feed lines of the old engine (its tasks, plans, checks and watchers).
OLD_ACTIVITY = """(task_id IS NOT NULL OR kind LIKE 'plan.%' OR kind LIKE 'check.%'
                   OR kind LIKE 'watcher.%')"""


def _rows(db: sqlite3.Connection, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = db.execute(sql, args)
    names = [d[0] for d in cursor.description or []]
    return [dict(zip(names, row, strict=False)) for row in cursor.fetchall()]


def _has(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def archive(db: sqlite3.Connection, data_root: Path | None) -> list[Path]:
    """Writes each workspace's old board history; returns the files written.
    Raises OSError when a file can't be written (the migration then stops and
    nothing is dropped)."""
    if not _has(db, "tasks"):
        return []
    plans = _has(db, "plans")
    written: list[Path] = []
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    workspaces = [str(r[0]) for r in db.execute("SELECT id FROM workspaces")]
    for workspace_id in workspaces:
        data = {
            "about": (
                "The old AGOS board before Hermes's Kanban took over: its tasks, plans and "
                "task chats, kept for reference. The work itself moved to the Kanban."
            ),
            "tasks": _rows(
                db, "SELECT * FROM tasks WHERE workspace_id = ? ORDER BY id", (workspace_id,)
            ),
            "plans": _rows(
                db, "SELECT * FROM plans WHERE workspace_id = ? ORDER BY id", (workspace_id,)
            )
            if plans
            else [],
            "task_messages": _rows(
                db,
                """SELECT m.* FROM messages m JOIN tasks t ON t.id = m.task_id
                   WHERE t.workspace_id = ? ORDER BY m.id""",
                (workspace_id,),
            ),
        }
        if not (data["tasks"] or data["plans"] or data["task_messages"]):
            continue
        if data_root is None:
            raise OSError("no data folder to keep the old board in")
        folder = data_root / "workspaces" / workspace_id / "files" / "archive"
        if not folder.parent.is_dir():
            folder = data_root / "system" / "old-board" / workspace_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"old-board-{stamp}.json"
        tmp = target.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
        tmp.replace(target)
        written.append(target)
    return written


def _write(data_root: Path | None, workspace_id: str, name: str, data: dict[str, Any]) -> Path:
    if data_root is None:
        raise OSError("no data folder to keep the history in")
    folder = data_root / "workspaces" / workspace_id / "files" / "archive"
    if not folder.parent.is_dir():
        folder = data_root / "system" / "old-board" / workspace_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}-{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
    tmp.replace(target)
    return target


def archive_history(db: sqlite3.Connection, data_root: Path | None) -> list[Path]:
    """The owner's old decisions (now said to Hermes, which keeps them in the
    workspace's learning conversation) and the old engine's feed lines, written
    per workspace to files/archive/history-<date>.json before they go."""
    written: list[Path] = []
    feedback = _has(db, "feedback")
    for (workspace_id,) in db.execute("SELECT id FROM workspaces").fetchall():
        data = {
            "about": (
                "AGOS history kept for reference: the owner's decisions before Hermes held "
                "them, and the feed of the old task engine."
            ),
            "decisions": _rows(
                db, "SELECT * FROM feedback WHERE workspace_id = ? ORDER BY id", (workspace_id,)
            )
            if feedback
            else [],
            "activity": _rows(
                db,
                f"SELECT * FROM activity WHERE workspace_id = ? AND {OLD_ACTIVITY} ORDER BY id",
                (workspace_id,),
            ),
        }
        if data["decisions"] or data["activity"]:
            written.append(_write(data_root, str(workspace_id), "history", data))
    return written
