"""A room's members are Hermes's (its hosted-room row, reported by the plugin with
every room-next); AGOS's master is the group's members alone (step 26, audit B-3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from test_hermes_roots import roots_env  # noqa: F401 - fixture
from test_rooms import _bridge, _jobs, _say, group  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, rooms
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


def _held(
    client: Any, core: Any, ws: str, room: str, members: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """The plugin tells what Hermes's room holds; the jobs room-next hands back."""
    body = {"rooms": {room: {"pending": [], "members": members}}}
    answer = _bridge(client, core, ws, "room-next", body)
    assert answer.status_code == 200
    items: list[dict[str, Any]] = answer.json().get("items") or []
    return [j["job"] for j in items if j["kind"] == "room-sync"]


def _syncs(core: Any, ws: str) -> list[dict[str, Any]]:
    return [j["job"] for j in _jobs(core, ws) if j["kind"] == "room-sync"]


def _as_hermes_keeps(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hermes's row: its own target added, display names stripped."""
    return [
        {
            **m,
            "display_name": f" {m['display_name']} ",
            "target": {"kind": "local", "profile": m["profile"]},
        }
        for m in members
    ]


def test_hermess_members_decide_whether_the_room_is_made_again(
    group: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    made = _syncs(core, ws)[0]
    room = made["room_id"]
    # Hermes holds the room with the roster it was made with: nothing to do.
    assert _held(client, core, ws, room, _as_hermes_keeps(made["members"])) == []
    assert _syncs(core, ws) == []
    # The core restarts: until told again, the room is taken as it is.
    rooms.forget(core)
    monkeypatch.setattr(agent_profiles, "ready", lambda _c, w, a: w == ws and a == "writer")
    with transaction(core.db):
        chats_repo.set_members(core.db, ws, chat, ["writer"])
    rooms.members_changed(core, ws, chat)
    assert _syncs(core, ws) == []
    # Told: Hermes's room still has the editor, so it is made again (g2).
    again = _held(client, core, ws, room, _as_hermes_keeps(made["members"])) + _syncs(core, ws)
    assert [(j["room_id"], j["disband"]) for j in again] == [(f"agos-c{chat}-g2", room)]
    assert [m["handle"] for m in again[0]["members"]] == ["cofounder", "writer"]


def test_a_room_hermes_doesnt_hold_is_left_to_its_sync(group: Any) -> None:  # noqa: F811
    client, core, ws, chat = group
    _say(core, ws, chat, "first")
    room = _syncs(core, ws)[0]["room_id"]
    assert _held(client, core, ws, room, None) == []
    assert _syncs(core, ws) == []  # the room-sync job still carries the members


def test_no_copy_of_the_rooms_members_comes_back(tmp_path: Path) -> None:
    """Guard: group_rooms has no roster, and nothing outside the migrations names it."""
    from agos_core.db.connection import open_database

    db = open_database(tmp_path / "agos.db")
    columns = {r[1] for r in db.execute("PRAGMA table_info(group_rooms)")}
    assert "roster" not in columns and "members" not in columns, columns
    for path in SRC.rglob("*.py"):
        if path.name == "migrations.py":
            continue
        text = path.read_text()
        assert not re.search(r"\[\"roster\"\]|\broster\s*=\s*excluded|, roster,", text), path
