"""Self-improvement + looking ahead + Autonomy rules (ADR 0016)."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import profile_dir
from test_library import env, turn_on, ws  # noqa: F401  (fixture + helpers)

from agos_core.actions import access, proactive
from agos_core.hermes_plugin.agos_guard import ASK_MARK, action_of, decide

# ---- the guard plugin (runs inside Hermes) ----------------------------------------


def test_guard_reads_are_always_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermes keeps a 'not found' for 60 s (its host-side exists() can't see the
    sandbox) and blocks a 4th read as 'not changed': a watch looking at the same
    file every check must always read the real file."""
    import sys
    import types

    from agos_core.hermes_plugin import agos_guard

    calls: list[str] = []
    fake = types.ModuleType("tools.file_tools_read_tracking")
    fake.notify_other_tool_call = calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools.file_tools_read_tracking", fake)
    agos_guard.fresh_read("read_file", "task-1")
    agos_guard.fresh_read("search_files", "task-1")
    agos_guard.fresh_read("terminal", "task-1")
    assert calls == ["task-1", "task-1"]
    monkeypatch.delitem(sys.modules, "tools.file_tools_read_tracking")
    agos_guard.fresh_read("read_file", "task-2")  # no Hermes module: nothing breaks


def test_guard_rules_per_agent_newest_specific_wins() -> None:
    policy = {"rules": {"*": {"files": "do", "messages": "ask"}, "writer": {"files": "never"}}}
    never = decide(policy, "writer", "write_file", {})
    assert never is not None and never["action"] == "block"
    assert decide(policy, "other", "write_file", {}) is None
    ask = decide(policy, "other", "send_message", {})
    assert ask is not None and ask["action"] == "approve" and ASK_MARK in ask["message"]
    # Reading is never stopped by a rule.
    assert decide(policy, "writer", "read_file", {}) is None


def test_mcp_tools_are_classified_by_verb() -> None:
    assert action_of("mcp_mcc_tasks_list") is None
    assert action_of("mcp_mcc_task_get") is None
    assert action_of("mcp_mcc_task_create") == "apps_change"
    assert action_of("mcp_mcc_task_delete") == "apps_delete"


def test_full_access_never_answers_an_ask_me_rule() -> None:
    assert access.owner_rule({"description": f"{ASK_MARK} Send messages: send_message"})
    assert access.owner_rule({"pattern_key": "plugin_rule:agos:messages"})
    assert not access.owner_rule({"description": "rm -rf in /workspace", "command": "rm -rf x"})


# ---- AGOS side ---------------------------------------------------------------------


def _policy(home: Path, w: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (profile_dir(home, f"agos-{w}") / "agos-guard.json").read_text()
    )
    return data


def test_rules_reach_only_their_workspace_and_plugin_is_on(env: Any) -> None:  # noqa: F811
    client, _core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    r = client.put(
        f"/workspaces/{a}/autonomy", json={"agent": "*", "action": "files", "choice": "never"}
    )
    assert r.status_code == 204
    assert _policy(home, a)["rules"]["*"]["files"] == "never"
    assert _policy(home, b)["rules"]["*"]["files"] == "do"
    assert (profile_dir(home, f"agos-{a}") / "plugins" / "agos-guard" / "__init__.py").is_file()
    assert "agos-guard" in json.loads(runner.config[f"agos-{a}"]["plugins.enabled"])
    view = client.get(f"/workspaces/{a}/autonomy").json()
    assert {x["key"] for x in view["actions"]} >= {"files", "messages", "apps_delete"}
    assert (
        client.put(
            f"/workspaces/{a}/autonomy", json={"agent": "*", "action": "nope", "choice": "do"}
        ).status_code
        == 400
    )


def test_owner_decisions_are_said_to_hermes_which_learns_by_itself(env: Any) -> None:  # noqa: F811
    """His decisions go to the workspace's own learning conversation on its Hermes;
    AGOS writes no memory and adds no lessons to the work (Hermes's review does)."""
    client, core, _runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    proactive.record(core, a, kind="rejected", subject="emoji in titles", detail="no emojis ever")
    from agos_core.actions import hermes_channel, learning

    # Said at once (no loop), once.
    said = hermes_channel.take_inbox(core, a, agos=True)
    texts = [i["text"] for i in said if i["chat"] == learning.ADDRESS and i["kind"] == "message"]
    assert texts == ["The owner rejected: emoji in titles\nHe said: no emojis ever"]
    assert not [i for i in hermes_channel.take_inbox(core, b, agos=True)]  # Beta hears nothing
    memory = profile_dir(home, f"agos-{a}") / "memories" / "MEMORY.md"
    assert not memory.exists() or "emoji" not in memory.read_text()
    # What the conversation is for: its channel prompt (Hermes's), not the turn.
    learn = [i for i in said if i["chat"] == learning.ADDRESS and i["kind"] == "message"]
    assert "memory tool" in learn[0]["channelPrompt"]
    start = hermes_channel.turn_start(core, a, learning.ADDRESS, "s-l")
    assert start["turnId"] == learning.TURN_ID and "context" not in start
    hermes_channel.turn_finish(core, a, learning.TURN_ID, "Noted.")
    # AGOS keeps no copy: "What I learned" lists his decisions from Hermes's own
    # learning conversation (the profile's state.db).
    import sqlite3

    assert "feedback" not in {
        r[0] for r in core.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    state = sqlite3.connect(profile_dir(home, f"agos-{a}") / "state.db")
    state.executescript(
        "CREATE TABLE sessions (id TEXT, session_key TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
        " content TEXT, timestamp REAL);"
        "INSERT INTO sessions VALUES ('s1', 'agent:main:agos:dm:l1'), ('s2', 'agent:main:agos:dm:9');"
    )
    state.executemany(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        [
            ("s1", "user", texts[0], 1791469107.0),
            ("s1", "assistant", "✅", 1791469108.0),
            ("s2", "user", "The owner said: not a decision chat", 1791469109.0),
        ],
    )
    state.commit()
    state.close()
    got = client.get(f"/workspaces/{a}/learned").json()["feedback"]
    assert [(f["kind"], f["subject"], f["detail"]) for f in got] == [
        ("rejected", "emoji in titles", "no emojis ever")
    ]
    assert client.get(f"/workspaces/{b}/learned").json()["feedback"] == []


def _entry(home: Path, entry_id: str, files: dict[str, tuple[str, str]], **more: Any) -> None:
    """One entry of Hermes's skill ledger (tools/skill_ledger.py append_entry): every
    changed file of the skill, sorted by path, as {path, sha256} with its blob."""
    import hashlib

    blobs = home / ".curator_backups" / "blobs"
    blobs.mkdir(parents=True, exist_ok=True)
    folder = home / "skills" / "script-writing"
    before: list[dict[str, str]] = []
    after: list[dict[str, str]] = []
    for rel in sorted(files):
        for side, text in zip((before, after), files[rel], strict=True):
            sha = hashlib.sha256(text.encode()).hexdigest()
            (blobs / sha).write_text(text)
            side.append({"path": str(folder / rel), "sha256": sha})
    ledger = home / "skills" / ".curator_ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": entry_id,
        "ts": "2026-10-02T00:00:00+00:00",
        "actor": "agent",
        "action": "patch",
        "skill": "script-writing",
        "evidence": {"session_id": "x"},
        "before": before,
        "after": after,
        **more,
    }
    with ledger.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def test_learned_shows_ledger_changes_with_text(env: Any) -> None:  # noqa: F811
    """Hermes's ledger read by Hermes's functions: the SKILL.md text by its path (a
    LICENSE or an Assets/ file sorts before it), for the Co-Founder and every member."""
    from test_agent_profiles import add_agent

    from agos_core.actions import agent_profiles

    client, core, _runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    p = profile_dir(home, f"agos-{a}")
    _entry(
        p,
        "abc123abc123",
        {"Assets/LICENSE": ("MIT", "MIT 2"), "SKILL.md": ("old way", "new way")},
    )
    member = core.engine.profile_home(agent_profiles.key(a, "writer"))
    _entry(member, "def456def456", {"SKILL.md": ("draft", "draft, short")})
    got = client.get(f"/workspaces/{a}/learned").json()
    mine = {c["id"]: c for c in got["changes"]}
    assert mine["abc123abc123"]["before"] == "old way"
    assert mine["abc123abc123"]["after"] == "new way"
    assert mine["abc123abc123"]["by"] == "learned by itself"
    assert mine["def456def456"]["after"] == "draft, short"
    assert "Writer" in mine["def456def456"]["by"]
    assert client.post(f"/workspaces/{a}/learned/zzz/undo").status_code == 400
    # A member's change is undone in that member's own Hermes home.
    calls: list[tuple[str, ...]] = []

    def hermes(key: str, *args: str, **_: Any) -> str:
        calls.append((key, *args))
        return ""

    core.engine._hermes = hermes
    assert client.post(f"/workspaces/{a}/learned/def456def456/undo").status_code == 204
    assert calls == [(agent_profiles.key(a, "writer"), "curator", "rollback", "def456def456", "-y")]


def test_learned_reads_the_ledger_with_hermess_functions() -> None:
    """No raw read of Hermes's ledger or blobs left in AGOS."""
    src = Path(proactive.__file__).read_text()
    assert ".curator_ledger.jsonl" not in src and "blobs" not in src
