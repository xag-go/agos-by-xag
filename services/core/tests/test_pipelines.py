"""Step 59: pipeline rules (F57).

A rule acts once per move: a card moving to its status (Hermes's Kanban hooks
through the bridge, AGOS's own moves, the dispatcher-tick sweep for moves no hook
tells), a review stage's approve or a plan's accept marker. Scope by project/goal
or #label; actions follow-up card (Hermes idempotency key agos-pipe:<rule>:<card>),
comment, assign, run automation, notify; a follow-up never re-triggers its rule.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_search_status import _board, _card
from test_team_hierarchy import _agent

from agos_core.actions import automations, goals, hermes_channel, pipelines
from agos_core.actions.services.board import card_writes, kanban_cli
from agos_core.actions.services.channel import owner_needs


@pytest.fixture
def acted(monkeypatch: Any) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    """Every Hermes write a rule makes (create / comment / assign / run / notify)."""
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def record(name: str, answer: Any = None) -> Any:
        def fn(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args[2:], kwargs))
            return answer

        return fn

    monkeypatch.setattr(card_writes, "create", record("create", "t_new"))
    monkeypatch.setattr(card_writes, "comment", record("comment"))
    monkeypatch.setattr(kanban_cli, "run", record("cli", "{}"))
    monkeypatch.setattr(automations, "run_now", record("run"))
    monkeypatch.setattr(owner_needs, "push", record("push", 1))
    return calls


def _rule(client: Any, ws: str, **body: Any) -> dict[str, Any]:
    r = client.post(f"/workspaces/{ws}/pipelines", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def _event(client: Any, core: Any, ws: str, card: str, path: str = "pipeline-event") -> int:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/{path}",
        json={"card": card} if path == "pipeline-event" else {},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    return int(r.json()["fired"])


def test_a_status_rule_makes_one_follow_up_per_move(env: Any, acted: list[Any]) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "writer")
    db = _board(core, ws)
    _card(db, "t_1", "Launch video #launch", "Cut the teaser.", status="running")
    _card(db, "t_2", "Other video", "No label.", status="running")
    rule = _rule(
        client,
        ws,
        name="Recap after launch",
        trigger="status",
        status="done",
        label="#launch",
        action="follow_up",
        member="writer",
        text="Write the recap of {title}",
    )
    assert rule["label"] == "launch" and rule["enabled"] and rule["lastFiredAt"] is None
    # Still running: no move to done.
    assert _event(client, core, ws, "t_1") == 0
    _card(db, "t_1", "Launch video #launch", "Cut the teaser.", status="done")
    _card(db, "t_2", "Other video", "No label.", status="done")
    assert _event(client, core, ws, "t_1") == 1
    # Hermes fires the same move again (another process): nothing more.
    assert _event(client, core, ws, "t_1") == 0
    assert _event(client, core, ws, "t_2") == 0  # out of scope (no #launch)
    made = [c for c in acted if c[0] == "create"]
    assert len(made) == 1
    title, body, member = made[0][1]
    assert title == "Write the recap of Launch video #launch" and member == "writer"
    assert made[0][2]["once"] == f"agos-pipe:{rule['id']}:t_1"
    assert "Follows card t_1" in body and f"[agos-pipe {rule['id']} from t_1]" in body
    shown = client.get(f"/workspaces/{ws}/pipelines").json()[0]
    assert shown["lastFiredAt"] and "t_new" in shown["lastOutcome"]
    # The follow-up card itself reaching done never makes another one.
    _card(db, "t_new", "Write the recap", body + "\n#launch", status="done")
    assert _event(client, core, ws, "t_new") == 0
    # Moving away and back is a new move.
    _card(db, "t_1", "Launch video #launch", "", status="ready")
    _event(client, core, ws, "t_1")
    _card(db, "t_1", "Launch video #launch", "", status="done")
    assert _event(client, core, ws, "t_1") == 1
    db.close()


def test_the_sweep_finds_moves_no_hook_told_and_old_cards_stay(env: Any, acted: list[Any]) -> None:  # noqa: F811
    client, core, _cron, ws = env
    db = _board(core, ws)
    _card(db, "t_old", "Old review", status="review")
    _rule(client, ws, trigger="status", status="review", action="notify", text="Look at it.")
    # Already in review before the rule: where it stands is no move.
    assert _event(client, core, ws, "", path="pipeline-sweep") == 0
    _card(db, "t_a", "Moved to review", status="todo", at=int(time.time()) - 5)
    _event(client, core, ws, "", path="pipeline-sweep")  # seen in todo
    _card(db, "t_a", "Moved to review", status="review", at=int(time.time()) - 5)
    _card(db, "t_b", "Born after the rule", status="review", at=int(time.time()) + 5)
    assert _event(client, core, ws, "", path="pipeline-sweep") == 2
    assert _event(client, core, ws, "", path="pipeline-sweep") == 0
    told = [c for c in acted if c[0] == "push"]
    assert len(told) == 2 and "Look at it." in told[0][1][0]
    db.close()


def test_review_approve_and_plan_accept_act_once(env: Any, acted: list[Any]) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "editor")
    db = _board(core, ws)
    _card(db, "t_r", "Article", status="review")
    _rule(client, ws, trigger="review_approved", action="comment", text="Approved: {card}")
    _rule(client, ws, trigger="plan_accepted", action="assign", member="editor")
    assert pipelines.after_review(core, ws, "t_r") == 0
    db.execute(
        "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        ("t_r", "a-x", "[agos-review t_r r1 s1: approve] X: fine", 1),
    )
    db.commit()
    assert pipelines.after_review(core, ws, "t_r") == 1
    assert pipelines.after_review(core, ws, "t_r") == 0
    db.execute(
        "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        ("t_r", "owner", "[agos-plan t_r v1: accept] You: accepted. Do the work now.", 2),
    )
    db.commit()
    assert pipelines.after_review(core, ws, "t_r") == 1
    comments = [c for c in acted if c[0] == "comment"]
    assert comments == [("comment", ("t_r", "Approved: t_r"), {})]
    assigns = [c for c in acted if c[0] == "cli" and c[1][:1] == ("assign",)]
    assert len(assigns) == 1 and assigns[0][1][1] == "t_r"
    db.close()


def test_scope_by_project_takes_its_cards_and_its_childrens(env: Any, acted: list[Any]) -> None:  # noqa: F811
    client, core, _cron, ws = env
    goals.set_vision(core, ws, title="Vision", why="", strategy="")
    goal = goals.add_goal(core, ws, title="Grow", why="", owner="")
    other = goals.add_goal(core, ws, title="Other", why="", owner="")
    db = _board(core, ws)
    _card(db, "t_in", "In", f"## Goal\nGoal #{goal} Grow\n\nWork.", status="todo")
    _card(db, "t_out", "Out", f"## Goal\nGoal #{other} Other\n\nWork.", status="todo")
    _rule(client, ws, trigger="status", status="done", goalId=goal, action="notify", text="Done.")
    for card in ("t_in", "t_out"):
        _card(
            db,
            card,
            card,
            str(db.execute("SELECT body FROM tasks WHERE id=?", (card,)).fetchone()[0]),
            status="done",
        )
    fired = _event(client, core, ws, "t_in") + _event(client, core, ws, "t_out")
    assert fired == 1
    db.close()


def test_a_rule_is_checked_before_it_is_kept(env: Any, acted: list[Any]) -> None:  # noqa: F811
    client, _core, _cron, ws = env
    url = f"/workspaces/{ws}/pipelines"
    bad = [
        {"trigger": "status", "status": "nowhere", "action": "notify", "text": "x"},
        {"trigger": "status", "status": "done", "action": "follow_up", "member": "ghost"},
        {"trigger": "status", "status": "done", "action": "comment"},
        {"trigger": "status", "status": "done", "action": "run_automation", "automationId": 999},
        {
            "trigger": "status",
            "status": "done",
            "action": "notify",
            "text": "x",
            "label": "two words",
        },
    ]
    for body in bad:
        assert client.post(url, json=body).status_code == 400, body
    rule = _rule(client, ws, trigger="plan_accepted", action="notify", text="x", status="done")
    assert rule["status"] == ""  # only status rules keep a column
    changed = client.put(
        f"{url}/{rule['id']}",
        json={"trigger": "plan_accepted", "action": "notify", "text": "y", "enabled": False},
    )
    assert changed.status_code == 200 and changed.json()["enabled"] is False
    assert client.delete(f"{url}/{rule['id']}").status_code == 204
    assert client.delete(f"{url}/{rule['id']}").status_code == 404
    assert client.get(url).json() == []


def test_the_guard_tells_every_card_move_and_tick(monkeypatch: Any) -> None:
    from agos_core.hermes_plugin import agos_guard
    from agos_core.hermes_plugin.agos_guard import bridge

    hooks: dict[str, list[Any]] = {}
    posted: list[tuple[str, dict[str, Any]]] = []

    class Ctx:
        def register_hook(self, name: str, fn: Any) -> None:
            hooks.setdefault(name, []).append(fn)

        def __getattr__(self, name: str) -> Any:
            return lambda *a, **k: None

    with contextlib.suppress(Exception):  # the rest of register needs Hermes
        agos_guard.register(Ctx())
    for name in (
        "kanban_task_claimed",
        "kanban_task_completed",
        "kanban_task_blocked",
        "on_kanban_task_updated",
        "on_kanban_dispatch_tick",
    ):
        assert name in hooks, name
    monkeypatch.setattr(bridge, "post", lambda path, body, timeout=30: posted.append((path, body)))
    ours = agos_guard.__name__
    for name, kwargs in (
        ("kanban_task_completed", {"task_id": "t_9", "summary": "ok"}),
        ("on_kanban_task_updated", {"task_id": "t_9", "changed_fields": ["assignee"]}),
        ("on_kanban_dispatch_tick", {"outcome": "ok", "dry_run": False}),
        ("on_kanban_dispatch_tick", {"outcome": "skipped_locked", "dry_run": False}),
    ):
        for fn in hooks[name]:
            if fn.__module__ == ours:  # the pipeline observers (the bridge has its own)
                fn(**kwargs)
    deadline = time.time() + 5
    while len(posted) < 3 and time.time() < deadline:
        time.sleep(0.02)
    assert sorted(p[0] for p in posted) == ["pipeline-event", "pipeline-event", "pipeline-sweep"]
    assert ("pipeline-event", {"card": "t_9"}) in posted
