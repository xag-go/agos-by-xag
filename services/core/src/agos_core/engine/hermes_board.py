"""A Kanban card read straight from Hermes's own board database (read only), the
way Hermes's own `hermes kanban show <id> --json` and `hermes kanban attachments
<id> --json` read it.

Opening a card used to start Hermes twice (`show`, then `attachments`: well over a
second together, every open). Both commands only read the board's database, so
AGOS reads that database itself, read only, with Hermes's own queries and
conversions (hermes_cli/kanban_db.py get_task + Task.from_row, list_comments,
list_events, parent_ids / child_ids, latest_summary, list_attachments;
hermes_cli/kanban.py _cmd_show / _cmd_attachments; hermes_cli/kanban_output.py
_task_to_dict / _obj_dict), and gives what the CLI prints for every field AGOS
shows. Every query is one Hermes itself runs, on one of its indexes (the task's
primary key, idx_comments_task, idx_events_task, idx_links_child /
idx_links_parent, idx_runs_task, idx_attachments_task).

Whatever this can't read the way Hermes's CLI would raises `Unread`, and the
caller asks Hermes's CLI as before: no board file yet (the CLI makes it), another
board chosen with `hermes kanban boards switch` (`<root>/kanban/current`), a root
inside ~/.hermes (Hermes's board would be the shared one), a table or column this
Hermes doesn't have, any SQLite error. Nothing is written and nothing is kept.
The writes (comment, attach, block...) stay on Hermes's CLI. The tables and columns
read are on engine/hermes_contract.py; tests/test_kanban_direct_live.py builds a
board with the real Hermes CLI and checks this gives what the CLI prints.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

# What AGOS shows of a card (kanban_board._card, card()): the task fields of the
# CLI's JSON (hermes_cli/kanban_output.py _TASK_DICT_FIELDS) it reads.
TASK_FIELDS = (
    "id",
    "title",
    "body",
    "assignee",
    "status",
    "created_by",
    "created_at",
    "started_at",
    "completed_at",
    "model_override",
    # Whether Mark done needs his words first (kanban_board.done_needs_summary).
    "result",
)
# hermes_cli/kanban_output.py _ATTACHMENT_FIELDS (what `attachments --json` prints).
ATTACHMENT_FIELDS = (
    "id",
    "filename",
    "content_type",
    "size",
    "uploaded_by",
    "stored_path",
    "created_at",
)


# Event names Hermes's CLI renames in the board on every start before it reads it
# (hermes_cli/kanban_db_connect.py _migrate_add_optional_columns): a card that
# still has one is left to the CLI.
RENAMED_EVENT_KINDS = frozenset({"ready", "priority", "spawn_auto_blocked"})


class Unread(Exception):
    """The board can't be read here the way Hermes's CLI reads it: ask the CLI."""


def board(root: Path, home: Path) -> Path:
    """The database Hermes's CLI reads for this root's board (its default board,
    hermes_cli/kanban_db.py kanban_db_path), or Unread."""
    try:
        resolved = root.resolve()
        if resolved.is_relative_to((home / ".hermes").resolve()):
            raise Unread("a root inside ~/.hermes: Hermes's board is the shared root's")
        if (root / "kanban" / "current").exists():
            raise Unread("another board is chosen (hermes kanban boards switch)")
    except OSError as error:
        raise Unread(str(error)) from error
    db = root / "kanban.db"
    if not db.is_file():
        raise Unread("no board yet (Hermes's CLI makes it)")
    return db


def _text(value: Any) -> Any:
    """hermes_cli/kanban_db.py _lossy_text: bytes as text, bad UTF-8 replaced."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _epoch(value: Any) -> int | None:
    """hermes_cli/kanban_db.py _to_epoch."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except (ValueError, OSError):
        return None


def _json_or_none(value: Any) -> Any:
    """hermes_cli/kanban_db.py _json_or (default None)."""
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001 - Hermes's own: any decode failure is None
        return None


def _get(row: sqlite3.Row, col: str, default: Any = None) -> Any:
    """hermes_cli/kanban_db.py _row_get: a column this board doesn't have is `default`."""
    return row[col] if col in row.keys() else default  # noqa: SIM118 - `in row` reads values


@contextlib.contextmanager
def _open(db: Path) -> Iterator[sqlite3.Connection]:
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error as error:
        raise Unread(str(error)) from error
    try:
        # Hermes's own connection settings (kanban_db_connect.py _open_configured).
        conn.row_factory = sqlite3.Row
        conn.text_factory = _text
        yield conn
    except (sqlite3.Error, KeyError, IndexError, TypeError, ValueError) as error:
        raise Unread(f"{type(error).__name__}: {error}") from error
    finally:
        conn.close()


def _task(row: sqlite3.Row) -> dict[str, Any]:
    """Task.from_row + _task_to_dict, for TASK_FIELDS."""
    out = {col: _text(row[col]) for col in ("id", "title", "body", "assignee", "status")}
    out["created_by"] = _text(row["created_by"])
    for col in ("created_at", "started_at", "completed_at"):
        out[col] = _epoch(_text(_get(row, col)))
    out["model_override"] = _text(_get(row, "model_override")) or None
    out["result"] = _text(_get(row, "result"))  # one of _TASK_OPTIONAL_COLUMNS
    return out


def show(db: Path, card_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """What `hermes kanban show <card_id> --json` prints (the fields AGOS reads: task
    TASK_FIELDS, latest_summary, parents, children, comments, events), and the
    card's goal_mode / block_kind (what kanban_board._extra adds, from the same
    row). None: no such card (the CLI's "no such task")."""
    with _open(db) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        task = _task(row)
        extra = {"goal_mode": _get(row, "goal_mode"), "block_kind": _get(row, "block_kind")}
        comments = [
            {
                "author": _text(c["author"]),
                "body": _text(c["body"]),
                "created_at": _epoch(c["created_at"]) or 0,
            }
            for c in conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
                (card_id,),
            )
        ]
        events = [
            {
                "kind": _text(e["kind"]),
                "payload": _json_or_none(_text(e["payload"])),
                "created_at": _epoch(e["created_at"]) or 0,
                "run_id": int(run) if (run := _get(e, "run_id")) is not None else None,
            }
            for e in conn.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY created_at ASC, id ASC",
                (card_id,),
            )
        ]
        if any(e["kind"] in RENAMED_EVENT_KINDS for e in events):
            raise Unread("old event names: Hermes's CLI renames them first")
        parents = [
            r["parent_id"]
            for r in conn.execute(
                "SELECT parent_id FROM task_links WHERE child_id = ? ORDER BY parent_id",
                (card_id,),
            )
        ]
        children = [
            r["child_id"]
            for r in conn.execute(
                "SELECT child_id FROM task_links WHERE parent_id = ? ORDER BY child_id",
                (card_id,),
            )
        ]
        summary = conn.execute(
            "SELECT summary FROM task_runs "
            "WHERE task_id = ? AND summary IS NOT NULL AND summary != '' "
            "ORDER BY COALESCE(ended_at, started_at) DESC, id DESC LIMIT 1",
            (card_id,),
        ).fetchone()
    shown = {
        "task": task,
        "latest_summary": summary["summary"] if summary else None,
        "parents": parents,
        "children": children,
        "comments": comments,
        "events": events,
    }
    return shown, extra


def attachments(db: Path, card_id: str) -> list[dict[str, Any]] | None:
    """What `hermes kanban attachments <card_id> --json` prints (oldest first);
    None: no such card (the CLI's "no such task")."""
    with _open(db) as conn:
        if conn.execute("SELECT * FROM tasks WHERE id = ?", (card_id,)).fetchone() is None:
            return None
        return [
            _attachment(a)
            for a in conn.execute(
                "SELECT * FROM task_attachments WHERE task_id = ? ORDER BY created_at ASC, id ASC",
                (card_id,),
            )
        ]


def all_attachments(db: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every card's files on the board (the Artifacts page), newest first: the
    attachment rows with their card (`task_id`), the same fields as `attachments`;
    and every card's title. One read of task_attachments and one of tasks (no CLI
    command lists files across cards)."""
    with _open(db) as conn:
        files = [
            {**_attachment(a), "task_id": _text(a["task_id"])}
            for a in conn.execute(
                "SELECT * FROM task_attachments ORDER BY created_at DESC, id DESC"
            )
        ]
        titles = {
            str(_text(t["id"])): str(_text(t["title"]) or "")
            for t in conn.execute("SELECT id, title FROM tasks")
        }
    return files, titles


def _attachment(a: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": a["id"],
        "filename": a["filename"],
        "content_type": a["content_type"],
        "size": a["size"] or 0,
        "uploaded_by": a["uploaded_by"],
        "stored_path": a["stored_path"],
        "created_at": _epoch(a["created_at"]) or 0,
    }
