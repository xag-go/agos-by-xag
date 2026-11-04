"""Guards (step 17, web and database): every web screen reads Hermes's state, and
the dead AGOS columns, finished moves and copies of Hermes's state stay gone.

- The Dashboard's "Board activity" is Hermes's Kanban (task_events), not AGOS's
  audit trail (tests/test_workspace_log.py proves the screen's data).
- A workspace page fetches that workspace's own bots, never every workspace's.
- The members' Telegram menus are rebuilt only when the team or a group changed.
- Dead columns and the finished one-time moves are gone; the migration that drops
  them first keeps anything left in a file, and writes nothing when all is moved.
- Copies of Hermes's state are gone: a bot token's end, the provider and tool keys'
  last 4 (Hermes's .env), the webhook port (WEBHOOK_PORT in the .env) and a skill's
  summary (its SKILL.md description).
- Only db/hermes_turns.py reads Hermes's agent.log.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from split_parts import is_part_of, whole_text
from test_library import MODEL
from test_library import env as env

from agos_core.db import connection, leftovers, ownership
from agos_core.db.connection import _migrate
from agos_core.db.migrations import MIGRATIONS

CORE = Path(__file__).resolve().parents[1]
SRC = CORE / "src" / "agos_core"
WEB = CORE.parents[1] / "apps" / "web" / "src"


def _sources() -> dict[str, str]:
    return {
        p.relative_to(SRC).as_posix(): p.read_text()
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "migrations.py"
    }


def _schema() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    from agos_core.db import hermes_text

    hermes_text.install(db)
    _migrate(db)
    return db


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in db.execute(f"PRAGMA table_info({table})")}


# ---- 1. the Dashboard's Board activity -------------------------------------------------


def test_board_activity_reads_hermes_kanban_not_agos_activity() -> None:
    text = (SRC / "api" / "workspaces.py").read_text()
    assert "kanban_board.events" in text
    assert "list_activity" not in text and "FROM activity" not in text
    assert "list_activity" not in (SRC / "db" / "activity.py").read_text()


# ---- 2. workspace isolation on the web ---------------------------------------------------


def test_workspace_pages_never_fetch_every_workspaces_bots() -> None:
    pages = WEB / "app" / "(app)" / "w"
    found = []
    for path in pages.rglob("*.tsx"):
        text = path.read_text()
        if "getChannels(" in text or re.search(r'"GET",\s*"/channels"', text):
            found.append(str(path.relative_to(WEB)))
    assert found == []
    queries = (WEB / "data" / "queries.ts").read_text()
    assert '"GET", "/channels"' not in queries
    for page in ("sessions/page.tsx", "messages/page.tsx"):
        assert "getWorkspaceBots(workspace.id)" in (pages / "[id]" / page).read_text()


# ---- 3. the members' Telegram menus ---------------------------------------------------


def test_the_menus_loop_looks_only_at_marks_and_not_twice_a_second() -> None:
    from agos_core.actions import channels

    assert channels.UPKEEP_EVERY >= 1.0
    text = (SRC / "actions" / "channels.py").read_text()
    start = text.index("def upkeep(")
    upkeep = text[start : text.index("\n\n\n", start)]
    assert "member_menus.sync(core)" in upkeep and "sync_member_menus" not in upkeep
    marks = (SRC / "actions" / "member_menus.py").read_text()
    mark = marks[marks.index("def mark(") : marks.index("def changed(")]
    # A mark stats files; it never reads a profile (no team.get / members / read_text).
    assert "read_text" not in mark and "team_members" not in mark and "team.get" not in mark


# ---- 4. dead columns and code -----------------------------------------------------------


def test_dead_columns_are_gone_and_no_code_names_them() -> None:
    db = _schema()
    assert "job_digest" not in _columns(db, "automations")
    assert "model" not in _columns(db, "chat_turns")
    assert "last_member" not in _columns(db, "group_rooms")
    assert "task_id" not in _columns(db, "activity")
    for rel, text in _sources().items():
        assert "job_digest" not in text and "last_member" not in text, rel
        for sql in re.findall(r"(?:INSERT INTO|UPDATE) activity[^\"]*", text):
            assert "task_id" not in sql, (rel, sql)


def test_every_activity_level_is_a_kind_something_writes() -> None:
    from agos_core.actions.services.system import workspace_log as log

    written = set()
    for text in _sources().values():
        for call in re.findall(r"add_activity\((.*?)\)\n", text, flags=re.S):
            written |= set(re.findall(r'kind="([a-z_.]+)"', call))
    assert set(log._ACTIVITY_LEVEL) <= written, set(log._ACTIVITY_LEVEL) - written


# ---- 5. finished moves ------------------------------------------------------------------


def test_the_finished_moves_and_their_tables_are_gone() -> None:
    db = _schema()
    tables = {str(r[0]) for r in db.execute("SELECT name FROM sqlite_master")}
    assert "workspace_connectors" not in tables
    assert not {"secret", "secret_last4"} & _columns(db, "channel_connections")
    assert not {"legacy", "hermes_profile", "hermes_session", "hermes_uid"} & _columns(
        db, "message_rows"
    )
    view = db.execute("SELECT sql FROM sqlite_master WHERE name = 'messages'").fetchone()[0]
    assert "agos_text" not in view
    # The app's wiring and its start sequence (actions/services/system/startup.py).
    app = (SRC / "api" / "app.py").read_text() + (
        SRC / "actions" / "services" / "system" / "startup.py"
    ).read_text()
    for gone in (
        "kanban_move",
        "move_tokens_to_hermes",
        "move_shared_logins",
        "move_legacy",
        "move_rows",
        "hermes_config.move_all",
    ):
        assert gone not in app, gone
    for rel, text in _sources().items():
        assert "workspace_connectors" not in text or rel == "db/leftovers.py", rel
        # The leftovers archive reads them; the ownership registry lists them as
        # MOVE_ONCE (checked below), so nothing there can keep them.
        if rel != "db/leftovers.py" and not rel.startswith("db/ownership/"):
            assert "title_told" not in text and "owner.timezone" not in text, rel
        if rel != "db/leftovers.py":
            assert "move_rows" not in text and "names_and_models" not in text, rel
            assert "run_session_job" not in text, rel
            assert not re.search(r"\blegacy\s*=\s*[01]", text), rel
    assert ownership.KEYS["owner.timezone"].kind == ownership.MOVE_ONCE
    assert not [k for k in ownership.KEYS if "title_told" in k]


def _before_leftovers(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    """A live-like database just before migration 101 (the leftovers' drop)."""
    last = next(i for i, m in enumerate(MIGRATIONS) if leftovers.MARK in m)
    file = tmp / "system" / "agos.db"
    file.parent.mkdir(parents=True)
    db = sqlite3.connect(file, isolation_level=None)
    db.row_factory = sqlite3.Row
    from agos_core.db import hermes_text

    hermes_text.install(db)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:last])
    _migrate(db, tmp)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    at = "2026-10-01T00:00:00Z"
    db.execute(
        "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES ('ws', 'Argan', ?, ?)",
        (at, at),
    )
    (tmp / "workspaces" / "ws" / "files").mkdir(parents=True)
    db.execute(
        """INSERT INTO chats (id, workspace_id, title, channel, created_at, updated_at, kind)
           VALUES (1, 'ws', 'Plan', 'web', ?, ?, 'chat')""",
        (at, at),
    )
    db.execute(
        """INSERT INTO message_rows (chat_id, author, body, created_at, legacy)
           VALUES (1, 'owner', 'an AGOS line', ?, 0)""",
        (at,),
    )
    db.execute(
        """INSERT INTO channel_connections (kind, name, secret, secret_last4, created_at,
             workspace_id) VALUES ('telegram', 'Bot', '', '1234', ?, 'ws')""",
        (at,),
    )
    db.execute(
        """INSERT INTO library_items (kind, name, title, summary, definition, source, created_at,
             updated_at) VALUES ('skill', 'notes', 'Notes', 'a copy', '{}', 'created', ?, ?)""",
        (at, at),
    )
    return db


def test_the_drop_writes_nothing_when_every_move_is_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _before_leftovers(tmp_path, monkeypatch)
    # A name given to Hermes once left only its mark: it goes, nothing to keep.
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('chats.title_told.1', 'true', 'x')"
    )
    _migrate(db, tmp_path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    assert not list(tmp_path.rglob("leftovers-*.json"))
    assert (
        db.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'chats.%'").fetchone()[0] == 0
    )
    assert [r["body"] for r in db.execute("SELECT body FROM messages")] == ["an AGOS line"]
    assert db.execute("SELECT summary FROM library_items").fetchone()[0] == ""


def test_anything_a_move_left_is_kept_in_a_file_before_it_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _before_leftovers(tmp_path, monkeypatch)
    at = "2026-10-01T00:00:00Z"
    db.execute(
        """INSERT INTO message_rows (chat_id, author, body, created_at, legacy)
           VALUES (1, 'agent', 'an old copy', ?, 1)""",
        (at,),
    )
    db.execute("UPDATE channel_connections SET secret = 'sealed-token'")
    db.execute(
        """INSERT INTO library_items (kind, name, title, summary, definition, source, created_at,
             updated_at, workspace_id)
           VALUES ('agent', 'writer', 'Writer', 'Writes', '{"instructions": "x"}', 'created',
                   ?, ?, 'ws')""",
        (at, at),
    )
    agent = db.execute("SELECT id FROM library_items WHERE kind = 'agent'").fetchone()[0]
    db.execute(
        """INSERT INTO workspace_connectors (workspace_id, item_id, enabled, local, updated_at)
           VALUES ('ws', ?, 1, 'his note', ?)""",
        (agent, at),
    )
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES ('owner.timezone', ?, ?)",
        (json.dumps("Europe/Paris"), at),
    )
    found = leftovers.left(db)
    assert {k for k, v in found.items() if v} == {
        "connectors",
        "agent_rows",
        "bot_tokens",
        "messages",
        "settings",
    }
    _migrate(db, tmp_path)
    [kept] = list((tmp_path / "workspaces" / "ws" / "files" / "archive").glob("leftovers-*.json"))
    data = json.loads(kept.read_text())
    assert data["messages"][0]["body"] == "an old copy"
    assert data["bot_tokens"][0]["sealed_token"] == "sealed-token"  # noqa: S105 - sealed
    assert data["connectors"][0]["local"] == "his note"
    assert data["agent_rows"][0]["title"] == "Writer"
    [owner] = list((tmp_path / "system").rglob("leftovers-*.json"))
    assert json.loads(owner.read_text())["settings"][0]["key"] == "owner.timezone"
    # ...and then they are gone.
    assert [r["body"] for r in db.execute("SELECT body FROM messages")] == ["an AGOS line"]
    row = db.execute("SELECT title, definition FROM library_items WHERE kind = 'agent'").fetchone()
    assert (row["title"], row["definition"]) == ("", "{}")
    assert not any(leftovers.left(db).values())


# ---- 6. copies of Hermes's state ----------------------------------------------------------


def test_no_copy_of_a_hermes_env_value_or_skill_description() -> None:
    texts = _sources()
    for rel, text in texts.items():
        assert "secret_last4" not in text or (
            rel == "actions/library.py" or is_part_of(text, "actions/library.py")
        ), rel
        assert "hooks.port." not in text and "PORT_KEY" not in text, rel
    # The webhook port is read from the workspace's .env, like the API server's.
    hooks = texts["actions/hooks.py"]
    assert '"WEBHOOK_PORT"' in hooks and "get_setting" not in hooks[hooks.index("def port_of") :]
    models = texts["actions/services/settings/model_keys.py"]
    assert '"last4": last4' not in models and "general_values" in models
    services = texts["actions/tool_services.py"]
    assert "[-4:] for k in wanted" not in services
    library = whole_text("actions/library.py", texts)
    assert "summary_of(core, row)" in library


def test_a_tool_service_is_read_from_each_profiles_hermes(tmp_path: Path) -> None:
    """The service a tool uses is the one each profile's Hermes uses (Hermes's
    picker over its config.yaml); its key's end comes from Hermes's .env. AGOS
    keeps no `tools.services` copy (moved into Hermes once, then deleted)."""
    from types import SimpleNamespace

    from agos_core.actions import hermes_time_limits, tool_services
    from agos_core.actions.hermes_time_limits import Profile
    from agos_core.db.app_settings import get_setting, set_setting
    from agos_core.engine import hermes_tools

    db = _schema()
    home = tmp_path / "ws"
    home.mkdir()
    (home / ".env").write_text("FAL_KEY=fal-secret-1234\n")
    uses: dict[str, str | None] = {"image_gen": "FAL.ai"}
    written: list[tuple[str, dict[str, Any]]] = []
    engine = SimpleNamespace(
        tool_services_in=lambda _h: dict(uses),
        set_tool_service=lambda h, job: written.append((str(h), job)),
    )
    core: Any = SimpleNamespace(db=db, settings=SimpleNamespace(data_dir=tmp_path), engine=engine)
    saved = hermes_tools._current["list"]
    hermes_tools._current["list"] = [
        {
            "key": "image_gen",
            "label": "Image Generation",
            "about": "",
            "providers": [{"name": "FAL.ai", "env": [{"key": "FAL_KEY"}]}],
        }
    ]
    real_profiles = hermes_time_limits.profiles
    hermes_time_limits.profiles = lambda _core: [Profile("w", "W", home)]  # type: ignore[assignment]
    try:
        assert tool_services.chosen(core) == {
            "image_gen": {"provider": "FAL.ai", "keys": {"FAL_KEY": "1234"}}
        }
        (home / ".env").write_text("FAL_KEY=fal-secret-9999\n")  # changed in Hermes
        assert tool_services.chosen(core)["image_gen"]["keys"] == {"FAL_KEY": "9999"}
        uses["image_gen"] = None  # unset in Hermes: not shown as set up
        assert tool_services.chosen(core) == {}
        # The old copy goes into the connectors home's Hermes once, then is deleted.
        set_setting(db, tool_services.OLD_SETTING, {"image_gen": {"provider": "FAL.ai"}})
        connectors = tmp_path / "system" / "connectors"
        connectors.mkdir(parents=True)
        (connectors / "config.yaml").write_text("{}\n")
        assert tool_services.move_old_setting(core) is True
        assert written and written[0][0] == str(connectors)
        assert written[0][1]["provider"] == "FAL.ai"
        assert get_setting(db, tool_services.OLD_SETTING, None) is None
        assert tool_services.move_old_setting(core) is False  # once
    finally:
        hermes_tools._current["list"] = saved
        hermes_time_limits.profiles = real_profiles
    # Nothing in AGOS writes the old key again.
    texts = _sources()
    for rel, text in texts.items():
        if rel != "actions/tool_services.py":
            ok = rel == "db/migrations.py" or rel.startswith("db/ownership/")  # MOVE_ONCE
            assert "tools.services" not in text or ok, rel
    assert ownership.KEYS["tools.services"].kind == ownership.MOVE_ONCE
    services = texts["actions/tool_services.py"]
    assert "set_setting" not in services


def test_library_rows_keep_no_copy_of_a_skill_or_toolset(env: Any) -> None:
    """A skill's name and description are its SKILL.md's (Hermes's reader), a
    tool's label and words Hermes's catalog: the rows hold only the id (and a
    skill's display name only when the owner gave one, which Hermes has no place
    for)."""
    client, core, _runner, _home = env
    w = client.post("/workspaces", json={"name": "Alpha", "defaultModel": MODEL}).json()["id"]
    skill = "---\nname: memo-check\ndescription: Checks memos.\n---\nBody\n"
    r = client.post(
        f"/workspaces/{w}/skills",
        json={"name": "memo-check", "title": "memo-check", "definition": {"text": skill}},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    skills = {i["name"]: i for i in client.get(f"/workspaces/{w}/skills").json()}
    assert skills["memo-check"]["title"] == "memo-check"
    assert skills["memo-check"]["summary"] == "Checks memos."
    listed = {i["name"]: i for i in client.get("/library").json()}
    from agos_core.engine import hermes_tools

    assert listed["web"]["title"] == hermes_tools.title("web")
    assert listed["web"]["summary"] == hermes_tools.about("web")
    rows = core.db.execute(
        "SELECT kind, name, title, summary, definition FROM library_items"
        " WHERE kind IN ('tool', 'skill')"
    ).fetchall()
    assert rows
    for row in rows:
        assert row["summary"] == "", dict(row)
        if row["kind"] == "tool":
            assert (row["title"], row["definition"]) == ("", "{}"), dict(row)
        else:
            assert row["title"] != row["name"], dict(row)
            assert "text" not in json.loads(row["definition"]), dict(row)
    # The repository itself refuses the copies (every writer goes through it).
    from agos_core.db import library as repo

    repo.update_item(core.db, sid, title="memo-check", summary="x", definition={})
    row = core.db.execute(
        "SELECT title, summary FROM library_items WHERE id = ?", (sid,)
    ).fetchone()
    assert (row["title"], row["summary"]) == ("", "")
    # An owner's own display name stays (Hermes has no field for it).
    repo.update_item(core.db, sid, title="Memo checker", summary="", definition={})
    listed = {i["name"]: i for i in client.get(f"/workspaces/{w}/skills").json()}
    assert listed["memo-check"]["title"] == "Memo checker"
    for rel in ("actions/library.py", "actions/workspace_skills.py"):
        src = whole_text(rel, _sources())
        assert "UPDATE library_items SET summary" not in src, rel
        assert "SET summary = ?, title = ?" not in src, rel


def test_no_copy_of_hermess_command_menu() -> None:
    """Hermes's "/" menu is read from its registry (telegram_menu_commands, in the
    engine) each time; nothing stores it and the plugin no longer sends it."""
    texts = _sources()
    for rel, text in texts.items():
        if rel != "db/migrations.py":
            assert "hermes.commands." not in text, rel
    channel = texts["actions/services/channel/gateway_commands.py"]
    body = channel[channel.index("def commands(") :]
    body = body[: body.index("\ndef ")]
    assert "command_menu" in body and "get_setting" not in body and "set_setting" not in body
    assert "telegram_menu_commands" in texts["engine/hermes/tools.py"]
    plugin = texts["hermes_plugin/agos_guard/bridge_menu.py"]
    sender = plugin[plugin.index("async def _send_menu") :]
    sender = sender.split("\ndef ")[0]
    assert "get_my_commands" not in sender


def test_a_skills_summary_is_its_skill_md_description(env: Any) -> None:
    client, core, _runner, _home = env
    w = client.post("/workspaces", json={"name": "Alpha", "defaultModel": MODEL}).json()["id"]
    skill = "---\nname: invoice-check\ndescription: Checks invoices.\n---\nBody\n"
    r = client.post(
        f"/workspaces/{w}/skills", json={"name": "invoice-check", "definition": {"text": skill}}
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    row = core.db.execute("SELECT summary FROM library_items WHERE id = ?", (sid,)).fetchone()
    assert row["summary"] == ""  # no copy
    listed = {i["id"]: i for i in client.get(f"/workspaces/{w}/skills").json()}
    assert listed[sid]["summary"] == "Checks invoices."
    from agos_core.actions.workspace_skills import skill_dir

    found = skill_dir(core, w, "invoice-check")
    assert found is not None
    path = found / "SKILL.md"
    path.write_text(path.read_text().replace("Checks invoices.", "Checks every invoice."))
    listed = {i["id"]: i for i in client.get(f"/workspaces/{w}/skills").json()}
    assert listed[sid]["summary"] == "Checks every invoice."


# ---- 7. agent.log ---------------------------------------------------------------------


def test_no_code_reads_agent_log() -> None:
    """Turn ends come from Hermes's hooks; no AGOS code parses Hermes's log text."""
    readers = [rel for rel, text in _sources().items() if re.search(r"[\"']agent\.log[\"']", text)]
    assert readers == []
