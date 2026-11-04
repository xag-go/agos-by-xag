"""The board asks Hermes's Kanban again only when the board's database changed."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agos_core.actions import agent_profiles, kanban_board
from agos_core.actions.services.board import kanban_cli


def test_hermes_is_asked_again_only_when_the_board_changed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import sqlite3

    home = tmp_path / "kanban"
    home.mkdir()
    db = sqlite3.connect(home / "kanban.db")
    db.execute(
        "CREATE TABLE tasks (id TEXT, title TEXT, body TEXT, assignee TEXT, status TEXT,"
        " created_by TEXT, created_at INT, started_at INT, completed_at INT,"
        " model_override TEXT, goal_mode INT, block_kind TEXT)"
    )
    db.execute("INSERT INTO tasks (id, title, status) VALUES ('t1', 'x', 'ready')")
    db.commit()
    asked: list[int] = []

    def hermes_lists(_core: Any, _ws: str, *_args: str) -> str:
        asked.append(1)
        (home / "kanban.db-wal").write_bytes(b"touched")  # Hermes's CLI touches the file
        return json.dumps([{"id": "t1", "title": "x", "status": "ready"}])

    monkeypatch.setattr(agent_profiles, "board_home", lambda _c, _w: home)
    monkeypatch.setattr(kanban_cli, "run", hermes_lists)
    core: Any = SimpleNamespace(engine=object())
    kanban_board._listed_cache.clear()
    assert kanban_board._listed(core, "a")[0]["id"] == "t1"
    kanban_board._listed(core, "a")
    kanban_board._listed(core, "a")
    assert len(asked) == 1
    db.execute("UPDATE tasks SET status = 'running'")
    db.commit()
    kanban_board._listed(core, "a")
    assert len(asked) == 2


def test_counters_are_hermess_kanban_stats(tmp_path: Path, monkeypatch: Any) -> None:
    """The dashboard's counters are `hermes kanban stats --json`, asked again only
    when the board changed; AGOS counts nothing in kanban.db itself."""
    import inspect
    import sqlite3

    home = tmp_path / "kanban"
    home.mkdir()
    db = sqlite3.connect(home / "kanban.db")
    db.execute(
        "CREATE TABLE tasks (id TEXT, title TEXT, body TEXT, assignee TEXT, status TEXT,"
        " created_by TEXT, created_at INT, started_at INT, completed_at INT,"
        " model_override TEXT, goal_mode INT, block_kind TEXT)"
    )
    db.execute("INSERT INTO tasks (id, title, status) VALUES ('t1', 'x', 'ready')")
    db.commit()
    asked: list[tuple[str, ...]] = []

    def hermes(_core: Any, _ws: str, *args: str) -> str:
        asked.append(args)
        return json.dumps(
            {"by_status": {"running": 2, "blocked": 1, "review": 1, "todo": 3, "done": 4}}
        )

    monkeypatch.setattr(agent_profiles, "board_home", lambda _c, _w: home)
    monkeypatch.setattr(kanban_cli, "run", hermes)
    core: Any = SimpleNamespace(engine=object())
    kanban_board._stats_cache.clear()
    want = {"working": 2, "waiting_for_you": 2, "suggestions": 3, "done": 4}
    assert kanban_board.counters(core, "a") == want
    assert kanban_board.counters(core, "a") == want
    assert asked == [("stats", "--json")]
    db.execute("UPDATE tasks SET status = 'running'")
    db.commit()
    kanban_board.counters(core, "a")
    assert len(asked) == 2
    body = inspect.getsource(kanban_board.counters)
    assert "COUNT(" not in body and "sqlite3" not in body


def test_hermess_own_stats_json_is_what_counters_read(tmp_path: Path) -> None:
    """The real `hermes kanban stats --json` on a throwaway board."""
    import os
    import shutil
    import subprocess

    hermes = shutil.which("hermes")
    tools = Path.home() / ".hermes" / "tools"
    if not hermes or not tools.is_dir():
        import pytest

        pytest.skip("no Hermes install on this machine")
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    from conftest import hermes_ready_home

    hermes_ready_home(home)  # Hermes's per-root environment, not built again
    # The board is pinned to this throwaway home: a HERMES_HOME under ~/.hermes
    # (pytest's tmp can be there) would otherwise use ~/.hermes's own board
    # (hermes_cli/kanban_db.py kanban_home -> get_default_hermes_root).
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("HERMES_")},
        "HERMES_HOME": str(home),
        "HERMES_KANBAN_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(tools),
        "HOME": str(tmp_path),
    }

    def run(*args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed argv
            [hermes, "kanban", *args], env=env, capture_output=True, text=True, timeout=180
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout

    run("create", "one", "--json")
    run("create", "two", "--json", "--triage")
    assert (home / "kanban.db").is_file()  # this home's board, nobody else's
    stats = kanban_board._json(run("stats", "--json"))
    assert stats["by_status"] == {"ready": 1, "triage": 1}, stats
    assert kanban_board.by_where(stats)["suggestions"] == 1


def test_the_read_ahead_asks_each_board_before_the_first_page(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Hermes's list (`kanban list` also promotes cards whose parents finished, so it
    stays Hermes's) and its stats, asked once after a start for each workspace with
    a board; the Board page and the counters then don't start Hermes."""
    import sqlite3

    from agos_core.db import workspaces as workspaces_repo
    from agos_core.engine import read_ahead

    boards = {"a": tmp_path / "a", "b": tmp_path / "b"}
    for home in boards.values():
        home.mkdir()
    db = sqlite3.connect(boards["a"] / "kanban.db")  # b has no board yet
    db.execute(
        "CREATE TABLE tasks (id TEXT, title TEXT, body TEXT, assignee TEXT, status TEXT,"
        " created_by TEXT, created_at INT, started_at INT, completed_at INT,"
        " model_override TEXT, goal_mode INT, block_kind TEXT)"
    )
    db.execute("INSERT INTO tasks (id, title, status) VALUES ('t1', 'x', 'ready')")
    db.commit()
    asked: list[tuple[str, ...]] = []

    def hermes(_core: Any, ws: str, *args: str) -> str:
        asked.append((ws, *args))
        if args[0] == "stats":
            return json.dumps({"by_status": {"ready": 1}})
        return json.dumps([{"id": "t1", "title": "x", "status": "ready"}])

    monkeypatch.setattr(agent_profiles, "board_home", lambda _c, w: boards[w])
    monkeypatch.setattr(kanban_cli, "run", hermes)
    monkeypatch.setattr(
        workspaces_repo, "list_workspaces", lambda _db: [SimpleNamespace(id=w) for w in boards]
    )
    core: Any = SimpleNamespace(engine=object(), db=None)
    kanban_board._listed_cache.clear()
    kanban_board._stats_cache.clear()
    assert "agos_core.actions.kanban_board:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.kanban_board:read_ahead",))
    assert sorted(asked) == [
        ("a", "list", "--json", "--archived", "--sort", "created-desc"),
        ("a", "stats", "--json"),
    ]
    assert kanban_board._listed(core, "a")[0]["id"] == "t1"
    assert kanban_board.counters(core, "a")["suggestions"] == 0
    assert len(asked) == 2
