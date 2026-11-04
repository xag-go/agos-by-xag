"""Moving an old board (AGOS's old agos-kanban pin) into Hermes's own default board
of a root (<root>/kanban.db and <root>/kanban), as the root migration does."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agos_core.hermes_gateway import kanban_move

# The tables of Hermes's board (hermes_cli/kanban_db.py SCHEMA), with the columns
# the move touches.
SCHEMA = """
CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT, workspace_path TEXT);
CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
CREATE TABLE task_comments (id INTEGER PRIMARY KEY, task_id TEXT, body TEXT);
CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT);
CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, workspace_path TEXT);
CREATE TABLE task_attachments (id INTEGER PRIMARY KEY, task_id TEXT, stored_path TEXT);
CREATE TABLE kanban_notify_subs (task_id TEXT, platform TEXT, chat_id TEXT);
"""


def _board(folder: Path, cards: list[str]) -> Path:
    """A live-like old board: WAL mode, rows in every table, paths into its folder."""
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    for n, card in enumerate(cards, 1):
        work = folder / "kanban" / "workspaces" / card
        work.mkdir(parents=True, exist_ok=True)
        (work / "notes.md").write_text(card)
        att = folder / "kanban" / "attachments" / card
        att.mkdir(parents=True, exist_ok=True)
        (att / "brief.pdf").write_bytes(b"%PDF")
        db.execute("INSERT INTO tasks VALUES (?, ?, 'todo', ?)", (card, card, str(work)))
        db.execute("INSERT INTO task_runs VALUES (?, ?, ?)", (n, card, str(work)))
        db.execute("INSERT INTO task_comments VALUES (?, ?, 'hi')", (n, card))
        db.execute("INSERT INTO task_events VALUES (?, ?, 'created')", (n, card))
        db.execute(
            "INSERT INTO task_attachments VALUES (?, ?, ?)", (n, card, str(att / "brief.pdf"))
        )
        db.execute("INSERT INTO kanban_notify_subs VALUES (?, 'agos', 'l1')", (card,))
    db.execute("INSERT INTO task_links VALUES (?, ?)", (cards[0], cards[-1]))
    db.commit()
    db.close()  # the WAL may keep rows: the copy must take them
    (folder / "kanban" / "current").write_text("default\n")
    (folder / "kanban" / ".dispatcher.lock").write_text("")
    return folder / "kanban.db"


def _counts(path: Path) -> dict[str, int]:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return kanban_move.counts(db)


def test_nothing_switches_when_the_counts_differ(tmp_path: Path, monkeypatch: Any) -> None:
    old = tmp_path / "shared" / "agos-kanban" / "w1"
    _board(old, ["t_a"])
    root = tmp_path / "roots" / "agos-w1"
    real = kanban_move._counts_of
    monkeypatch.setattr(kanban_move, "_counts_of", lambda p: {**real(p), "tasks": 0})

    with pytest.raises(kanban_move.MoveError):
        kanban_move.move_board(old, root, keep_source=False)

    assert not (root / "kanban.db").exists()
    assert (old / "kanban.db").is_file()


def test_the_start_up_move_of_every_board_is_gone() -> None:
    """Guard: the live boards were moved once at core start; that move is gone and
    the core no longer looks for an old pin at start."""
    from agos_core.actions.services.system import startup
    from agos_core.api import app

    assert not hasattr(kanban_move, "move_all") and not hasattr(kanban_move, "move_root")
    for start in (app, startup):  # the app's wiring and its start sequence
        assert "kanban_move" not in Path(str(start.__file__)).read_text()


def test_a_copy_keeps_the_old_board_as_it_was(tmp_path: Path) -> None:
    """migrate_root: the shared home's board is copied into the new root, never moved."""
    old = tmp_path / "shared" / "agos-kanban" / "w1"
    old_db = _board(old, ["t_a"])
    root = tmp_path / "roots" / "agos-w1"

    kanban_move.move_board(old, root, keep_source=True)

    assert _counts(root / "kanban.db") == _counts(old_db)
    assert (old / "kanban" / "workspaces" / "t_a").is_dir()
    assert (root / "kanban" / "workspaces" / "t_a").is_dir()
    with contextlib.closing(sqlite3.connect(root / "kanban.db")) as db:
        (path,) = db.execute("SELECT workspace_path FROM tasks").fetchone()
    assert path == str(root / "kanban" / "workspaces" / "t_a")
    with pytest.raises(kanban_move.MoveError):
        _board(tmp_path / "other", ["t_z"])
        kanban_move.move_board(tmp_path / "other", root, keep_source=True)


def test_only_the_move_knows_agoss_old_board_pin() -> None:
    """Guard: Hermes's own board path is the one every reader uses (the Board page,
    automations, token watch, the Log, the plugin). Only the move (and the root
    migration that copies the shared home's board) may name the old pin."""
    src = Path(kanban_move.__file__).resolve().parents[1]
    allowed = {src / "hermes_gateway" / "kanban_move.py", src / "migrate_root.py"}
    found = []
    for path in src.rglob("*.py"):
        text = path.read_text()
        for word in ("HERMES_KANBAN_HOME", "HERMES_KANBAN_DB", '"agos-kanban"', "kanban_home("):
            if word in text and path not in allowed:
                found.append(f"{path.relative_to(src)}: {word}")
    assert found == []
