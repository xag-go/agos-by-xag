"""The owner's Allow once / Deny for a Kanban card can reach AGOS a second before
the card's kanban_block lands (card t_81e17bdd, 2026-10-23: OK at 09:53:15, block
at 09:53:16, stuck). Either way the card goes on with his answer:
- the block comes after his answer is written: the guard refuses the block and the
  worker uses his answer at once;
- the block lands anyway (the guard's check ran just before his answer): Hermes's
  kanban_task_blocked hook tells AGOS, which unblocks it at once."""

import contextlib
import json
import sqlite3
import sys
import time
import types
from typing import Any

import pytest
from test_agent_profiles import add_agent, cofounder_chat
from test_engine_sync import profile_dir
from test_library import env, ws  # noqa: F401 - fixture

CARD = "t_81e17bdd"
LABEL = "Change things in connected apps"
UPLOAD = ("mcp_google_drive_upload_file", {"name": "reel.mp4"})


def _board(core: Any, a: str) -> sqlite3.Connection:
    from agos_core.actions import agent_profiles

    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,"
        " assignee TEXT, status TEXT, block_kind TEXT);"
        "CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY, task_id TEXT,"
        " kind TEXT, payload TEXT, created_at INTEGER);"
    )
    db.execute(
        "INSERT OR REPLACE INTO tasks VALUES (?, 'Upload the reel', '', 'a-editor', 'running', NULL)",
        (CARD,),
    )
    db.commit()
    return db


def _block(db: sqlite3.Connection, reason: str) -> None:
    """What Hermes's block_task writes (status, kind, its 'blocked' event)."""
    db.execute(
        "UPDATE tasks SET status = 'blocked', block_kind = 'needs_input' WHERE id = ?", (CARD,)
    )
    db.execute(
        "INSERT INTO task_events (task_id, kind, payload) VALUES (?, 'blocked', ?)",
        (CARD, json.dumps({"kind": "needs_input", "reason": reason})),
    )
    db.commit()


@pytest.fixture
def team(env: Any, monkeypatch: Any) -> Any:  # noqa: F811
    """A member working CARD under 'Ask me' for app changes; the guard runs in its
    Hermes profile and reaches AGOS through the real bridge endpoints."""
    from agos_core.actions import hermes_channel
    from agos_core.hermes_plugin import agos_guard

    client, core, runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    cofounder_chat(core, a)
    member_home = profile_dir(home, f"agos-{a}--a-editor")
    fake = types.ModuleType("hermes_constants")
    fake.get_hermes_home = lambda: str(member_home)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    key = hermes_channel.bridge_key(core, a)
    posted: list[tuple[str, Any]] = []

    class Bridge:
        agent_of_session = staticmethod(lambda session: "editor")

        @staticmethod
        def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
            r = client.post(
                f"/hermes-bridge/{a}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
            )
            assert r.status_code == 200, r.text
            posted.append((path, r.json()))
            return dict(r.json())

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: Bridge)
    monkeypatch.setenv("HERMES_KANBAN_TASK", CARD)
    policy = {"member": "editor", "rules": {"editor": {"apps_change": "ask"}}}
    return client, core, runner, a, policy, posted, _board(core, a)


def _ask_and_answer(client: Any, core: Any, a: str, policy: Any, allow: bool) -> dict[str, str]:
    from agos_core.actions import kanban_asks
    from agos_core.hermes_plugin import agos_guard

    stop = agos_guard.card_ask(policy, CARD, *UPLOAD)
    assert stop is not None and f"waiting for the owner: {LABEL}" in stop["message"]
    ask = kanban_asks.waiting(core, a)[0]
    r = client.post(f"/workspaces/{a}/kanban-asks/{ask['id']}", json={"allow": allow})
    assert r.status_code == 200, r.text
    return stop


def _unblocks(runner: Any) -> int:
    return sum(1 for c in runner.calls if "kanban" in c and "unblock" in c and CARD in c)


@pytest.mark.parametrize("gap", [0.0, 1.0, 2.0])
def test_an_ok_given_just_before_the_block_is_used_at_once(team: Any, gap: float) -> None:
    """His OK reaches AGOS 0-2 s before the worker blocks: the block is refused and
    the worker does the action now (nothing waits)."""
    from agos_core.hermes_plugin import agos_guard

    client, core, _runner, a, policy, _posted, _db = team
    _ask_and_answer(client, core, a, policy, allow=True)
    time.sleep(gap)
    args = {"kind": "needs_input", "reason": f"waiting for the owner: {LABEL}"}
    verdict, _ = agos_guard._verdict("kanban_block", args, "s1")
    assert verdict is not None and verdict["action"] == "block"
    assert "already allowed" in verdict["message"] and "do it now" in verdict["message"]
    assert agos_guard.card_ask(policy, CARD, *UPLOAD) is None  # the upload runs
    # A block for a different, unanswered wait is Hermes's as usual.
    other = {"kind": "needs_input", "reason": "waiting for the owner: Run commands"}
    assert agos_guard._verdict("kanban_block", other, "s1")[0] is None


@pytest.mark.parametrize("gap", [0.0, 1.0, 2.0])
def test_a_block_that_lands_after_the_ok_goes_on_at_once(team: Any, gap: float) -> None:
    """The guard's check ran just before his OK was written, so the block lands
    anyway: Hermes's kanban_task_blocked hook tells AGOS, and the card is unblocked
    at once (it was never resumed before)."""
    from agos_core.hermes_plugin import agos_guard

    client, core, runner, a, policy, posted, db = team
    _ask_and_answer(client, core, a, policy, allow=True)
    before = _unblocks(runner)  # his click's own unblock: the card was still running
    time.sleep(gap)
    reason = f"waiting for the owner: {LABEL}"
    _block(db, reason)
    agos_guard.blocked_for_owner(CARD, reason)
    assert posted[-1] == ("kanban-blocked", {"settled": True})
    assert _unblocks(runner) == before + 1


def test_a_block_waits_while_he_has_not_answered(team: Any) -> None:
    from agos_core.hermes_plugin import agos_guard

    _client, _core, runner, _a, policy, posted, db = team
    agos_guard.card_ask(policy, CARD, *UPLOAD)
    reason = f"waiting for the owner: {LABEL}"
    assert agos_guard._verdict("kanban_block", {"reason": reason}, "s1")[0] is None
    _block(db, reason)
    agos_guard.blocked_for_owner(CARD, reason)
    assert posted[-1] == ("kanban-blocked", {"settled": False})
    assert _unblocks(runner) == 0  # it waits for his Allow once / Deny
    agos_guard.blocked_for_owner(CARD, "Which colour?")  # a question: not told
    assert posted[-1][0] == "kanban-blocked" and len(posted) == 2


def test_a_no_given_just_before_the_block_is_used_too(team: Any) -> None:
    """His Deny arrives first: the card neither blocks nor asks again; a block that
    lands anyway goes on at once (without the action)."""
    from agos_core.hermes_plugin import agos_guard

    client, core, runner, a, policy, posted, db = team
    _ask_and_answer(client, core, a, policy, allow=False)
    reason = f"waiting for the owner: {LABEL}"
    verdict = agos_guard._verdict("kanban_block", {"reason": reason}, "s1")[0]
    assert verdict is not None and "already said no" in verdict["message"]
    again = agos_guard.card_ask(policy, CARD, *UPLOAD)
    assert again is not None and "said no" in again["message"]
    assert "kanban_block" not in again["message"]
    asks = [p for p in posted if p[0] == "kanban-ask"]
    assert len(asks) == 1  # not asked a second time
    before = _unblocks(runner)
    _block(db, reason)
    agos_guard.blocked_for_owner(CARD, reason)
    assert _unblocks(runner) == before + 1


def test_the_guard_listens_to_hermess_block_hook() -> None:
    from agos_core.hermes_plugin import agos_guard

    hooks: dict[str, Any] = {}

    class Ctx:
        def register_hook(self, name: str, fn: Any) -> None:
            hooks[name] = fn

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    with contextlib.suppress(Exception):  # the rest of register needs Hermes
        agos_guard.register(Ctx())
    assert "kanban_task_blocked" in hooks and "pre_tool_call" in hooks
