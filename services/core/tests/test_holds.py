"""A subtree hold: Pause parks the dispatchable cards of a card's subtree (Hermes's
`kanban schedule`), Resume releases exactly those still parked, Cancel archives
the open ones; one hold row records what each did."""

from __future__ import annotations

from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_blocked import board, card
from test_library import env, ws  # noqa: F401 - fixture
from test_proposals import _profile

from agos_core.actions import holds


@pytest.fixture
def team(env: Any) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "editor")
    return client, core, runner, a


def _tree(core: Any, a: str) -> dict[str, str]:
    """root -> (todo a, ready b -> (running c, blocked d), done e); outsider x."""
    db = board(core, a)
    spec = {
        "root": ("ready", ()),
        "a": ("todo", ("root",)),
        "b": ("ready", ("root",)),
        "c": ("running", ("b",)),
        "d": ("blocked", ("b",)),
        "e": ("done", ("root",)),
        "x": ("ready", ()),
    }
    for card_id, (status, parents) in spec.items():
        card(
            db, card_id, status, parents=parents, kind="needs_input" if status == "blocked" else ""
        )
    db.close()
    cards = core.engine.runner.kanban.setdefault(_profile(core, a), {})
    for card_id, (status, _parents) in spec.items():
        cards[card_id] = {
            "id": card_id,
            "title": card_id,
            "body": "",
            "status": status,
            "comments": [],
        }
    return {k: v[0] for k, v in spec.items()}


def _sync(core: Any, a: str) -> None:
    """The board file follows the fake CLI's statuses (what the next read sees)."""
    db = board(core, a)
    for card_id, held in core.engine.runner.kanban[_profile(core, a)].items():
        db.execute("UPDATE tasks SET status = ? WHERE id = ?", (held["status"], card_id))
    db.commit()
    db.close()


def test_pause_parks_only_the_dispatchable_cards_of_the_subtree(team: Any) -> None:
    client, core, runner, a = team
    _tree(core, a)
    r = client.post(f"/workspaces/{a}/kanban/root/hold", json={"action": "pause"})
    assert r.status_code == 200, r.text
    hold = r.json()
    assert hold["action"] == "pause" and hold["card"] == "root"
    assert sorted(h["card"] for h in hold["held"]) == ["a", "b", "root"]
    assert {h["card"]: h["was"] for h in hold["held"]} == {
        "root": "ready",
        "a": "todo",
        "b": "ready",
    }
    assert hold["left"] == ["c", "d"]  # running and blocked: untouched, said so
    cards = runner.kanban[_profile(core, a)]
    assert cards["root"]["status"] == cards["a"]["status"] == cards["b"]["status"] == "scheduled"
    assert cards["c"]["status"] == "running" and cards["d"]["status"] == "blocked"
    assert cards["x"]["status"] == "ready"  # not in the subtree
    schedules = [c for c in runner.calls if "kanban" in c and "schedule" in c]
    assert len(schedules) == 3 and all("Paused by the owner" in c[-1] for c in schedules)
    # The Board shows the open pause on the root card.
    _sync(core, a)
    shown = {c["id"]: c for c in client.get(f"/workspaces/{a}/kanban").json()["cards"]}
    assert shown["root"]["holdId"] == hold["id"] and shown["a"]["holdId"] is None


def test_resume_releases_exactly_what_the_pause_held(team: Any) -> None:
    client, core, runner, a = team
    _tree(core, a)
    hold = client.post(f"/workspaces/{a}/kanban/root/hold", json={"action": "pause"}).json()
    cards = runner.kanban[_profile(core, a)]
    # Meanwhile the owner moved one held card himself, and scheduled an outsider.
    cards["a"]["status"] = "archived"
    cards["x"]["status"] = "scheduled"
    _sync(core, a)
    r = client.post(f"/workspaces/{a}/kanban/holds/{hold['id']}/resume")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["released"]) == ["b", "root"] and r.json()["releasedAt"]
    assert cards["root"]["status"] == cards["b"]["status"] == "ready"
    assert cards["a"]["status"] == "archived" and cards["x"]["status"] == "scheduled"
    # Resumed again: nothing more (no second unblock).
    unblocks = len([c for c in runner.calls if "kanban" in c and "unblock" in c])
    again = client.post(f"/workspaces/{a}/kanban/holds/{hold['id']}/resume")
    assert again.status_code == 200 and again.json()["released"] == []
    assert len([c for c in runner.calls if "kanban" in c and "unblock" in c]) == unblocks
    assert holds.open_holds(core, a) == {}


def test_cancel_archives_the_open_subtree_children_first(team: Any) -> None:
    client, core, runner, a = team
    _tree(core, a)
    r = client.post(f"/workspaces/{a}/kanban/root/hold", json={"action": "cancel"})
    assert r.status_code == 200, r.text
    held = r.json()["held"]
    assert sorted(h["card"] for h in held) == ["a", "b", "c", "d", "root"]
    assert [h["card"] for h in held].index("root") > [h["card"] for h in held].index("c")
    cards = runner.kanban[_profile(core, a)]
    assert all(cards[c]["status"] == "archived" for c in ("root", "a", "b", "c", "d"))
    assert cards["e"]["status"] == "done" and cards["x"]["status"] == "ready"
    assert r.json()["left"] == []
    # A cancel is not resumed.
    assert client.post(f"/workspaces/{a}/kanban/holds/{r.json()['id']}/resume").status_code == 409
    assert (
        client.post(f"/workspaces/{a}/kanban/nope/hold", json={"action": "pause"}).status_code
        == 404
    )
