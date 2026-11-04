"""A chat's model is Hermes's own /model for its conversation (H: gateway/session.py:467
keeps model, provider, base_url); AGOS keeps only the reasoning effort Hermes forgets
on a restart (H: gateway/session_state.py:229, in memory only)."""

import json
import sqlite3
from pathlib import Path
from typing import Any

import hermes_store
from test_identity import MODEL, create, env  # noqa: F401 — fixtures

from agos_core.actions import hermes_channel
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.connection import _migrate
from agos_core.db.migrations import MIGRATIONS

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _sent(core: Any, address: str) -> list[str]:
    return [
        str(r["text"])
        for r in core.db.execute(
            "SELECT text FROM hermes_inbox WHERE chat_ref = ? AND kind = 'command'"
            " AND text LIKE '/model %'",
            (address,),
        )
    ]


def test_the_upgrade_moves_chat_models_into_hermes(env: Any) -> None:  # noqa: F811
    client, core, _home = env
    ws = create(client, "Argan")
    new = client.post(f"/workspaces/{ws}/chats", json={"title": "New"}).json()["id"]
    theirs = client.post(f"/workspaces/{ws}/chats", json={"title": "Theirs"}).json()["id"]
    kept = client.post(f"/workspaces/{ws}/chats", json={"title": "Kept"}).json()["id"]
    pick = {**MODEL, "model": "claude-opus-5", "effort": "max"}
    for chat in (new, theirs):  # what migration 103 left from chats.model
        set_setting(core.db, f"{hermes_channel.MOVE_KEY}{chat}", pick)
    # Hermes already has another model for "theirs" (picked in Hermes): Hermes wins.
    root = core.engine.profile_home(ws)
    hermes_store.model(
        root, "main", str(theirs), {"model": "claude-haiku-5", "provider": "anthropic"}
    )
    # The old whole /model told for "kept": becomes its effort note, same marks.
    told = "/model claude-opus-5 --provider anthropic --session --reasoning high"
    set_setting(core.db, f"hermes.model.agos:{kept}", f"{told}@")

    assert hermes_channel.move_old_models(core) == 1
    assert [s.endswith("--reasoning max") for s in _sent(core, f"agos:{new}")] == [True]
    assert _sent(core, f"agos:{theirs}") == []
    note = hermes_channel.effort_note(core.db, f"agos:{kept}")
    assert (note["model"], note["effort"]) == ("claude-opus-5", "high")
    sel = {**MODEL, "model": "claude-opus-5", "effort": "high"}
    assert hermes_channel.model_command(core, f"agos:{kept}", sel, ws) is None  # nothing re-sent
    left = core.db.execute(
        "SELECT key FROM app_settings WHERE key LIKE 'chats.model.move.%'"
        " OR key LIKE 'hermes.model.%'"
    ).fetchall()
    assert left == []
    assert hermes_channel.move_old_models(core) == 0  # once
    # The chat shows Hermes's pick (and the effort with it).
    hermes_store.model(root, "main", str(new), {"model": "claude-opus-5", "provider": "anthropic"})
    core.db.execute("UPDATE hermes_inbox SET done_at = 'x'")
    got = client.get(f"/workspaces/{ws}/chats/{new}").json()["model"]
    assert (got["model"], got["effort"]) == ("claude-opus-5", "max")
    got = client.get(f"/workspaces/{ws}/chats/{theirs}").json()["model"]
    assert got["model"] == "claude-haiku-5"


def test_migration_keeps_his_picks_until_hermes_has_them() -> None:
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    drop = next(i for i, m in enumerate(MIGRATIONS) if "ALTER TABLE chats DROP COLUMN model" in m)
    for sql in MIGRATIONS[:drop]:
        db.executescript(sql)
    db.execute(f"PRAGMA user_version = {drop}")
    at = "2026-01-01T00:00:00Z"
    db.execute(
        "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES ('w', 'W', ?, ?)",
        (at, at),
    )
    for title, model, deleted in (
        ("a", json.dumps(MODEL), None),
        ("b", None, None),
        ("c", json.dumps(MODEL), at),
    ):
        db.execute(
            "INSERT INTO chats (workspace_id, title, channel, model, created_at, updated_at,"
            " deleted_at, hermes_key) VALUES ('w', ?, 'web', ?, ?, ?, ?, ?)",
            (title, model, at, at, deleted, f"k-{title}"),
        )
    _migrate(db)
    moved = {
        r["key"]: json.loads(r["value"])
        for r in db.execute("SELECT * FROM app_settings WHERE key LIKE 'chats.model.move.%'")
    }
    assert moved == {"chats.model.move.1": MODEL}
    assert "model" not in {r[1] for r in db.execute("PRAGMA table_info(chats)")}


def test_agos_keeps_only_the_effort(env: Any) -> None:  # noqa: F811
    client, core, _home = env
    ws = create(client, "Argan")
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Plan"}).json()["id"]
    pick = {**MODEL, "model": "claude-opus-5", "effort": "max"}
    assert client.put(f"/workspaces/{ws}/chats/{chat}", json={"model": pick}).status_code == 204
    note = get_setting(core.db, f"{hermes_channel.EFFORT_KEY}agos:{chat}", None)
    assert set(note) == {"model", "effort", "told", "sent"}  # no provider, no command
    assert "anthropic" not in json.dumps(note) and "/model" not in json.dumps(note)
    rows = core.db.execute("SELECT key FROM app_settings WHERE key LIKE 'hermes.model.%'")
    assert rows.fetchall() == []
    # Only gateway_models writes it (and the reader in db/chats.py goes through it).
    users = sorted(p.name for p in SRC.rglob("*.py") if '"hermes.effort."' in p.read_text())
    assert users == ["gateway_models.py"]
