"""AGOS's own tools (agos_action, agos_capability) called with no chat: from a
Kanban card's worker (Hermes's dispatcher gives it HERMES_KANBAN_TASK), from an
automation's run (Hermes's cron) and from a subagent of any of them. Each change
still shows as a card with Undo, in the Co-Founder chat; what needs the owner's
yes waits there for his Approve (nobody is in the run to answer Hermes's card)."""

import json
from typing import Any

import pytest
from test_automations import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import hermes_channel
from agos_core.actions.services.chat import view as chat_view
from agos_core.db import chats as chats_repo

ITEM = {
    "do": "create_automation",
    "name": "Daily ideas",
    "schedule": "0 9 * * *",
    "instructions": "a",
}


def _cofounder_chat(core: Any, ws: str) -> int:
    from agos_core.actions.workers import open_dm

    return int(open_dm(core, ws, None))


def _run_turns(core: Any, chat: int) -> list[Any]:
    return list(
        core.db.execute(
            "SELECT * FROM chat_turns WHERE chat_id = ? AND hermes_run_id LIKE 'run:%' ORDER BY id",
            (chat,),
        )
    )


def test_a_card_worker_changes_things_and_each_change_has_undo(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    chat = _cofounder_chat(core, ws)
    said = hermes_channel.run_actions(core, ws, "kanban:t_e545e37b", [ITEM])
    assert said["results"][0]["status"] == "done", said
    assert [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()] == [
        "Daily ideas"
    ]
    [turn] = _run_turns(core, chat)
    assert turn["hermes_run_id"] == "run:kanban:t_e545e37b" and turn["status"] == "completed"
    # The same card's next call joins its record; another card gets its own.
    more = {"do": "pause_automation", "automation": "Daily ideas"}
    hermes_channel.run_actions(core, ws, "kanban:t_e545e37b", [more])
    hermes_channel.run_actions(core, ws, "kanban:t_other1", [{**more, "do": "resume_automation"}])
    first, second = _run_turns(core, chat)
    assert first["id"] == turn["id"] and second["hermes_run_id"] == "run:kanban:t_other1"
    # The owner sees them in the Co-Founder chat, each on its own (never inside
    # an answer of the chat), with the card's name and Undo.
    shown = [t for t in chat_view.turns_of(core.db, ws, chat) if t.actions]
    assert len(shown) == 2
    assert [a.status for a in shown[0].actions] == ["done", "done"]
    assert any("board card" in a.title for a in shown[0].activity)
    card = shown[0].actions[0]
    assert card.can_undo
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card.id}", json={"choice": "undo"})
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert client.get(f"/workspaces/{ws}/automations").json() == [] and cron.jobs == {}


def test_a_card_acts_while_the_cofounder_is_answering(env: Any) -> None:  # noqa: F811
    # The chat holds one live turn at a time: a card's record made as a live turn
    # was refused while he answered, and the card's worker got "AGOS can't be reached".
    client, core, _cron, ws = env
    chat = _cofounder_chat(core, ws)
    answering = chats_repo.insert_turn(core.db, chat_id=chat, workspace_id=ws, asked_up_to=0)
    said = hermes_channel.run_actions(core, ws, "kanban:t_7dbd46be", [ITEM])
    assert said["results"][0]["status"] == "done", said
    [turn] = _run_turns(core, chat)
    assert turn["status"] == "completed" and turn["id"] != answering
    live = chats_repo.live_turn(core.db, chat)
    assert live is not None and live.id == answering
    assert [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()] == [
        "Daily ideas"
    ]


def test_a_command_in_a_room_while_it_answers_is_kept(env: Any) -> None:  # noqa: F811
    # Same rule for a Hermes command typed in a room while the room answers: its
    # "answered by Hermes" record was refused and the command was lost.
    from agos_core.db.connection import transaction

    _client, core, _cron, ws = env
    with transaction(core.db):
        room = chats_repo.insert_chat(
            core.db, workspace_id=ws, title="Room", channel="web", kind="group", members=[]
        )
    answering = chats_repo.insert_turn(core.db, chat_id=room, workspace_id=ws, asked_up_to=0)
    with transaction(core.db):
        hermes_channel._answered_by_hermes(core, ws, room, 7)
    rows = core.db.execute(
        "SELECT id, status, asked_up_to FROM chat_turns WHERE chat_id = ? ORDER BY id", (room,)
    ).fetchall()
    assert [(r["status"], r["asked_up_to"]) for r in rows[1:]] == [("completed", 7)]
    live = chats_repo.live_turn(core.db, room)
    assert live is not None and live.id == answering


def test_an_automations_run_acts_too(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    chat = _cofounder_chat(core, ws)
    said = hermes_channel.run_actions(core, ws, "cron:abc123def456", [ITEM])
    assert said["results"][0]["status"] == "done", said
    [turn] = _run_turns(core, chat)
    assert turn["hermes_run_id"] == "run:cron:abc123def456"
    [shown] = [t for t in chat_view.turns_of(core.db, ws, chat) if t.actions]
    assert any("scheduled run" in a.title or "automation" in a.title for a in shown.activity)


def test_in_ask_mode_a_run_leaves_it_for_his_approve(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _cofounder_chat(core, ws)
    assert client.put("/cofounder-actions/mode", json={"mode": "ask"}).json() == {"mode": "ask"}
    # Hermes's Allow / Deny can't be answered in a run: not asked there...
    check = hermes_channel.tool_check(core, "agos_action", {"actions": [ITEM]}, ws, "kanban:t_x1")
    assert check["ask"] is False
    # ...the card waits for his Approve instead, and nothing is done before it.
    said = hermes_channel.run_actions(core, ws, "kanban:t_x1", [ITEM])
    [result] = said["results"]
    assert result["status"] == "proposed" and "don't send it again" in result["waiting"]
    assert client.get(f"/workspaces/{ws}/automations").json() == []
    row = core.db.execute("SELECT id, status FROM cofounder_actions").fetchone()
    assert row["status"] == "proposed"
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{row['id']}", json={"choice": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()] == [
        "Daily ideas"
    ]


def test_the_bridge_takes_a_cards_address(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _cofounder_chat(core, ws)
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/actions",
        json={"chat": "kanban:t_e545e37b", "actions": [ITEM]},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "done", r.text
    bad = client.post(
        f"/hermes-bridge/{ws}/actions",
        json={"chat": "kanban:../x", "actions": [ITEM]},
        headers={"authorization": f"Bearer {key}"},
    )
    assert bad.status_code == 422


def test_no_cofounder_chat_still_says_so(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    core.db.execute("DELETE FROM chats WHERE workspace_id = ?", (ws,))
    said = hermes_channel.run_actions(core, ws, "kanban:t_x2", [ITEM])
    assert "nothing was done" in said["error"]


# ---- the plugin: where a call comes from -------------------------------------------


def _bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    from agos_core.hermes_plugin.agos_guard import bridge

    monkeypatch.setattr(
        bridge, "bridge", lambda: {"core": "http://127.0.0.1:8766", "workspace": "w", "key": "k"}
    )
    monkeypatch.setattr(bridge, "_busy", {})
    monkeypatch.setattr(bridge, "_parents", {})
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    return bridge


def test_a_dispatcher_spawned_worker_calls_from_its_card(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(monkeypatch)
    sent: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any], wait: float) -> tuple[dict[str, Any], bool]:
        sent.append((path, body))
        return {"results": []}, False

    monkeypatch.setattr(bridge, "_post", post)
    # No chat and no card: refused as before.
    said = json.loads(bridge.action_tool({"actions": [ITEM]}, session_id="s1"))
    assert said == {"error": "AGOS can't tell which chat this is; nothing was done."}
    assert sent == []
    # Hermes's dispatcher gave this worker its card.
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_e545e37b")
    assert json.loads(bridge.action_tool({"actions": [ITEM]}, session_id="s1")) == {"results": []}
    assert json.loads(bridge.capability_tool({"kind": "skill", "name": "x"}, session_id="s1"))
    assert [(p, b["chat"]) for p, b in sent] == [
        ("actions", "kanban:t_e545e37b"),
        ("capability", "kanban:t_e545e37b"),
    ]
    # Something that isn't a card id is never sent.
    monkeypatch.setenv("HERMES_KANBAN_TASK", "../etc")
    assert bridge._address_of_session("s1") is None


def test_a_subagent_acts_from_its_parents_place(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(monkeypatch)
    bridge._busy[("parent", "1")] = "agos:12"
    # Hermes's subagent_start hook, through the plugin's registration.
    from agos_core.hermes_plugin import agos_guard

    hooks: dict[str, Any] = {}

    class Ctx:
        def register_hook(self, name: str, fn: Any) -> None:
            hooks[name] = fn

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: bridge)
    agos_guard.register(Ctx())
    hooks["subagent_start"](parent_session_id="parent", child_session_id="child", child_goal="g")
    hooks["subagent_start"](parent_session_id="child", child_session_id="grandchild")
    assert bridge._address_of_session("child") == "agos:12"
    assert bridge._address_of_session("grandchild") == "agos:12"
    # A child of an automation's run acts from that run.
    hooks["subagent_start"](parent_session_id="cron_abc_20261028_0900", child_session_id="c2")
    assert bridge._address_of_session("c2") == "cron:abc"
    # A loop never hangs.
    bridge._parents.update({"a": "b", "b": "a"})
    assert bridge._address_of_session("a") is None
    assert MODEL  # the fixture module's model (kept imported)
