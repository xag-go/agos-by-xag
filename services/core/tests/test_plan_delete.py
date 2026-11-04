"""An agent's plan change can delete a goal, a key result or a project for good.

- delete_goal / delete_kr / delete_project (the tool: the same kind with
  `delete: true`): approved, the row is gone (a goal with its key results and
  projects); other goals stay.
- An update whose status says "deleted" (what the Co-Founder wrote before this
  existed, refused on approve with "A goal is active, paused, done or dropped") is
  read as the delete: shown so in the Inbox and approved as is, also for a card
  already waiting.
- A made-up status is refused when the agent proposes, not when the owner approves.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_vision import _bridge, pushed, space  # noqa: F401 - fixtures

from agos_core.actions import goals, proposals
from agos_core.actions.errors import ActionError
from agos_core.engine import goals as goal_rules
from agos_core.engine import proposals as rules


def _plan(core: Any, ws: str) -> tuple[int, int, int, int]:
    goals.set_vision(core, ws, title="Grow")
    goal = goals.add_goal(core, ws, title="Audience")
    project = goals.add_project(core, ws, goal, title="Reels")
    goals.add_result(core, ws, goal, title="10k followers", target=10_000, unit="followers")
    kept = goals.add_goal(core, ws, title="Revenue")
    goals.add_result(core, ws, kept, title="5k MAD", target=5000, unit="MAD")
    return goal, project, kept, len(_rows(core, ws))


def _rows(core: Any, ws: str) -> list[tuple[str, int]]:
    out = [
        ("goal", int(r["id"]))
        for r in core.db.execute(
            "SELECT id FROM goals WHERE workspace_id = ? AND parent_id IS NOT NULL", (ws,)
        )
    ]
    out += [
        ("kr", int(r["goal_id"]))
        for r in core.db.execute("SELECT goal_id FROM key_results WHERE workspace_id = ?", (ws,))
    ]
    return out


def _approve(client: Any, ws: str, ask_id: int) -> Any:
    return client.post(f"/workspaces/{ws}/proposals/{ask_id}", json={"choice": "approve"})


def test_the_statuses_match_the_goals_rules() -> None:
    assert rules.ITEM_STATUSES == goal_rules.STATUSES


def test_an_agent_deletes_a_goal_with_its_key_results_and_projects(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
) -> None:
    client, core, _cron, ws = space
    goal, project, kept, _ = _plan(core, ws)
    answer = _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "goal",
            "payload": {"goal_id": goal, "delete": True, "why": "The owner asked."},
        },
    )
    assert "error" not in answer, answer
    [shown] = proposals.waiting(core, ws)
    assert shown["payload"]["change"] == "delete_goal"
    assert "delete" not in shown["payload"]
    assert shown["label"] == f"Delete goal #{goal}"
    r = _approve(client, ws, shown["id"])
    assert r.status_code == 200, r.text
    assert _rows(core, ws) == [("goal", kept), ("kr", kept)]
    assert project not in [i for _k, i in _rows(core, ws)]


def test_a_status_deleted_is_the_delete_also_for_a_card_already_waiting(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
) -> None:
    client, core, _cron, ws = space
    goal, _project, kept, _ = _plan(core, ws)
    other = goals.add_goal(core, ws, title="Community")
    for goal_id in (goal, other):
        answer = _bridge(
            client,
            core,
            ws,
            {
                "action": "propose",
                "kind": "goal",
                "payload": {
                    "goal_id": goal_id,
                    "title": "Audience",
                    "status": "deleted",
                    "why": "Sam asked: delete all goals.",
                },
            },
        )
        assert "error" not in answer, answer
    first, second = proposals.waiting(core, ws)
    assert first["payload"]["change"] == "delete_goal"
    assert "status" not in first["payload"]
    # The second as the old code stored it: an update with status "deleted".
    old = {**second["payload"], "change": "update_goal", "status": "deleted"}
    core.db.execute(
        "UPDATE kanban_asks SET payload = ?, label = ? WHERE id = ?",
        (json.dumps(old), f"Change goal #{other}: Audience", second["id"]),
    )
    [_, again] = proposals.waiting(core, ws)
    assert again["payload"]["change"] == "delete_goal"
    assert again["label"] == f"Delete goal #{other}: Audience"
    for ask in (first, again):
        r = _approve(client, ws, ask["id"])
        assert r.status_code == 200, r.text
    assert _rows(core, ws) == [("goal", kept), ("kr", kept)]


def test_a_key_result_and_a_project_are_deleted_and_a_made_up_status_is_refused(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
) -> None:
    client, core, _cron, ws = space
    goal, project, kept, _ = _plan(core, ws)
    [kr] = [
        int(r["id"])
        for r in core.db.execute("SELECT id FROM key_results WHERE goal_id = ?", (goal,))
    ]
    refused = _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "goal",
            "payload": {"goal_id": goal, "status": "sleeping", "why": "Later."},
        },
    )
    assert "active, paused, done or dropped" in str(refused.get("error")), refused
    assert "delete_goal" in str(refused.get("error"))
    for kind, payload in (("kr", {"kr_id": kr}), ("project", {"project_id": project})):
        answer = _bridge(
            client,
            core,
            ws,
            {
                "action": "propose",
                "kind": kind,
                "payload": {**payload, "delete": True, "why": "Not needed."},
            },
        )
        assert "error" not in answer, answer
    asks = proposals.waiting(core, ws)
    assert [a["payload"]["change"] for a in asks] == ["delete_kr", "delete_project"]
    for ask in asks:
        r = _approve(client, ws, ask["id"])
        assert r.status_code == 200, r.text
    assert sorted(_rows(core, ws)) == [("goal", goal), ("goal", kept), ("kr", kept)]


def test_an_approve_that_fails_leaves_the_proposal_waiting(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before: the approve's marker stayed on the card, so his next click (Reject)
    read the card as approved and the row became 'approved' with nothing made."""
    client, core, _cron, ws = space
    goal, _project, kept, _ = _plan(core, ws)
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "goal",
            "payload": {"goal_id": goal, "delete": True, "why": "The owner asked."},
        },
    )
    [shown] = proposals.waiting(core, ws)
    real = goals.apply_change

    def broken(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ActionError("A goal is active, paused, done or dropped.")

    monkeypatch.setattr(goals, "apply_change", broken)
    r = _approve(client, ws, shown["id"])
    assert r.status_code >= 400 and "dropped" in r.text
    [still] = proposals.waiting(core, ws)
    assert still["status"] == "waiting"
    monkeypatch.setattr(goals, "apply_change", real)
    r = _approve(client, ws, shown["id"])  # the same click again now goes through
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert _rows(core, ws) == [("goal", kept), ("kr", kept)]


def test_a_failed_approve_can_still_be_rejected(
    space: Any,  # noqa: F811
    pushed: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _cron, ws = space
    goal, *_ = _plan(core, ws)
    _bridge(
        client,
        core,
        ws,
        {
            "action": "propose",
            "kind": "goal",
            "payload": {"goal_id": goal, "delete": True, "why": "The owner asked."},
        },
    )
    [shown] = proposals.waiting(core, ws)

    def broken(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise ActionError("nope")

    monkeypatch.setattr(goals, "apply_change", broken)
    assert _approve(client, ws, shown["id"]).status_code >= 400
    r = client.post(f"/workspaces/{ws}/proposals/{shown['id']}", json={"choice": "reject"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert ("goal", goal) in _rows(core, ws)
