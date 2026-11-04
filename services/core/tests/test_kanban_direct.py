"""Opening a Kanban card reads Hermes's own board database (read only, with Hermes's
own queries: engine/hermes_board.py) instead of starting `hermes kanban show` and
`hermes kanban attachments` (over a second per open, every open). Whatever can't
be read that way (another board chosen, a table this Hermes lacks) asks Hermes's
CLI as before. tests/test_kanban_direct_live.py checks the read against the real
Hermes CLI's JSON."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from test_engine_sync import MODEL, env  # noqa: F401 - fixture

# hermes_cli/kanban_db.py SCHEMA_SQL (v0.22.2): the tables a card's page reads.
BOARD = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
    status TEXT NOT NULL, priority INTEGER DEFAULT 0, created_by TEXT,
    created_at INTEGER NOT NULL, started_at INTEGER, completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch', workspace_path TEXT,
    claim_lock TEXT, claim_expires INTEGER, tenant TEXT, result TEXT,
    idempotency_key TEXT, model_override TEXT, provider_override TEXT,
    goal_mode INTEGER NOT NULL DEFAULT 0, session_id TEXT, block_kind TEXT
);
CREATE TABLE task_links (parent_id TEXT NOT NULL, child_id TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id));
CREATE TABLE task_comments (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    author TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    run_id INTEGER, kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL);
CREATE TABLE task_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    profile TEXT, status TEXT NOT NULL, started_at INTEGER NOT NULL, ended_at INTEGER,
    summary TEXT);
CREATE TABLE task_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
    filename TEXT NOT NULL, stored_path TEXT NOT NULL, content_type TEXT,
    size INTEGER NOT NULL DEFAULT 0, uploaded_by TEXT, created_at INTEGER NOT NULL);
CREATE INDEX idx_links_child ON task_links(child_id);
CREATE INDEX idx_links_parent ON task_links(parent_id);
CREATE INDEX idx_comments_task ON task_comments(task_id, created_at);
CREATE INDEX idx_events_task ON task_events(task_id, created_at);
CREATE INDEX idx_runs_task ON task_runs(task_id, started_at);
CREATE INDEX idx_attachments_task ON task_attachments(task_id, created_at);
"""


def _board(root: Path) -> Path:
    """A board as Hermes leaves it: a done parent, a blocked card waiting for an
    answer (comments, events, runs with summaries, a file), and its child."""
    root.mkdir(parents=True, exist_ok=True)
    files = root / "kanban" / "attachments" / "t_1"
    files.mkdir(parents=True)
    (files / "notes.txt").write_text("hello")
    with contextlib.closing(sqlite3.connect(root / "kanban.db")) as db:
        db.executescript(BOARD)
        db.executemany(
            "INSERT INTO tasks (id, title, body, assignee, status, created_by, created_at,"
            " started_at, completed_at, model_override, goal_mode, block_kind)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("t_0", "Research", "", None, "done", "owner", 1_800_000_000, None, 1_800_000_050, None, 0, None),
                # Hermes's own casts: a started_at stored as text, '' meaning no model.
                ("t_1", "Write the script", "The body", "default", "blocked", "user",
                 1_800_000_100, "1800000200", None, "", 1, "needs_input"),
                ("t_2", "Publish", None, None, "todo", "default", 1_800_000_150, None, None, "gpt-x", 0, None),
            ],
        )  # fmt: skip
        db.executemany("INSERT INTO task_links VALUES (?, ?)", [("t_0", "t_1"), ("t_1", "t_2")])
        db.executemany(
            "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
            [
                ("t_1", "owner", "first", 1_800_000_300),
                ("t_1", "default", "second", 1_800_000_300),  # same second: kept in order
                ("t_1", "user", "earlier", 1_800_000_250),
                ("t_0", "owner", "another card's", 1_800_000_260),
            ],
        )
        db.executemany(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
            [
                ("t_1", "created", '{"assignee": "default"}', 1_800_000_100),
                ("t_1", "heartbeat", None, 1_800_000_210),
                ("t_1", "blocked", '{"reason": "Which colour?"}', 1_800_000_400),
                ("t_1", "commented", "{not json", 1_800_000_300),
            ],
        )
        db.executemany(
            "INSERT INTO task_runs (task_id, status, started_at, ended_at, summary)"
            " VALUES (?,?,?,?,?)",
            [
                ("t_1", "done", 1_800_000_200, 1_800_000_300, "an older summary"),
                ("t_1", "blocked", 1_800_000_350, None, '{"output": "the newest summary"}'),
                ("t_1", "blocked", 1_800_000_390, None, ""),  # empty: not a summary
            ],
        )
        db.execute(
            "INSERT INTO task_attachments (task_id, filename, stored_path, content_type,"
            " size, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)",
            ("t_1", "notes.txt", str((files / "notes.txt").resolve()), "text/plain", 5, "owner",
             1_800_000_600),
        )  # fmt: skip
        db.commit()
    return root / "kanban.db"


def _asked(runner: Any) -> list[list[str]]:
    """The Kanban commands AGOS ran with Hermes's CLI."""
    return [c[1:] for c in runner.calls if Path(c[0]).name == "hermes" and c[1:2] == ["kanban"]]


def test_a_card_opens_from_hermess_board_without_starting_hermes(env: Any) -> None:  # noqa: F811
    client, runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core = client.app.state.core
    _board(core.engine.root(ws))
    runner.calls.clear()
    got = client.get(f"/workspaces/{ws}/kanban/t_1")
    assert got.status_code == 200, got.text
    card = got.json()
    assert _asked(runner) == []
    assert (card["title"], card["body"], card["status"]) == (
        "Write the script",
        "The body",
        "blocked",
    )
    assert (card["member"], card["memberTitle"], card["createdBy"]) == (
        "cofounder",
        "Co-Founder",
        "You",
    )
    assert (card["createdAt"], card["startedAt"], card["completedAt"]) == (
        1_800_000_100,
        1_800_000_200,
        None,
    )
    assert card["model"] == "" and card["goal"] is True and card["blockKind"] == "needs_input"
    assert card["summary"] == "the newest summary"
    assert [(c["author"], c["body"], c["at"]) for c in card["comments"]] == [
        ("You", "earlier", 1_800_000_250),
        ("You", "first", 1_800_000_300),
        ("Co-Founder", "second", 1_800_000_300),
    ]
    assert [(e["kind"], e["at"], e["detail"]) for e in card["events"]] == [
        ("created", 1_800_000_100, "Co-Founder"),
        ("commented", 1_800_000_300, ""),
        ("blocked", 1_800_000_400, "Which colour?"),
    ]
    assert card["question"] == "Which colour?"
    assert (card["parents"], card["children"]) == (["t_0"], ["t_2"])
    assert card["attachments"] == [
        {"id": 1, "name": "notes.txt", "size": 5, "by": "You", "at": 1_800_000_600}
    ]
    # The file itself, a file it doesn't have, a card the board doesn't have: no CLI.
    assert client.get(f"/workspaces/{ws}/kanban/t_1/attachments/1").content == b"hello"
    assert client.get(f"/workspaces/{ws}/kanban/t_1/attachments/2").status_code == 404
    assert client.get(f"/workspaces/{ws}/kanban/t_9").status_code == 404
    assert client.get(f"/workspaces/{ws}/kanban/t_9/attachments/1").status_code == 404
    assert _asked(runner) == []


def test_what_cant_be_read_like_hermes_asks_hermess_cli(env: Any) -> None:  # noqa: F811
    client, runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    core = client.app.state.core
    root = core.engine.root(ws)
    db = _board(root)
    # Another board chosen in Hermes (`hermes kanban boards switch`): its CLI decides.
    (root / "kanban" / "current").write_text("other\n")
    runner.calls.clear()
    client.get(f"/workspaces/{ws}/kanban/t_1")
    assert ["kanban", "show", "t_1", "--json"] in _asked(runner)
    (root / "kanban" / "current").unlink()
    # A table this Hermes doesn't have: the CLI answers for it (the rest is read).
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.execute("DROP TABLE task_attachments")
        conn.commit()
    runner.calls.clear()
    client.get(f"/workspaces/{ws}/kanban/t_1")
    assert _asked(runner) == [["kanban", "attachments", "t_1", "--json"]]
    # No board yet: Hermes's CLI (it makes one).
    db.unlink()
    runner.calls.clear()
    client.get(f"/workspaces/{ws}/kanban/t_1")
    assert ["kanban", "show", "t_1", "--json"] in _asked(runner)
