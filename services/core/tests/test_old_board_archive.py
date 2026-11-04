"""The old board's last tables go: archived to a readable file first, the tables
that pointed at them rebuilt without the links, every other row kept."""

import json
import sqlite3
from pathlib import Path

from agos_core.db import connection
from agos_core.db.migrations import MIGRATIONS


def _at(db: sqlite3.Connection, version: int) -> None:
    for index, sql in enumerate(MIGRATIONS[:version], start=1):
        for statement in connection._split(sql):
            db.execute(statement)
        db.execute(f"PRAGMA user_version = {index}")


def _add(db: sqlite3.Connection, table: str, **values: object) -> None:
    """A row with these values; other required columns get a plain filler."""
    for _cid, name, kind, notnull, default, pk in db.execute(f"PRAGMA table_info({table})"):
        if name in values or pk or not notnull or default is not None:
            continue
        values[name] = 0 if "INT" in str(kind).upper() else "{}"
    cols = ", ".join(values)
    marks = ", ".join("?" * len(values))
    db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))


def test_the_old_board_is_archived_then_its_tables_go(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "system").mkdir(parents=True)
    (root / "workspaces" / "argan" / "files").mkdir(parents=True)
    file = root / "system" / "agos.db"
    last = len(MIGRATIONS)
    # The database as it was just before the archive migration.
    before = next(i for i, sql in enumerate(MIGRATIONS) if "archive-old-board" in sql)
    db = sqlite3.connect(file, isolation_level=None)
    db.execute("PRAGMA foreign_keys = ON")
    _at(db, before)
    now = "2026-10-01T10:00:00+00:00"
    _add(db, "workspaces", id="argan", name="Argan", created_at=now, updated_at=now)
    _add(
        db,
        "tasks",
        id=7,
        workspace_id="argan",
        title="Old task",
        status="complete",
        autonomy="decide",
        created_at=now,
        updated_at=now,
    )
    _add(
        db,
        "chats",
        id=1,
        workspace_id="argan",
        title="General",
        channel="web",
        created_at=now,
        updated_at=now,
    )
    _add(db, "messages", id=1, chat_id=1, author="owner", body="hello", created_at=now)
    _add(db, "messages", id=2, task_id=7, author="agent", body="task chat line", created_at=now)
    _add(
        db,
        "activity",
        workspace_id="argan",
        task_id=7,
        kind="task.done",
        text="Old task done",
        created_at=now,
    )
    db.close()

    opened = connection.open_database(file)
    assert opened.execute("PRAGMA user_version").fetchone()[0] == last
    tables = {r[0] for r in opened.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tasks" not in tables and "plans" not in tables
    # The chat's own line was an old copy (Hermes holds a chat's words since): kept in
    # the leftovers file when its copy went (db/leftovers.py).
    assert [r["body"] for r in opened.execute("SELECT body FROM messages")] == []
    archive = root / "workspaces" / "argan" / "files" / "archive"
    [kept] = list(archive.glob("leftovers-*.json"))
    assert [m["body"] for m in json.loads(kept.read_text())["messages"]] == ["hello"]
    # The old engine's feed line went to the history archive (a later migration).
    assert opened.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 0
    assert opened.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert opened.execute("PRAGMA foreign_key_check").fetchall() == []
    # A new chat message still works (its links are right).
    opened.execute(
        "INSERT INTO message_rows (chat_id, author, body, created_at) VALUES (1, 'owner', 'x', ?)",
        (now,),
    )
    (kept,) = (root / "workspaces" / "argan" / "files" / "archive").glob("old-board-*.json")
    data = json.loads(kept.read_text())
    assert [t["title"] for t in data["tasks"]] == ["Old task"]
    assert [m["body"] for m in data["task_messages"]] == ["task chat line"]
    assert kept.stat().st_mode & 0o777 == 0o600
    (history,) = (root / "workspaces" / "argan" / "files" / "archive").glob("history-*.json")
    old = json.loads(history.read_text())
    assert [a["text"] for a in old["activity"]] == ["Old task done"]
