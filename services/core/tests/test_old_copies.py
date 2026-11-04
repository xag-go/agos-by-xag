"""Step 32 (925047d area 2: C2, C5, C6, the unregistered keys): the last old copies
of Hermes data in AGOS's data folder go once (migration 122, db/old_copies.py):
moved into the backups folder, never deleted; a second start writes nothing."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agos_core.db import connection, ownership
from agos_core.db.connection import _migrate, open_database
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.old_copies import MARK

AT = "2026-10-01T00:00:00+00:00"


def _insert(db: sqlite3.Connection, table: str, **given: Any) -> int:
    """A row with `given`, every other required column filled with a plain value."""
    values = dict(given)
    for _, name, kind, notnull, default, pk in db.execute(f"PRAGMA table_info({table})"):
        if name in values or pk or not notnull or default is not None:
            continue
        values[name] = 0 if "INT" in str(kind).upper() else AT if name.endswith("_at") else "x"
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cursor = db.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    return int(cursor.lastrowid or 0)


OWN = {
    "own": [
        {"kind": "tool", "title": "Tool describe", "detail": "{...} → {...}"},
        {"kind": "approval", "title": "Run rm?", "status": "done"},
    ]
}


@pytest.fixture
def old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A data folder as the live install has it, at the migration before 122."""
    data = tmp_path / "agos-data"
    monkeypatch.delenv("AGOS_BACKUP_DIR", raising=False)
    last = next(i for i, m in enumerate(MIGRATIONS) if MARK in m)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:last])
    db = open_database(data / "system" / "agos.db")
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    _insert(db, "workspaces", id="cc")
    ids = {}
    for kind in ("chat", "dm", "group"):
        chat = _insert(
            db, "chats", workspace_id="cc", kind=kind, hermes_key=f"k-{kind}", channel="web"
        )
        ids[kind] = _insert(
            db,
            "chat_turns",
            chat_id=chat,
            workspace_id="cc",
            status="completed",
            asked_up_to=0,
            activity=json.dumps(OWN),
            via="hermes",
        )
    for key in (
        "chats.words_in_hermes",
        "telegram.menus",
        "tools.default_on",
        "kanban.seen.cc",
        "kanban.asked.1658",
        "tabs",
    ):
        db.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)", (key, "1", AT)
        )
    hook_only = _insert(
        db, "automations", workspace_id="cc", name="", file="a.md", schedule="", enabled=1
    )
    refused = _insert(
        db,
        "automations",
        workspace_id="cc",
        name="",
        file="b.md",
        schedule="",
        enabled=1,
        sync_error="Hermes said no",
    )
    system = data / "system"
    (system / "MEMORY.marketing.bak-1790964677").write_text("old memory")
    (system / "before-one-copy-20261002-211150" / "library-skills").mkdir(parents=True)
    (system / "before-one-copy-20261002-211150" / "xag.db").write_text("old")
    (data / "agos.db").touch()
    return {"db": db, "data": data, "turns": ids, "hook_only": hook_only, "refused": refused}


def test_the_old_copies_go_once_into_the_backups_folder(old: dict[str, Any]) -> None:
    db, data = old["db"], old["data"]
    stray = [
        "chats.words_in_hermes",
        "kanban.asked.1658",
        "kanban.seen.cc",
        "telegram.menus",
        "tools.default_on",
    ]
    assert ownership.unregistered(db) == stray
    _migrate(db, data)

    # The keys no code reads: gone from app_settings, kept in the backups folder.
    assert ownership.unregistered(db) == []
    assert db.execute("SELECT key FROM app_settings WHERE key = 'tabs'").fetchone()
    moved = next((data.parent / "agos-backups").glob("old-copies-*"))
    rows = json.loads((moved / "rows.json").read_text())
    assert sorted(r["key"] for r in rows["app_settings"]) == stray
    # A plain chat's and a DM's whole tool steps: Hermes's; only the approval stays.
    for kind in ("chat", "dm"):
        held = db.execute(
            "SELECT activity FROM chat_turns WHERE id = ?", (old["turns"][kind],)
        ).fetchone()[0]
        assert json.loads(held) == {"kept": [OWN["own"][1]]}, kind
    assert {r["id"] for r in rows["chat_turns"]} == {old["turns"]["chat"], old["turns"]["dm"]}
    # A group chat's stay (Hermes prunes a hosted room's log).
    group = db.execute(
        "SELECT activity FROM chat_turns WHERE id = ?", (old["turns"]["group"],)
    ).fetchone()[0]
    assert json.loads(group) == OWN
    # A webhook-only automation's on/off is its Hermes route's: no copy; a refused
    # change still waits in AGOS's row.
    on = dict(db.execute("SELECT id, enabled FROM automations").fetchall())
    assert on == {old["hook_only"]: 0, old["refused"]: 1}
    # The hand-made copies: moved, not deleted.
    system = data / "system"
    assert not list(system.glob("MEMORY.*")) and not list(system.glob("before-one-copy-*"))
    assert not (data / "agos.db").exists()
    assert (moved / "system/MEMORY.marketing.bak-1790964677").read_text() == "old memory"
    assert (moved / "system/before-one-copy-20261002-211150/xag.db").read_text() == "old"
    assert (moved / "agos.db").is_file()
    assert (system / "agos.db").is_file()  # the real database stays

    # Once: a later start moves and writes nothing.
    before = sorted(p.relative_to(moved) for p in moved.rglob("*"))
    db.execute("PRAGMA user_version = ?".replace("?", str(len(MIGRATIONS) - 1)))
    _migrate(db, data)
    assert sorted(p.relative_to(moved) for p in moved.rglob("*")) == before
    assert len(list((data.parent / "agos-backups").iterdir())) == 1


def test_a_failed_move_drops_nothing(old: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    db, data = old["db"], old["data"]
    blocked = data.parent / "blocked"
    blocked.write_text("a file, not a folder")
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(blocked))
    with pytest.raises(OSError):
        _migrate(db, data)
    assert len(ownership.unregistered(db)) == 5
    assert (data / "system" / "MEMORY.marketing.bak-1790964677").is_file()


def test_the_registry_check_reads_a_live_database() -> None:
    """With AGOS_LIVE_DB (a copy of a live install's agos.db, read only), every
    app_settings key it holds is registered: a key no code names shows here."""
    import os

    live = os.environ.get("AGOS_LIVE_DB")
    if not live:
        pytest.skip("no AGOS_LIVE_DB given")
    db = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    assert ownership.unregistered(db) == []
