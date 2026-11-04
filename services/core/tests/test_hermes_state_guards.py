"""Guards: what Hermes holds, AGOS keeps no copy of (step 16, audit B2, B4, B5).

- A Hermes chat's tokens, model and how its turns ended are Hermes's (its sessions,
  messages.token_count, session_model_usage, agent.log "Turn ended"): no AGOS code
  writes them on a turn record, and the plugin sends none with an answer's end.
- A Telegram bot's lamp is Hermes's gateway_state.json, read live: no status cache
  in channel_connections, no loop re-reading it or re-applying the profile's .env.
- MCP: added, removed or switched servers are Hermes's own reconcile; /reload-mcp is
  only for an edited entry, every profile skips its confirm, and AGOS never answers
  one with /approve.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
from pathlib import Path

from agos_core.db.migrations import MIGRATIONS

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _sources() -> dict[Path, str]:
    return {
        p: p.read_text()
        for p in SRC.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "migrations.py"
    }


def _schema() -> sqlite3.Connection:
    from agos_core.db.connection import _migrate

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    _migrate(db)
    return db


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in db.execute(f"PRAGMA table_info({table})")}


def test_turn_records_hold_no_copy_of_hermess_usage_model_or_status() -> None:
    from agos_core.db import chat_turns

    db = _schema()
    assert not {"usage", "provider"} & _columns(db, "chat_turns")
    assert not {"usage", "provider", "model"} & chat_turns._TURN_FIELDS
    for path, text in _sources().items():
        for sql in re.findall(r"UPDATE chat_turns SET[^\"]*", text):
            assert not re.search(r"\b(model|usage|provider)\s*=", sql), (path, sql)
        for sql in re.findall(r"INSERT INTO chat_turns\s*\([^)]*\)", text):
            assert not re.search(r"\b(model|usage|provider)\b", sql), (path, sql)


def test_an_answers_end_carries_only_that_it_ended() -> None:
    from agos_core.actions import hermes_channel
    from agos_core.api.hermes_bridge import TurnFinish
    from agos_core.engine.chat import LiveTurn
    from agos_core.hermes_plugin.agos_guard import bridge

    assert set(TurnFinish.model_fields) == {"turn_id", "text"}
    params = set(inspect.signature(hermes_channel.turn_finish).parameters)
    assert params == {"core", "workspace_id", "turn_id", "text"}
    assert not hasattr(bridge, "_usage")
    assert '"usage"' not in inspect.getsource(bridge._finish)
    assert "runtime" not in inspect.getsource(bridge._finish)
    assert not {"usage", "runtime"} & set(LiveTurn.__dataclass_fields__)


def test_the_bot_lamp_has_no_cache_and_no_loop() -> None:
    from agos_core.actions import channels, hermes_channel

    db = _schema()
    assert not {"status", "status_reason", "last_ok_at"} & _columns(db, "channel_connections")
    for name in ("follow_bots", "show_state", "_last_kept"):
        assert not hasattr(hermes_channel, name), name
    assert not hasattr(channels, "_set_status")
    assert "hermes_channel" not in inspect.getsource(channels.run_forever)
    for path, text in _sources().items():
        for sql in re.findall(r"UPDATE channel_connections SET[^\"]*", text):
            assert not re.search(r"\bstatus\b|last_ok_at", sql), (path, sql)


def test_mcp_changes_are_hermess_reconcile_and_no_approve() -> None:
    from agos_core.actions import hermes_channel, library

    assert library.profile_settings([])["approvals.mcp_reload_confirm"] == "false"
    assert "/approve" not in inspect.getsource(hermes_channel.reload_mcp)
    # The only /approve AGOS sends is the answer to Hermes's own /undo confirm.
    uses = [
        (path.name, line.strip())
        for path, text in _sources().items()
        for line in text.splitlines()
        if "/approve" in line
        and not line.strip().startswith(("#", '"', "'"))
        and '"/approve"' in line
    ]
    assert uses == [
        ("gateway_commands.py", 'said = [command, "/approve"] if command == "/undo" else [command]')
    ]


def test_only_an_edited_mcp_entry_reloads(tmp_path: Path) -> None:
    from agos_core.actions.library import _mcp_edited

    assert not _mcp_edited(tmp_path, {"a": "1"})  # added
    assert not _mcp_edited(tmp_path, {"a": "1", "b": "2"})  # added
    assert not _mcp_edited(tmp_path, {"a": "1"})  # removed
    assert _mcp_edited(tmp_path, {"a": "9"})  # edited
    (tmp_path / ".agos-mcp").write_text("0123abcd")  # the older single-hash stamp
    assert not _mcp_edited(tmp_path, {"a": "9"})


def test_migrations_drop_the_copies() -> None:
    text = "\n".join(MIGRATIONS)
    for column in ("usage", "provider"):
        assert f"ALTER TABLE chat_turns DROP COLUMN {column};" in text
    for column in ("status", "status_reason", "last_ok_at"):
        assert f"ALTER TABLE channel_connections DROP COLUMN {column};" in text
