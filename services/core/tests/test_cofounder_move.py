"""Step 44: the Manager is the Co-Founder. Migration 126 (rows written under the old
name are read under the new one) and the one-time pass over the roots' files
(actions/cofounder_move.py), on data shaped like live's."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_engine_sync import profile_dir
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions, cofounder_move
from agos_core.db import connection, hermes_text
from agos_core.db.app_settings import get_setting
from agos_core.db.migrations import MIGRATIONS
from agos_core.engine import identity

MARK = "-- agos: the Manager is the Co-Founder (step 44)"


def _before(monkeypatch: Any) -> tuple[sqlite3.Connection, int]:
    """A database as live had it right before migration 126."""
    at = next(i for i, m in enumerate(MIGRATIONS) if MARK in m)
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    hermes_text.install(db)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:at])
    connection._migrate(db)
    return db, at


def test_migration_126_renames_the_table_the_key_the_dm_and_the_office_look(
    monkeypatch: Any,
) -> None:
    db, _ = _before(monkeypatch)
    db.execute("INSERT INTO workspaces (id, created_at, updated_at) VALUES ('w', 'x', 'x')")
    db.execute(
        "INSERT INTO chats (workspace_id, kind, title, channel, created_at, updated_at)"
        " VALUES ('w', 'dm', 'Manager', 'web', 'x', 'x')"
    )
    db.execute(
        "INSERT INTO chats (workspace_id, kind, agent, title, channel, created_at, updated_at)"
        " VALUES ('w', 'dm', 'writer', 'Manager', 'web', 'x', 'x')"
    )
    db.execute(
        "INSERT INTO manager_actions (workspace_id, action, title, payload, status, result,"
        " created_at) VALUES ('w', 'update_skill', 'Update skill x', '{}', 'done', ?, 'x')",
        (json.dumps({"before": {"kept_in": "manager-actions-before-step32.json"}}),),
    )
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('manager.actions', '\"ask\"', 'x')"
    )
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('office.w', ?, 'x')",
        (json.dumps({"manager": {"pet": "cat", "colour": "indigo"}, "writer": {"pet": "none"}}),),
    )
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    connection._migrate(db)

    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master")}
    assert "cofounder_actions" in names and "manager_actions" not in names
    assert "cofounder_actions_by_turn" in names and "manager_actions_by_turn" not in names
    row = db.execute("SELECT * FROM cofounder_actions").fetchone()
    assert row["action"] == "update_skill" and row["status"] == "done"
    assert json.loads(row["result"])["before"]["kept_in"] == cofounder_actions.SNAPSHOTS_FILE
    titles = [r["title"] for r in db.execute("SELECT title FROM chats ORDER BY id")]
    assert titles == ["Co-Founder", "Manager"]  # a member's DM title is its own
    assert get_setting(db, "cofounder.actions", None) == "ask"
    assert get_setting(db, "manager.actions", None) is None
    assert get_setting(db, "office.w", {}) == {
        "cofounder": {"pet": "cat", "colour": "indigo"},
        "writer": {"pet": "none"},
    }


def test_migration_126_keeps_a_newer_key_and_runs_on_an_empty_database(monkeypatch: Any) -> None:
    db, _ = _before(monkeypatch)
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('manager.actions', '\"ask\"', 'x')"
    )
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at)"
        " VALUES ('cofounder.actions', '\"direct\"', 'x')"
    )
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    connection._migrate(db)
    assert get_setting(db, "cofounder.actions", None) == "direct"
    assert get_setting(db, "manager.actions", None) is None
    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    hermes_text.install(fresh)
    connection._migrate(fresh)
    assert fresh.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def _old_souls(home: Path, a: str) -> tuple[Path, Path]:
    """The root's and a member's SOUL.md as AGOS wrote them before step 44."""
    root = profile_dir(home, f"agos-{a}") / "SOUL.md"
    member = profile_dir(home, f"agos-{a}--a-writer") / "SOUL.md"
    text = root.read_text()
    assert identity.COFOUNDER_START in text
    root.write_text(
        text.replace(identity.COFOUNDER_START, identity.OLD_LEAD_START)
        .replace(identity.COFOUNDER_END, identity.OLD_LEAD_END)
        .replace("You are the Co-Founder", "You are the Manager")
    )
    member.write_text(member.read_text().replace(identity.LEAD_LINE, identity.OLD_LEAD_LINE))
    assert "Manager" in root.read_text() and "Manager" in member.read_text()
    return root, member


def test_the_roots_files_take_the_new_name_once(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    own = "I am Alpha's own voice."
    r = client.put(f"/workspaces/{a}/identity", json={"identity": own})
    assert r.status_code == 204, r.text
    root, member = _old_souls(home, a)
    backups = home.parent / "agos-backups"
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(backups))
    backups.mkdir(parents=True, exist_ok=True)
    (backups / cofounder_move.OLD_SNAPSHOTS).write_text(json.dumps([{"id": 1, "action": "x"}]))

    counts = cofounder_move.move_old_manager_name(core)
    assert counts == {"souls": 2, "snapshots": 1}
    soul = root.read_text()
    assert "Manager" not in soul and own in soul
    assert "You are the Co-Founder" in identity.cofounder_view(soul)
    assert identity.LEAD_LINE.strip() in member.read_text() and "Manager" not in member.read_text()
    assert not (backups / cofounder_move.OLD_SNAPSHOTS).exists()
    assert json.loads((backups / cofounder_actions.SNAPSHOTS_FILE).read_text()) == [
        {"id": 1, "action": "x"}
    ]

    # Again: nothing to do, nothing rewritten.
    stamps = (root.stat().st_mtime_ns, member.stat().st_mtime_ns)
    assert cofounder_move.move_old_manager_name(core) == {"souls": 0, "snapshots": 0}
    assert (root.stat().st_mtime_ns, member.stat().st_mtime_ns) == stamps


def test_the_snapshot_files_merge_when_both_exist(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    _client, core, _runner, home = env
    backups = home.parent / "agos-backups"
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(backups))
    backups.mkdir(parents=True, exist_ok=True)
    (backups / cofounder_move.OLD_SNAPSHOTS).write_text(json.dumps([{"id": 1}, {"id": 2}]))
    (backups / cofounder_actions.SNAPSHOTS_FILE).write_text(json.dumps([{"id": 2}, {"id": 3}]))
    assert cofounder_move.move_old_manager_name(core)["snapshots"] == 1
    assert json.loads((backups / cofounder_actions.SNAPSHOTS_FILE).read_text()) == [
        {"id": 2},
        {"id": 3},
        {"id": 1},
    ]
    assert not (backups / cofounder_move.OLD_SNAPSHOTS).exists()
