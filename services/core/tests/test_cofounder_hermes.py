"""The Co-Founder changes Hermes's own settings and stores from a chat (the Hermes
settings page, Held-back writes, the key pools, Health): each change is a card whose
Undo puts back the Hermes value it found. Hermes's runtime is stubbed (the fake
runner has none); the runtime scripts were probed against Hermes v0.22.2."""

import json
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_hermes_all_settings import _stub_schema, _value
from test_key_pools import BASE, _fake_hermes
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions, hermes_channel
from agos_core.actions.services.cofounder import agent_tools
from agos_core.db import chats as chats_repo
from agos_core.engine import cofounder_actions as rules
from agos_core.engine.read_cache import ReadCache


def _run(core: Any, ws_id: str, *items: dict[str, Any]) -> list[dict[str, Any]]:
    from agos_core.actions.workers import open_dm

    chat = open_dm(core, ws_id, None)
    turn = chats_repo.insert_turn(
        core.db, chat_id=chat, workspace_id=ws_id, asked_up_to=0, speaker=None
    )
    core.db.execute("UPDATE chat_turns SET status = 'completed' WHERE id = ?", (turn,))
    actions = [a for a in (rules._clean(dict(i)) for i in items) if a is not None]
    assert len(actions) == len(items), items
    for action_id in cofounder_actions.save(core, ws_id, int(chat), turn, actions):
        row = core.db.execute(
            "SELECT * FROM cofounder_actions WHERE id = ?", (action_id,)
        ).fetchone()
        cofounder_actions._run(core, row)
    return [a.model_dump(by_alias=True) for a in cofounder_actions.of_turn(core.db, turn)]


def _undo(core: Any, ws_id: str, card: dict[str, Any]) -> dict[str, Any]:
    return cofounder_actions.decide(core, ws_id, int(card["id"]), "undo").model_dump(by_alias=True)


def test_the_cofounder_changes_a_hermes_setting_and_undo_puts_each_value_back(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    _stub_schema(core)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    # Beta has its own value; the others have none (Hermes's default).
    core.engine._hermes(b, "config", "set", "--force", "checkpoints.max_snapshots", "9")
    assert "change_hermes_setting" in cofounder_actions.instructions(core, a)
    [card] = _run(
        core, a, {"do": "change_hermes_setting", "key": "checkpoints.max_snapshots", "value": "7"}
    )
    assert card["status"] == "done" and card["canUndo"], card
    assert "checkpoints.max_snapshots" in card["title"]
    for key in (a, f"{a}--a-writer", b):
        assert str(_value(core, key, "checkpoints.max_snapshots")) == "7", key
    undone = _undo(core, a, card)
    assert undone["status"] == "undone"
    assert _value(core, a, "checkpoints.max_snapshots") is None
    assert _value(core, f"{a}--a-writer", "checkpoints.max_snapshots") is None
    assert str(_value(core, b, "checkpoints.max_snapshots")) == "9"

    # This workspace only, a boolean, then back to Hermes's default and its Undo.
    [card] = _run(
        core,
        a,
        {
            "do": "change_hermes_setting",
            "key": "checkpoints.enabled",
            "value": True,
            "only_here": True,
        },
    )
    assert card["status"] == "done", card
    assert _value(core, a, "checkpoints.enabled") is True
    assert _value(core, b, "checkpoints.enabled") is None
    [reset] = _run(core, a, {"do": "reset_hermes_setting", "key": "checkpoints.enabled"})
    assert reset["status"] == "done" and _value(core, a, "checkpoints.enabled") is None
    _undo(core, a, reset)
    assert _value(core, a, "checkpoints.enabled") is True

    # An owner's choice among AGOS's recommendations can be changed from chat too.
    [card] = _run(
        core, a, {"do": "change_hermes_setting", "key": "approvals.cron_mode", "value": "deny"}
    )
    assert card["status"] == "done", card
    assert _value(core, a, "approvals.cron_mode") == "deny"
    _undo(core, a, card)
    assert _value(core, a, "approvals.cron_mode") == "approve"

    # What AGOS must keep (or another card owns) is refused, with why.
    [card] = _run(
        core,
        a,
        {"do": "change_hermes_setting", "key": "approvals.mcp_reload_confirm", "value": True},
    )
    assert card["status"] == "failed" and "can't be changed here" in card["error"]
    [shown] = _run(core, a, {"do": "show_hermes_setting", "key": "checkpoints.max_snapshots"})
    assert shown["status"] == "done" and not shown["canUndo"]
    assert "The engine's default: 50" in shown["detail"]


def test_held_writes_are_decided_from_chat_and_undo_takes_it_back(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    queue = [
        {
            "id": "57cacd57",
            "subsystem": "memory",
            "action": "add",
            "summary": "add: likes short reports",
            "origin": "foreground",
            "created_at": 1,
            "target": "memory",
            "detail": "+ likes short reports",
        }
    ]
    decided: list[tuple[str, str, bool, bool]] = []
    undone: list[tuple[str, Any]] = []

    def pending_writes(home: Path) -> dict[str, Any]:
        return {"gates": {"memory": True, "skills": False}, "items": list(queue)}

    def decide_pending(
        home: Path, subsystem: str, pending_id: str, approve: bool, *, keep: bool = False
    ) -> dict[str, Any]:
        decided.append((subsystem, pending_id, approve, keep))
        queue.clear()
        return {
            "found": True,
            "gone": True,
            "text": "Approved 1 memory write(s).",
            "undo": {"before": {"memory": [], "user": []}, "after": {"memory": ["x"], "user": []}},
        }

    def undo_pending(home: Path, subsystem: str, kept: dict[str, Any]) -> dict[str, Any]:
        undone.append((subsystem, kept))
        return {"ok": True}

    core.engine.pending_writes = pending_writes
    core.engine.decide_pending = decide_pending
    core.engine.undo_pending = undo_pending
    [listed] = _run(core, a, {"do": "list_held_writes"})
    assert "57cacd57" in listed["detail"] and "memory: on" in listed["detail"]
    [card] = _run(core, a, {"do": "approve_held_write", "id": "57cacd57"})
    assert card["status"] == "done" and card["canUndo"], card
    assert decided == [("memory", "57cacd57", True, True)]
    assert "Approved 1 memory" in card["detail"]
    _undo(core, a, card)
    assert undone == [
        ("memory", {"before": {"memory": [], "user": []}, "after": {"memory": ["x"], "user": []}})
    ]
    # Hermes refusing the Undo (the memory changed since) is said on the card.
    [card] = _run(core, a, {"do": "approve_held_write", "id": "57cacd57"})
    assert card["status"] == "failed" and "No held write" in card["error"]


def _labels(core: Any) -> list[str]:
    """The keys added here, in Hermes's order (the managed .env's numbered lines)."""
    from agos_core.actions import key_pools

    found = key_pools.read(core)["providers"]
    return [e["label"] for e in found[0]["entries"] if e["movable"]]


def _held(core: Any) -> dict[str, str]:
    from agos_core.engine import config_file

    found = config_file.read_env(core.engine.settings.managed_home)
    return {k: v for k, v in found.items() if k.startswith(BASE)}


def test_the_pool_is_changed_from_chat_and_the_key_is_kept_only_sealed(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    _fake_hermes(core)
    key_one, key_two, key_three = (f"sk-or-v1-{c * 40}" for c in "abc")
    [one, two, three] = _run(
        core,
        a,
        {"do": "add_pool_key", "provider": "openrouter", "key": key_one},
        {"do": "add_pool_key", "provider": "openrouter", "key": key_two},
        {"do": "add_pool_key", "provider": "openrouter", "key": key_three},
    )
    assert {c["status"] for c in (one, two, three)} == {"done"}, (one, two, three)
    k2, k3, k4 = (f"{BASE}_{n}" for n in (2, 3, 4))
    assert _labels(core) == [k2, k3, k4]
    assert _held(core) == {k2: key_one, k3: key_two, k4: key_three}
    # AGOS's database never holds the key as text.
    for row in core.db.execute("SELECT * FROM cofounder_actions").fetchall():
        assert all(k not in str(tuple(row)) for k in (key_one, key_two, key_three))
    # Order: the two lines trade numbers; Undo trades them back.
    [moved] = _run(
        core, a, {"do": "move_pool_key", "provider": "openrouter", "label": k3, "position": 2}
    )
    assert moved["status"] == "done", moved
    assert _held(core) == {k2: key_two, k3: key_one, k4: key_three}
    _undo(core, a, moved)
    assert _held(core) == {k2: key_one, k3: key_two, k4: key_three}
    # Remove renumbers the later lines; Undo puts the same key back at its number.
    [removed] = _run(core, a, {"do": "remove_pool_key", "provider": "openrouter", "label": k2})
    assert removed["status"] == "done", removed
    assert _held(core) == {k2: key_two, k3: key_three}
    for row in core.db.execute("SELECT * FROM cofounder_actions").fetchall():
        assert key_one not in str(tuple(row))
    _undo(core, a, removed)
    assert _held(core) == {k2: key_one, k3: key_two, k4: key_three}
    _undo(core, a, three)  # the add's Undo: its line goes
    assert _held(core) == {k2: key_one, k3: key_two}
    # Never a per-home copy: every home's auth.json is untouched.
    from agos_core.actions import key_pools

    for home in key_pools.homes(core):
        assert key_one not in (
            (home / "auth.json").read_text() if (home / "auth.json").exists() else ""
        )
    [listed] = _run(core, a, {"do": "list_pool_keys"})
    assert k2 in listed["detail"] and key_one not in listed["detail"]


def test_the_pool_strategy_from_chat_and_its_undo_back_to_hermess_default(env: Any) -> None:  # noqa: F811
    from agos_core.actions import hermes_managed

    client, core, runner, _home = env
    a = ws(client, "Alpha")
    _fake_hermes(core)
    [card] = _run(
        core, a, {"do": "set_pool_strategy", "provider": "openrouter", "strategy": "round_robin"}
    )
    assert card["status"] == "done", card
    assert hermes_managed.value(core, "credential_pool_strategies.openrouter") == "round_robin"
    runner.calls.clear()
    _undo(core, a, card)  # it had none: Hermes's own unset, not a copy of its default
    assert any("unset" in c and "credential_pool_strategies.openrouter" in c for c in runner.calls)
    assert hermes_managed.value(core, "credential_pool_strategies.openrouter") is None
    [bad] = _run(core, a, {"do": "set_pool_strategy", "provider": "openrouter", "strategy": "x"})
    assert bad["status"] == "failed" and "Choose one of" in bad["error"]


def test_hermes_health_is_hermess_own_status_and_doctor(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    asked: list[tuple[str, str]] = []

    def hermes_check(workspace_id: str, command: str, *, timeout: float = 180) -> tuple[str, int]:
        asked.append((workspace_id, command))
        if command == "doctor":
            return (
                "◆ Configuration Files\n  ✗ .env file missing\n  ⚠ discord.py not installed\n"
                "  ✓ Managed scope active: 42 config key(s), 3 env key(s) pinned by /m",
                1,
            )
        return "◆ Environment\n  Model: claude", 0

    core.engine.hermes_check = hermes_check
    assert client.get("/preferences/hermes-health").status_code == 200  # asked behind
    assert ReadCache.settle(10)
    r = client.get("/preferences/hermes-health")
    assert r.status_code == 200, r.text
    [root] = r.json()["roots"]
    assert root["workspaceId"] == a
    assert root["doctor"]["problems"] == 1 and root["doctor"]["warnings"] == 1
    # #6: yes/no is Hermes's own verdict, doctor's exit code (H: hermes_cli/doctor.py
    # run_doctor: int(bool(issues or manual_issues))); status has none.
    assert root["doctor"]["hasProblems"] is True
    assert root["status"]["hasProblems"] is None
    assert "Managed scope active" in root["doctor"]["text"]
    assert root["status"]["text"].startswith("◆ Environment")
    assert sorted(asked) == [(a, "doctor"), (a, "status")]
    [card] = _run(core, a, {"do": "hermes_health"})
    assert card["status"] == "done" and not card["canUndo"]
    assert "problems: yes" in card["detail"] and "✗ .env file missing" in card["detail"]
    assert "Managed scope active" in card["detail"]


def test_the_health_card_title_never_names_the_engine() -> None:
    """Spec 2026-11-04 (no engine name): the card's title the owner sees says
    "Engine checks", not the engine's name."""
    from agos_core.engine.cofounder_actions import Action, title_of

    title = title_of(Action(do="hermes_health"))
    assert "Engine checks" in title and "Hermes" not in title


def test_doctors_exit_code_decides_yes_or_no_not_the_marks(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    core.engine.hermes_check = lambda ws_id, command, timeout=180: ("  ✗ a mark, but passed", 0)
    client.get("/preferences/hermes-health")  # asked behind the page
    assert ReadCache.settle(10)
    [root] = client.get("/preferences/hermes-health").json()["roots"]
    assert root["doctor"]["hasProblems"] is False and root["doctor"]["problems"] == 1


def test_the_tool_answer_carries_the_report(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    core.engine.hermes_check = lambda ws_id, command, timeout=180: ("  ✓ fine", 0)
    from agos_core.actions.workers import open_dm

    chat = open_dm(core, a, None)
    turn = chats_repo.insert_turn(
        core.db, chat_id=chat, workspace_id=a, asked_up_to=0, speaker=None
    )
    monkeypatch.setattr(agent_tools, "_chat_turn", lambda *_a: (int(chat), turn))
    out = hermes_channel.run_actions(core, a, "agos:1", [{"do": "hermes_health"}])
    assert out["results"][0]["status"] == "done"
    assert "problems: no" in out["results"][0]["report"]


def test_a_sealed_pool_key_is_dropped_once_hermes_holds_it(env: Any) -> None:  # noqa: F811
    """The sealed key of an "add pool key" card goes once the card is done or
    declined; a removed key's sealed copy (for its Undo) goes once the Undo put it
    back. Hermes's managed .env holds it then; AGOS keeps no copy."""

    def sealed(card: dict[str, Any]) -> tuple[Any, Any]:
        row = core.db.execute(
            "SELECT payload, result FROM cofounder_actions WHERE id = ?", (card["id"],)
        ).fetchone()
        return (
            json.loads(row["payload"] or "{}").get("key_sealed"),
            json.loads(row["result"] or "{}").get("sealed"),
        )

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    _fake_hermes(core)
    [added] = _run(
        core, a, {"do": "add_pool_key", "provider": "openrouter", "key": f"sk-or-v1-{'a' * 40}"}
    )
    assert added["status"] == "done", added
    assert sealed(added) == (None, None)
    # Declined: never added, nothing kept.
    actions = [rules._clean({"do": "add_pool_key", "provider": "openrouter", "key": "sk-x" * 10})]
    assert actions[0] is not None
    chat = core.db.execute("SELECT chat_id, turn_id FROM cofounder_actions").fetchone()
    [declined] = cofounder_actions.save(
        core, a, int(chat["chat_id"]), int(chat["turn_id"]), [actions[0]]
    )
    assert sealed({"id": declined})[0]  # waiting for the owner: the key is needed
    cofounder_actions.decide(core, a, declined, "reject")
    assert sealed({"id": declined}) == (None, None)
    # A removed key: kept sealed for the Undo while the card is done, gone once undone.
    k2 = f"{BASE}_2"
    [removed] = _run(core, a, {"do": "remove_pool_key", "provider": "openrouter", "label": k2})
    assert removed["status"] == "done" and sealed(removed)[1], removed
    _undo(core, a, removed)
    assert sealed(removed) == (None, None)
    assert _held(core) == {k2: f"sk-or-v1-{'a' * 40}"}


def test_old_sealed_pool_keys_are_cleared_once(monkeypatch: Any) -> None:
    """Migration 121: the sealed keys older cards kept after they settled go (a done
    or declined add's payload.key_sealed, an undone remove's result.sealed); a card
    still waiting, or a done remove (its Undo needs the key), keeps its own."""
    import sqlite3

    from agos_core.db import connection, hermes_text
    from agos_core.db.migrations import MIGRATIONS

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    hermes_text.install(db)
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS[:120])
    connection._migrate(db)
    db.execute("INSERT INTO workspaces (id, created_at, updated_at) VALUES ('w', 'x', 'x')")
    rows = [
        ("add_pool_key", "done", {"provider": "p", "key_sealed": "S1"}, None),
        ("add_pool_key", "rejected", {"provider": "p", "key_sealed": "S2"}, None),
        ("add_pool_key", "proposed", {"provider": "p", "key_sealed": "S3"}, None),
        ("remove_pool_key", "undone", {"provider": "p"}, {"label": "L", "sealed": "S4"}),
        ("remove_pool_key", "done", {"provider": "p"}, {"label": "L", "sealed": "S5"}),
    ]
    for action, status, payload, result in rows:
        db.execute(
            # The table's name before migration 126 (the Manager is the Co-Founder).
            "INSERT INTO manager_actions (workspace_id, action, title, payload, status, result,"
            " created_at) VALUES ('w', ?, 't', ?, ?, ?, 'x')",
            (action, json.dumps(payload), status, json.dumps(result) if result else None),
        )
    monkeypatch.setattr(connection, "MIGRATIONS", MIGRATIONS)
    connection._migrate(db)
    kept = " ".join(
        str(tuple(r)) for r in db.execute("SELECT payload, result FROM cofounder_actions")
    )
    assert [s for s in ("S1", "S2", "S3", "S4", "S5") if s in kept] == ["S3", "S5"]
    assert '"label": "L"' in kept or '"label":"L"' in kept
