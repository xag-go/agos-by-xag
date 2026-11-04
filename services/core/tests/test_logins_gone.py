"""Migration 141: AGOS has no login any more. The owner's password, the sessions,
the failed sign-ins and the human members go; the owner's name is kept as the plain
owner.name setting; members' chats go to the trash; every other row stays."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_old_copies import _insert

from agos_core.db import connection
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.connection import _migrate, open_database
from agos_core.db.logins_gone import MARK
from agos_core.db.migrations import MIGRATIONS

AT = "2026-10-01T00:00:00.000Z"
GONE = {"owner", "sessions", "login_failures", "members", "member_workspaces"}


def _tables(db: sqlite3.Connection) -> set[str]:
    return {str(r[0]) for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _chat(db: sqlite3.Connection, key: str, **extra: object) -> int:
    return _insert(db, "chats", workspace_id="cc", channel="web", hermes_key=key, **extra)


def _before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, name_set: str | None) -> Path:
    """A database as the live install has it, one migration before 141."""
    mark = next(i for i, m in enumerate(MIGRATIONS) if MARK in m)
    assert mark == 140, "migration 141 is the one that drops the logins"
    file = tmp_path / "agos.db"
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:mark])
    db = open_database(file)
    _insert(db, "workspaces", id="cc")
    db.execute(
        "INSERT INTO owner (id, name, password_hash, created_at, updated_at) "
        "VALUES (1, '  Sara   A ', 'scrypt$x', ?, ?)",
        (AT, AT),
    )
    if name_set is not None:
        set_setting(db, "owner.name", name_set)
    db.execute(
        "INSERT INTO members (id, username, name, created_at, updated_at) "
        "VALUES (7, 'omar', 'Omar', ?, ?)",
        (AT, AT),
    )
    db.execute("INSERT INTO member_workspaces (member_id, workspace_id) VALUES (7, 'cc')")
    for token, member in (("t-owner", None), ("t-member", 7)):
        db.execute(
            "INSERT INTO sessions (token_hash, created_at, last_seen_at, expires_at, member_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, AT, AT, AT, member),
        )
    db.execute("INSERT INTO login_failures (created_at) VALUES (?)", (AT,))
    mine = _chat(db, "k-owner")
    member = _chat(db, "k-member", member_id=7)
    former = _chat(db, "k-former", former_member="Ali")
    dm = _chat(db, "k-dm", kind="dm", agent="writer")
    card = _chat(db, "k-card", kanban_card="t_1", agent="writer")
    _insert(db, "chat_turns", chat_id=mine, workspace_id="cc", status="completed")
    db.close()
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    assert (mine, member, former, dm, card) == (1, 2, 3, 4, 5)
    return file


def test_the_logins_go_and_everything_else_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = open_database(_before(tmp_path, monkeypatch, name_set=None))
    assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert not GONE & _tables(db)
    columns = {r[1] for r in db.execute("PRAGMA table_info(chats)")}
    assert not {"member_id", "former_member"} & columns
    # His name is kept, as the plain setting Settings → General shows.
    assert get_setting(db, "owner.name", None) == "Sara A"
    hidden = {
        int(r["id"]): r["deleted_at"] is not None
        for r in db.execute("SELECT id, deleted_at FROM chats ORDER BY id")
    }
    # The members' chats go to the trash; his chats, DMs and card chats stay.
    assert hidden == {1: False, 2: True, 3: True, 4: False, 5: False}
    assert db.execute("SELECT COUNT(*) FROM chat_turns").fetchone()[0] == 1
    assert db.execute("PRAGMA foreign_key_check").fetchone() is None
    indexes = {r[1] for r in db.execute("PRAGMA index_list(chats)")}
    assert {"chats_by_hermes_key", "chats_one_dm", "chats_kanban_card"} <= indexes
    with pytest.raises(sqlite3.IntegrityError):
        _chat(db, "k-dm-2", kind="dm", agent="writer")  # still one DM per agent
    # A second run of the last migration (an old copy replayed) changes nothing.
    set_setting(db, "owner.name", "Sara B")
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) - 1}")
    _migrate(db)
    assert get_setting(db, "owner.name", None) == "Sara B"
    assert not GONE & _tables(db)
    assert {r[1] for r in db.execute("PRAGMA table_info(chats)")} == columns


@pytest.mark.parametrize(("saved", "kept"), [("Sam", "Sam"), ("", "Sara A")])
def test_a_name_he_set_himself_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saved: str, kept: str
) -> None:
    """An empty saved name meant "my account's name": it becomes that name."""
    db = open_database(_before(tmp_path, monkeypatch, name_set=saved))
    assert get_setting(db, "owner.name", None) == kept
