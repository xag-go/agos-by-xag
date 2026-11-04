"""The Telegram groups and topics a chat can be linked to are Hermes's own channel
directory (H: gateway/channel_directory.py). What that directory can't have (a
group the bot stays quiet in, a topic name Hermes doesn't know) goes into Hermes's
own channel_aliases.json (its `_apply_channel_aliases`); AGOS keeps nothing."""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from channels_rig import OWNER, env, fake_telegram  # noqa: F401 — fixtures
from hermes_channel_rig import _bridge, _hermes_bot

from agos_core.actions import hermes_channel
from agos_core.db import ownership
from agos_core.db.app_settings import get_setting
from agos_core.db.connection import _migrate
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.records import Workspace

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _directory(home: Path, entries: list[dict[str, Any]]) -> None:
    """Hermes's directory as its gateway writes it (H: build_channel_directory)."""
    data = {"updated_at": "2026-10-19T09:00:00", "platforms": {"telegram": entries}}
    (home / "channel_directory.json").write_text(json.dumps(data))


def _note(core: Any, ws: str) -> Any:
    assert get_setting(core.db, hermes_channel.GROUPS_KEY + ws, None) is None  # AGOS: none
    path = core.engine.profile_home(ws) / "channel_aliases.json"
    return json.loads(path.read_text()).get("telegram") if path.is_file() else None


def test_places_come_from_hermes_and_agos_keeps_only_what_it_lacks(env: Any) -> None:  # noqa: F811
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    me = {"sender": str(OWNER)}
    home = core.engine.profile_home(ws)
    # Hermes knows a group and its topic from its own sessions (topic name unknown).
    _directory(
        home,
        [
            {"id": str(OWNER), "name": "Sara", "type": "dm", "thread_id": None},
            {"id": "-1000007", "name": "Ops", "type": "group", "thread_id": None},
            {"id": "-1000007:12", "name": "Ops / topic 12", "type": "group", "thread_id": "12"},
            {"id": "-1000007:13", "name": "Ops / Leads", "type": "group", "thread_id": "13"},
        ],
    )
    got = client.get(f"/workspaces/{ws}/telegram-places").json()
    rows = [(p["address"], p["group"], p["label"]) for p in got["places"]]
    assert rows == [
        (f"{OWNER}:0", "", "Private chat with the bot"),
        ("-1000007:0", "Ops", "General"),
        ("-1000007:13", "Ops", "Leads"),
        ("-1000007:12", "Ops", "Topic 12"),
    ]
    assert client.get(f"/workspaces/{ws}/telegram-groups").json()["groups"] == [
        {"id": "-1000007", "name": "Ops"}
    ]
    assert _note(core, ws) is None  # nothing of Hermes's is copied

    # He writes in a place Hermes holds: AGOS notes nothing.
    _bridge(
        client, ws, key, "incoming", me | {"chat": "-1000007:13", "text": "x", "chatName": "Ops"}
    )
    assert _note(core, ws) is None
    # A topic name only Telegram's own message carried (Hermes says "topic 12"): kept.
    said = me | {"chat": "-1000007:12", "text": "x", "chatName": "Ops", "topicName": "Ideas"}
    _bridge(client, ws, key, "incoming", said)
    assert _note(core, ws) == {"-1000007:12": "Ops / Ideas"}
    # A group the bot stays quiet in (no session in Hermes): only AGOS saw it.
    quiet = me | {"chat": "-1000009", "text": "hi", "chatName": "Team"}
    assert _bridge(client, ws, key, "incoming", quiet).json() == {"handled": True}
    assert _note(core, ws)["-1000009"] == "Team"
    labels = {
        p["address"]: (p["group"], p["label"])
        for p in client.get(f"/workspaces/{ws}/telegram-places").json()["places"]
    }
    assert labels["-1000007:12"] == ("Ops", "Ideas")
    assert labels["-1000009:0"] == ("Team", "General")

    # The group is renamed in Telegram: his next message there renames it in Hermes.
    renamed = me | {"chat": "-1000009", "text": "hi", "chatName": "Team HQ"}
    _bridge(client, ws, key, "incoming", renamed)
    groups = client.get(f"/workspaces/{ws}/telegram-groups").json()["groups"]
    assert {g["id"]: g["name"] for g in groups} == {"-1000007": "Ops", "-1000009": "Team HQ"}
    assert _note(core, ws)["-1000009"] == "Team HQ"


def test_an_old_note_moves_into_hermess_aliases_once(env: Any) -> None:  # noqa: F811
    from agos_core.db.app_settings import set_setting

    client, core, _fake, _tg, ws = env
    _hermes_bot(client, core, ws)
    old = {"-1000021": {"name": "Sales", "topics": {"0": "", "4": "Leads"}}}
    set_setting(core.db, hermes_channel.GROUPS_KEY + ws, old)
    groups = client.get(f"/workspaces/{ws}/telegram-groups").json()["groups"]
    assert {"id": "-1000021", "name": "Sales"} in groups
    assert _note(core, ws) == {"-1000021": "Sales", "-1000021:4": "Sales / Leads"}
    labels = {
        p["address"]: p["label"]
        for p in client.get(f"/workspaces/{ws}/telegram-places").json()["places"]
    }
    assert labels["-1000021:4"] == "Leads"


def test_member_profiles_directories_count_too(env: Any) -> None:  # noqa: F811
    client, core, _fake, _tg, ws = env
    _hermes_bot(client, core, ws)
    member = core.engine.root(ws) / "profiles" / "a-writer"
    member.mkdir(parents=True)
    _directory(member, [{"id": "-1000011:5", "name": "Writers / Drafts", "thread_id": "5"}])
    rows = [
        (p["address"], p["group"], p["label"])
        for p in client.get(f"/workspaces/{ws}/telegram-places").json()["places"]
    ]
    assert ("-1000011:5", "Writers", "Drafts") in rows


def test_the_old_workspace_telegram_group_is_gone_and_kept_as_a_place() -> None:
    """workspaces.telegram_group/topic had no reader (the web showed it as "Saved
    from before"): the upgrade keeps it as a place to link a chat to, then drops it."""
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    drop = next(i for i, m in enumerate(MIGRATIONS) if "DROP COLUMN telegram_group" in m)
    for sql in MIGRATIONS[:drop]:
        db.executescript(sql)
    db.execute(f"PRAGMA user_version = {drop}")
    at = "2026-01-01T00:00:00Z"
    for ws, group, topic in (
        ("a", "-1001", "7"),
        ("b", "-1002", ""),
        ("c", None, None),
        ("d", "-1004", "9"),
    ):
        db.execute(
            "INSERT INTO workspaces (id, name, telegram_group, telegram_topic, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ws, ws, group, topic, at, at),
        )
    keep = {"-1004": {"name": "Seen", "topics": {"0": "General"}}}
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ("telegram.groups.d", json.dumps(keep), at),
    )
    _migrate(db)
    notes = {
        r["key"]: json.loads(r["value"])
        for r in db.execute("SELECT * FROM app_settings WHERE key LIKE 'telegram.groups.%'")
    }
    assert notes == {
        "telegram.groups.a": {"-1001": {"name": "", "topics": {"0": "", "7": ""}}},
        "telegram.groups.b": {"-1002": {"name": "", "topics": {"0": ""}}},
        "telegram.groups.d": keep,  # already there: untouched
    }
    columns = {r[1] for r in db.execute("PRAGMA table_info(workspaces)")}
    assert not {"telegram_group", "telegram_topic"} & columns


def test_no_workspace_telegram_copy_comes_back() -> None:
    assert "telegram" not in Workspace.model_fields
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    _migrate(db)
    columns = {r[1] for r in db.execute("PRAGMA table_info(workspaces)")}
    assert not [c for c in columns if re.match(r"telegram", c)]
    # Only the gateway_places reader names AGOS's note of what Hermes lacks (plus the
    # migration that made it and the ownership registry, which says why it stays).
    users = [
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if "telegram.groups." in p.read_text()
    ]
    assert sorted(users) == [
        "actions/services/channel/gateway_places.py",
        "db/migrations.py",
        "db/ownership/keys.py",
    ]
    note = ownership.KEYS["telegram.groups.*"]
    assert note.kind == ownership.MOVE_ONCE and "channel_directory.py" in note.hermes
    web = SRC.parents[3] / "apps" / "web" / "src"
    for path in [*web.rglob("*.ts"), *web.rglob("*.tsx")]:
        if path.name == "core-api.d.ts":
            continue
        text = path.read_text()
        assert "Saved from before" not in text and "tgGroup" not in text, path
