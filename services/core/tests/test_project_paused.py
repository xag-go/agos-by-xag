"""A goal or project can be "paused": on hold, it comes back (dropped ends it).

- Migration 137 rebuilds the goals table to take the new status: every row, column
  and key result survives, the rebuild replays, and a bad status is still refused.
- An agent's plan change that pauses a project is approved as is (it was refused
  before: "A project is active, done, dropped."), the project leaves the progress
  and the agents' work list, and the SOUL.md section says it is paused.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_vision import _bridge, pushed, space  # noqa: F401 - fixtures

from agos_core.actions import goals, proposals
from agos_core.actions.errors import ActionError
from agos_core.db import connection
from agos_core.db.migrations import MIGRATIONS
from agos_core.engine import goals as rules

MARK = "CHECK (status IN ('active','paused','done','dropped'))"


def test_the_rebuild_keeps_every_row_and_takes_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    mark = next(i for i, m in enumerate(MIGRATIONS) if MARK in m)
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:mark])
    connection._migrate(db)
    db.execute("INSERT INTO workspaces (id, created_at, updated_at) VALUES ('w', 't', 't')")
    row = """INSERT INTO goals (id, workspace_id, parent_id, level, title, status, project_kind,
             rhythm, created_at, updated_at) VALUES (?, 'w', ?, ?, ?, ?, ?, ?, 't', 't')"""
    db.execute(row, (1, None, "vision", "Grow", "active", None, None))
    db.execute(row, (2, 1, "goal", "Audience", "active", None, None))
    db.execute(row, (5, 2, "project", "Build in public", "active", "recurring", "every 2 weeks"))
    db.execute(row, (6, 2, "project", "Old idea", "dropped", "dated", None))
    db.execute(
        "INSERT INTO key_results (workspace_id, goal_id, title, created_at, updated_at)"
        " VALUES ('w', 2, '10k followers', 't', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE goals SET status = 'paused' WHERE id = 5")
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[: mark + 1])
    connection._migrate(db)

    def state() -> list[tuple[Any, ...]]:
        return [
            tuple(r)
            for r in db.execute(
                "SELECT id, parent_id, level, title, status, project_kind, rhythm FROM goals"
                " ORDER BY id"
            )
        ]

    before = state()
    assert before == [
        (1, None, "vision", "Grow", "active", None, None),
        (2, 1, "goal", "Audience", "active", None, None),
        (5, 2, "project", "Build in public", "active", "recurring", "every 2 weeks"),
        (6, 2, "project", "Old idea", "dropped", "dated", None),
    ]
    krs = [tuple(r) for r in db.execute("SELECT goal_id, title FROM key_results")]
    assert krs == [(2, "10k followers")]
    db.execute("UPDATE goals SET status = 'paused' WHERE id = 5")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE goals SET status = 'sleeping' WHERE id = 5")
    indexes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"goals_one_workspace_goal", "goals_by_workspace"} <= indexes
    # Replayed on a database already at this migration: nothing doubles or moves.
    db.execute(f"PRAGMA user_version = {mark}")
    connection._migrate(db)
    assert len(state()) == 4
    assert db.execute("SELECT status FROM goals WHERE id = 5").fetchone()[0] == "paused"
    # Links still hold: removing the goal still takes its key results with it.
    db.execute("DELETE FROM goals WHERE parent_id = 2")
    db.execute("DELETE FROM goals WHERE id = 2")
    assert db.execute("SELECT COUNT(*) FROM key_results").fetchone()[0] == 0


def test_an_agent_pauses_a_project_and_the_plan_leaves_it_alone(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
) -> None:
    client, core, _cron, ws = space
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    project = goals.add_project(core, ws, goal, title="Build in public", owner="editor")
    other = goals.add_project(core, ws, goal, title="Reels", owner="editor")
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "project",
            "payload": {
                "project_id": project,
                "title": "Build in public",
                "status": "paused",
                "why": "Waits for the new account.",
            },
        },
    )
    [shown] = proposals.waiting(core, ws)
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    vision = goals.top(core, ws)
    assert vision is not None
    status = {p.id: p.status for p in vision.children[0].children}
    assert status == {project: "paused", other: "active"}
    soul = rules.prompt(vision, "editor")
    assert f"Project #{other} Reels" in soul
    assert f"Project #{project} Build in public: paused, no work on it" in soul
    # The owner resumes it from the page; a made-up status is still refused.
    goals.update_item(core, ws, project, {"status": "active"})
    with pytest.raises(ActionError, match="active, paused, done or dropped"):
        goals.update_item(core, ws, project, {"status": "sleeping"})
