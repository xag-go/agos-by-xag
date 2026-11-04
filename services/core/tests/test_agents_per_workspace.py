"""Agents belong to one workspace: the upgrade splits shared ones, nothing is lost."""

import sqlite3

import pytest

from agos_core.db import connection, leftovers
from agos_core.db.connection import _migrate
from agos_core.db.migrations import MIGRATIONS


def test_the_upgrade_gives_each_workspace_its_own_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    # The migration that gives agents a workspace (later ones run after it).
    before = next(
        i for i, m in enumerate(MIGRATIONS) if "_agos_connectors" in m and "workspace_id" in m
    )
    for sql in MIGRATIONS[:before]:
        db.executescript(sql)
    db.execute(f"PRAGMA user_version = {before}")
    at = "2026-01-01T00:00:00Z"
    for w in ("cc", "si", "idle"):
        db.execute(
            "INSERT INTO workspaces (id, name, default_model, limits, created_at, updated_at)"
            " VALUES (?, ?, '{}', '{}', ?, ?)",
            (w, w, at, at),
        )
    rows = [
        (1, "agent", "ideas", "Ideas Generator"),  # on in cc and si: split in two
        (2, "agent", "writer", "Script Writer"),  # only cc
        (3, "agent", "loner", "Loner"),  # in no workspace
        (4, "skill", "hooks", "Hooks"),  # skills stay global
    ]
    for i, kind, name, title in rows:
        db.execute(
            "INSERT INTO library_items (id, kind, name, title, definition, created_at, updated_at)"
            ' VALUES (?, ?, ?, ?, \'{"instructions": "x"}\', ?, ?)',
            (i, kind, name, title, at, at),
        )
    for w, item, on, local in (
        ("cc", 1, 1, "cc notes"),
        ("si", 1, 1, "si notes"),
        ("cc", 2, 1, ""),
        ("cc", 4, 1, ""),
        ("si", 4, 0, ""),
    ):
        db.execute(
            "INSERT INTO workspace_connectors (workspace_id, item_id, enabled, local, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (w, item, on, local, at),
        )
    # Up to the migration where workspace_connectors goes (db/leftovers.py).
    last = next(i for i, m in enumerate(MIGRATIONS) if leftovers.MARK in m)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:last])
    _migrate(db)

    agents = {
        (r["workspace_id"], r["name"]): r
        for r in db.execute("SELECT * FROM library_items WHERE kind = 'agent'")
    }
    assert set(agents) == {("cc", "ideas"), ("si", "ideas"), ("cc", "writer"), (None, "loner")}
    assert agents[("cc", "ideas")]["id"] == 1  # the first keeps its id (chats, tasks)
    assert agents[("si", "ideas")]["id"] != 1
    assert agents[("si", "ideas")]["title"] == "Ideas Generator"
    links = {
        (r["workspace_id"], r["item_id"]): (r["enabled"], r["local"])
        for r in db.execute("SELECT * FROM workspace_connectors")
    }
    si_id = agents[("si", "ideas")]["id"]
    assert links == {
        ("cc", 1): (1, "cc notes"),
        ("si", si_id): (1, "si notes"),
        ("cc", 2): (1, ""),
        ("cc", 4): (1, ""),
        ("si", 4): (0, ""),
    }
    skill = db.execute("SELECT workspace_id FROM library_items WHERE kind = 'skill'").fetchone()
    assert skill["workspace_id"] is None
    # Same agent name in two workspaces is allowed; twice in one is not.
    try:
        db.execute(
            "INSERT INTO library_items (kind, name, title, created_at, updated_at, workspace_id)"
            " VALUES ('agent', 'ideas', 'dup', ?, ?, 'cc')",
            (at, at),
        )
        raise AssertionError("duplicate allowed")
    except sqlite3.IntegrityError:
        pass
