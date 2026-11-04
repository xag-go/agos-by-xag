import shutil
import sqlite3
from pathlib import Path

import pytest

from agos_core.actions.services.chat.view import get_chat
from agos_core.db.activity import add_activity
from agos_core.db.app_settings import set_setting
from agos_core.db.automations import insert_automation, list_automations, row
from agos_core.db.chats import add_chat_message, insert_chat
from agos_core.db.connection import NewerDatabaseError, open_database, transaction
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.records import AddedFolder
from agos_core.db.workspaces import (
    drop_legacy_folders,
    get_workspace,
    insert_workspace,
    legacy_folders,
    list_workspaces,
    mark_deleted,
    purge_deleted,
    set_archived,
    workspace_id_taken,
)
from agos_core.domain.models import ModelSelection

MODEL = ModelSelection(provider="claude", mode="cli", model="claude-sonnet-5", effort="medium")


@pytest.fixture
def db() -> sqlite3.Connection:
    connection = open_database(":memory:")
    for wid in ("investor", "ecommerce"):
        insert_workspace(
            connection,
            workspace_id=wid,
            name=wid,
            description="",
        )
    return connection


def test_file_is_private_and_newer_versions_refused(tmp_path: Path) -> None:
    file = tmp_path / "system" / "agos.db"
    open_database(file).close()
    assert file.stat().st_mode & 0o777 == 0o600
    again = open_database(file)
    assert again.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    again.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    again.close()
    with pytest.raises(NewerDatabaseError):
        open_database(file)


def test_opens_a_database_made_by_the_typescript_version(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / "agos-data" / "system" / "agos.db"
    if not source.exists():
        pytest.skip("no development database on this machine")
    copy = tmp_path / "agos.db"
    shutil.copy(source, copy)
    db = open_database(copy)
    for workspace in list_workspaces(db, include_archived=True):
        list_activity(db, workspace.id)


def list_activity(db: sqlite3.Connection, workspace_id: str) -> list[str]:
    """The workspace's audit trail, newest first."""
    return [
        str(r[0])
        for r in db.execute(
            "SELECT text FROM activity WHERE workspace_id = ? ORDER BY id DESC", (workspace_id,)
        )
    ]


def test_transactions_nest(db: sqlite3.Connection) -> None:
    def row() -> None:
        add_activity(db, "investor", kind="a", text="x")

    with pytest.raises(RuntimeError), transaction(db):
        row()
        with transaction(db):
            row()
        raise RuntimeError("boom")
    assert list_activity(db, "investor") == []
    with transaction(db):
        row()
        try:
            with transaction(db):
                row()
                raise RuntimeError("inner")
        except RuntimeError:
            pass
    assert len(list_activity(db, "investor")) == 1


def test_workspaces(db: sqlite3.Connection) -> None:
    assert [w.id for w in list_workspaces(db)] == ["investor", "ecommerce"]
    set_archived(db, "ecommerce", True)
    assert [w.id for w in list_workspaces(db)] == ["investor"]
    mark_deleted(db, "investor", "investor--1")
    assert get_workspace(db, "investor") is None
    assert workspace_id_taken(db, "investor")
    purge_deleted(db, "investor")
    assert not workspace_id_taken(db, "investor")
    assert get_workspace(db, "../system") is None
    with pytest.raises(ValueError):
        insert_workspace(db, workspace_id="Bad Id", name="x", description="")


def test_old_added_folders_are_only_read_then_dropped(db: sqlite3.Connection) -> None:
    """AGOS's old folder rows (before Hermes's docker_volumes was the one list)
    are read per workspace until the move, then dropped; nothing writes them."""
    set_setting(
        db,
        "folders.move.investor",
        [{"name": "reports", "host_path": "/data/reports", "access": "read"}],
    )
    assert legacy_folders(db, "investor") == [
        AddedFolder(name="reports", host_path="/data/reports", access="read")
    ]
    assert legacy_folders(db, "ecommerce") == []
    assert drop_legacy_folders(db, "ecommerce") == 0
    assert drop_legacy_folders(db, "investor") == 1
    assert legacy_folders(db, "investor") == []


def test_a_purged_workspace_takes_every_key_of_itself_and_its_chats(
    db: sqlite3.Connection,
) -> None:
    """ownership.WILDCARD_IDS drives the purge: every `*` key of the workspace and
    of its chats goes with it; another workspace's keys stay."""
    chat = insert_chat(db, workspace_id="investor", title="t", channel="web")
    keep = insert_chat(db, workspace_id="ecommerce", title="t", channel="web")
    set_setting(db, "playbooks.written.investor", {"a": "h"})
    set_setting(db, "office.investor", {"zoom": 1})
    set_setting(db, "composio_key:investor", "sealed")
    set_setting(db, f"hermes.effort.agos:{chat}", "high")
    set_setting(db, f"group.next_to.{chat}", "mentor")
    set_setting(db, "playbooks.written.ecommerce", {"b": "h"})
    set_setting(db, f"hermes.effort.agos:{keep}", "low")
    mark_deleted(db, "investor", "investor--1")
    purge_deleted(db, "investor")
    keys = {str(r["key"]) for r in db.execute("SELECT key FROM app_settings").fetchall()}
    assert not any("investor" in k or str(chat) in k for k in keys)
    assert "playbooks.written.ecommerce" in keys and f"hermes.effort.agos:{keep}" in keys


def test_keys_of_gone_workspaces_and_chats_are_swept_to_the_backups_folder(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What older purges left behind (ownership.unregistered can't see it: the
    prefixes are registered) moves once into the backups folder, values kept."""
    from agos_core.db import orphan_keys

    monkeypatch.delenv("AGOS_BACKUP_DIR", raising=False)
    set_setting(db, "playbooks.written.gone-ws", {"a": "h"})
    set_setting(db, "telegram.groups.gone-ws", {"-100": "Team"})
    set_setting(db, "hermes.effort.agos:12345", "high")  # its chat is gone too
    set_setting(db, "office.investor", {"keep": True})  # a live workspace's: stays
    set_setting(db, "hermes_contract_told:x", True)  # global: never an orphan
    data_root = tmp_path / "agos-data"
    data_root.mkdir()
    assert orphan_keys.sweep(db, data_root) == 3
    keys = {str(r["key"]) for r in db.execute("SELECT key FROM app_settings").fetchall()}
    assert "office.investor" in keys and "hermes_contract_told:x" in keys
    assert not any("gone-ws" in k or "12345" in k for k in keys)
    files = list((tmp_path / "agos-backups").glob("old-copies-*/app-settings-orphans-*.json"))
    assert len(files) == 1 and "gone-ws" in files[0].read_text()
    assert orphan_keys.sweep(db, data_root) == 0  # nothing left: nothing written


def test_an_old_database_keeps_its_unmoved_folders_until_hermes_has_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An old database (or an old backup being restored) still has workspace_folders
    rows: the step-26 migration keeps them under folders.move.<ws> and drops the table."""
    from agos_core.db import connection

    step = next(i for i, m in enumerate(MIGRATIONS) if "DROP TABLE workspace_folders" in m)
    file = tmp_path / "old.db"
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:step])
    old = open_database(file)
    old.execute(  # the old schema: the name still had its column
        "INSERT INTO workspaces (id, name, created_at, updated_at)"
        " VALUES ('investor', 'Investor', 'now', 'now')"
    )
    for name in ("zeta", "alpha"):
        old.execute(
            "INSERT INTO workspace_folders (workspace_id, name, host_path, access, created_at)"
            " VALUES ('investor', ?, ?, 'read', '2026-01-01')",
            (name, f"/data/{name}"),
        )
    old.close()
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    db = open_database(file)
    gone = db.execute("SELECT name FROM sqlite_master WHERE name = 'workspace_folders'")
    assert gone.fetchone() is None
    assert [f.name for f in legacy_folders(db, "investor")] == ["alpha", "zeta"]
    assert legacy_folders(db, "investor")[0].host_path == "/data/alpha"
    db.close()


def test_a_voice_notes_words_are_kept_only_on_a_room_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Hermes chat's voice note is heard and kept by Hermes (its message): AGOS
    never writes its words, and an old copy goes with the step-27 migration. A room
    line (AGOS's own line) keeps them."""
    from agos_core.db import connection
    from agos_core.db.chat_attachments import add_attachment, set_transcript

    step = next(i for i, m in enumerate(MIGRATIONS) if "Hermes chat's voice words" in m)
    file = tmp_path / "old.db"
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:step])
    old = open_database(file)
    old.execute(  # the old schema: the name still had its column
        "INSERT INTO workspaces (id, name, created_at, updated_at)"
        " VALUES ('investor', 'Investor', 'now', 'now')"
    )
    cid = insert_chat(old, workspace_id="investor", title="Research", channel="web")
    line = add_chat_message(old, "investor", cid, "owner", "hi")

    def attach(message_id: int | None, inbox_id: int | None) -> int:
        return add_attachment(
            old,
            message_id,
            kind="audio",
            name="a.ogg",
            mime="audio/ogg",
            size=1,
            path="a",
            duration=1.0,
            chat_id=cid,
            inbox_id=inbox_id,
        )

    in_hermes = attach(None, 7)
    on_line = attach(line, None)
    for aid in (in_hermes, on_line):
        old.execute("UPDATE message_attachments SET transcript = 'salam' WHERE id = ?", (aid,))
    old.commit()
    old.close()
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    db = open_database(file)
    words = dict(db.execute("SELECT id, transcript FROM message_attachments").fetchall())
    assert words == {in_hermes: None, on_line: "salam"}
    set_transcript(db, in_hermes, "again")
    set_transcript(db, on_line, "ok")
    words = dict(db.execute("SELECT id, transcript FROM message_attachments").fetchall())
    assert words == {in_hermes: None, on_line: "ok"}
    db.close()


def test_chats_automations_activity(db: sqlite3.Connection) -> None:
    cid = insert_chat(db, workspace_id="investor", title="Research", channel="web")
    assert not add_chat_message(db, "ecommerce", cid, "owner", "hi")
    assert get_chat(db, "ecommerce", cid) is None
    assert add_chat_message(db, "investor", cid, "owner", "hi")
    chat = get_chat(db, "investor", cid)
    assert chat and len(chat.messages) == 1
    aid = insert_automation(
        db,
        "investor",
        name="Brief",
        file="automations/brief.md",
        schedule="0 8 * * *",
        model=MODEL,
    )
    assert row(db, "investor", aid)
    assert row(db, "ecommerce", aid) is None
    assert list_automations(db, "ecommerce") == []
    with pytest.raises(ValueError):
        insert_automation(
            db,
            "investor",
            name="b",
            file="b.md",
            schedule="0 8 * * *\nrm -rf /",
            model=MODEL,
        )
    add_activity(db, "investor", kind="a", text="first")
    add_activity(db, "investor", kind="a", text="second")
    add_activity(db, "ecommerce", kind="a", text="other")
    assert list_activity(db, "investor") == ["second", "first"]


def test_the_leftover_tables_and_columns_go_and_the_rest_stays(tmp_path: Path) -> None:
    """A live database with rows in the tables nothing uses any more: they go (with
    the unused columns), every other row stays."""
    file = tmp_path / "agos.db"
    db = sqlite3.connect(file)
    db.execute("PRAGMA foreign_keys = OFF")
    leftovers = next(
        i for i, m in enumerate(MIGRATIONS) if "DROP TABLE IF EXISTS channel_seen" in m
    )
    for sql in MIGRATIONS[:leftovers]:
        db.executescript(sql)
    db.execute(f"PRAGMA user_version = {leftovers}")
    db.executescript(
        """INSERT INTO workspaces (id, name, created_at, updated_at, identity)
             VALUES ('ws', 'Argan', 'now', 'now', 'Old text');
           INSERT INTO automations (id, workspace_id, name, file, schedule, enabled, created_at,
             updated_at)
             VALUES (1, 'ws', 'Daily', 'daily.md', '', 1, 'now', 'now');
           INSERT INTO automation_runs (id, automation_id, workspace_id, hermes_run_id, result,
             started_at) VALUES (1, 1, 'ws', 'r', 'ok', 'now');
           INSERT INTO automation_proposals (run_id, title) VALUES (1, 'Old card');
           INSERT INTO automation_events (automation_id, workspace_id, delivery, status,
             received_at) VALUES (1, 'ws', 'd', 'started', 'now');
           INSERT INTO channel_connections (id, kind, name, secret, secret_last4, relay, cursor,
             created_at, workspace_id) VALUES (1, 'telegram', 'Bot', '', '1234', 'x', '9',
             'now', 'ws');
           INSERT INTO channel_seen VALUES (1, 'm', 'now');"""
    )
    db.commit()
    db.close()
    db = open_database(file)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not tables & {
        "chat_proposals",
        "automation_proposals",
        "automation_runs",
        "automation_proposed",
        "automation_events",
        "channel_seen",
    }

    def columns(table: str) -> set[str]:
        return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}

    assert "identity" not in columns("workspaces")
    assert not columns("group_rooms") & {"continuations", "recap"}
    assert not columns("channel_connections") & {"relay", "cursor"}
    assert "name" not in columns("workspaces")  # step 28: its Hermes display name
    from agos_core.db.workspaces import name_of

    assert name_of(db, "ws") == "Argan"  # waiting for its Hermes (engine.move_name)
    assert db.execute("SELECT name FROM automations").fetchone()[0] == "Daily"
    assert db.execute("SELECT name FROM channel_connections").fetchone()[0] == "Bot"
