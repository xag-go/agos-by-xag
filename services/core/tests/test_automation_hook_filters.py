"""A webhook automation's Only-if lines are Hermes's own route filters: shown and
changed in AGOS (and by the Co-Founder, with Undo) without a copy, kept when AGOS
rewrites the route, never wiped by a change made from a partial picture, and a
webhook Hermes does not take is never kept in AGOS.

Split out of test_automation_hooks.py (deliveries, the relay and signatures stay there)."""

import json
from typing import Any

import pytest
from test_automation_hooks import SECRET, _matches, hook_on
from test_automation_team import MONDAY_STEPS, create, team  # noqa: F401  (fixture)
from work_env import MODEL, Env, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.actions import hooks


def test_hermess_own_route_conditions_stay_when_agos_rewrites_the_route(team: Env) -> None:  # noqa: F811
    """Which deliveries need work is said in Hermes's route filters (set in Hermes):
    AGOS rewrites only its events filter and keeps every other condition as it is."""
    client, _, core, ws = team
    file = core.engine.profile_home(ws) / hooks.SUBSCRIPTIONS
    aid = create(client, ws, name="Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    hook = hook_on(client, ws, aid, secret=SECRET, events=["spaces.task.moved"])
    name = hook["path"].removeprefix("/webhooks/")
    condition = {"any": [{"field": "payload.data.to.name", "in": ["todo"]}]}
    routes = json.loads(file.read_text())
    routes[name]["filters"].append(condition)
    file.write_text(json.dumps(routes))
    assert hooks.routes(core, ws)[aid].conditions == [condition]
    # The owner changes the events, then turns the automation off and on.
    hook_on(client, ws, aid, events=["spaces.task.moved", "spaces.task.created"])
    hooks.follow(core, ws, aid, on=False)
    hooks.follow(core, ws, aid, on=True)
    route = json.loads(file.read_text())[name]
    assert route["filters"][1:] == [condition]
    assert route["filters"][0]["any"][0]["in"] == ["spaces.task.created", "spaces.task.moved"]
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["hook"]["events"] == ["spaces.task.created", "spaces.task.moved"]


def test_only_if_lines_are_hermess_filters_shown_and_changed_in_agos(team: Env) -> None:  # noqa: F811
    """The owner's "Only if" lines are Hermes's route filters: written there, read back
    from there, and a delivery none of them lets through starts nothing."""
    client, _, core, ws = team
    file = core.engine.profile_home(ws) / hooks.SUBSCRIPTIONS
    aid = create(client, ws, name="Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    lines = [
        {"when": "spaces.task.moved", "field": "data.to.name", "op": "is", "values": ["todo"]},
        {"when": None, "field": "data.movedBy", "op": "not_contains", "values": ["via MCP"]},
        {"when": None, "field": "data.boardId", "op": "is_not", "values": ["other"]},
    ]
    hook = hook_on(client, ws, aid, secret=SECRET, events=["spaces.task.moved"], conditions=lines)
    assert hook["conditions"] == lines and hook["otherFilters"] == 0
    name = hook["path"].removeprefix("/webhooks/")
    route = json.loads(file.read_text())[name]
    assert len(route["filters"]) == 4  # the events, then one Hermes filter per line
    # A filter set in Hermes in another shape stays, counted, never shown as a line.
    other = {"all": [{"field": "payload.x", "equals": 1}]}
    route["filters"].append(other)
    file.write_text(json.dumps({**json.loads(file.read_text()), name: route}))
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert got["conditions"] == lines and got["otherFilters"] == 1

    def moved(to: str, by: str = "Sam", board: str = "b1") -> dict[str, Any]:
        return {
            "event": "spaces.task.moved",
            "x": 1,
            "data": {"to": {"name": to}, "movedBy": by, "boardId": board},
        }

    route = json.loads(file.read_text())[name]
    ok = [
        m
        for m in (
            moved("todo"),
            moved("choose"),
            moved("todo", "Sam via MCP"),
            moved("todo", board="other"),
        )
        if all(_matches(f, m) for f in route["filters"])
    ]
    assert ok == [moved("todo")]
    # Saved without lines said: they stay; with an empty list: gone (the Hermes one stays).
    hook_on(client, ws, aid, events=["spaces.task.moved"])
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]["conditions"] == lines
    hook_on(client, ws, aid, events=["spaces.task.moved"], conditions=[])
    route = json.loads(file.read_text())[name]
    assert route["filters"][1:] == [other]
    bad = client.post(
        f"/workspaces/{ws}/automations/{aid}/hook",
        json={"on": True, "conditions": [{"field": "data.x", "op": "is", "values": [" "]}]},
    )
    assert bad.status_code == 400


def test_the_cofounder_changes_the_only_if_lines_with_undo(team: Env) -> None:  # noqa: F811
    from agos_core.actions import cofounder_actions

    client, _, core, ws = team
    aid = create(client, ws, name="Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    hook_on(client, ws, aid, events=["spaces.task.moved"])
    line = {"when": None, "field": "data.to.name", "op": "is", "values": ["todo", "review"]}
    action = {
        "do": "update_automation",
        "automation": "Watcher",
        "webhook_events": ["spaces.task.moved"],
        "webhook_conditions": [line],
    }
    # Read the way the Co-Founder's agos_action tool is read (its lists must survive).
    from agos_core.engine import cofounder_actions as rules

    read = rules._clean(action)
    assert read is not None and read.fields["webhook_conditions"] == [line]
    result = cofounder_actions._do(core, ws, "update_automation", read.fields)
    hook = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert hook["conditions"] == [line] and hook["events"] == ["spaces.task.moved"]
    # The same change again changes nothing: never a "done" card for it.

    from agos_core.actions.errors import ActionError

    with pytest.raises(ActionError, match="Nothing changed"):
        cofounder_actions._do(core, ws, "update_automation", read.fields)
    cofounder_actions._undo(core, ws, "update_automation", result)
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]["conditions"] == []


def test_the_cofounder_adds_a_value_to_a_line_in_one_event_like_in_chat(team: Env) -> None:  # noqa: F811
    """What a Co-Founder really sent (a new tracker column), end to end:
    the tool's words -> the card -> Hermes's route file."""
    from agos_core.actions import cofounder_actions
    from agos_core.engine import cofounder_actions as rules

    client, _, core, ws = team
    aid = create(client, ws, name="Board Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    hook_on(client, ws, aid, events=["spaces.task.moved", "spaces.task.created"])
    line = {"when": "spaces.task.moved", "field": "data.to.name", "op": "is", "values": ["todo"]}
    client.post(
        f"/workspaces/{ws}/automations/{aid}/hook",
        json={
            "on": True,
            "events": ["spaces.task.moved", "spaces.task.created"],
            "conditions": [line],
        },
    )
    sent = {
        "do": "update_automation",
        "automation": "Board Watcher",
        "webhook": True,
        "webhook_conditions": [
            {
                "when": "spaces.task.moved",
                "field": "data.to.name",
                "op": "is",
                "values": ["todo", "Editing"],
            }
        ],
    }
    read = rules._clean(sent)
    assert read is not None
    cofounder_actions._do(core, ws, "update_automation", read.fields)
    hook = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert hook["conditions"][0]["values"] == ["todo", "Editing"]
    assert sorted(hook["events"]) == ["spaces.task.created", "spaces.task.moved"]
    name = hook["path"].rsplit("/", 1)[-1]
    from agos_core.actions import hooks

    file = core.engine.profile_home(ws) / hooks.SUBSCRIPTIONS
    route = json.loads(file.read_text())[name]
    assert "Editing" in json.dumps(route["filters"])


def test_a_webhook_hermes_does_not_take_is_never_kept_in_agos(team: Env) -> None:  # noqa: F811
    client, _, core, ws = team

    def refused(*_: Any) -> None:
        from agos_core.engine.hermes import EngineError

        raise EngineError("Hermes did not take the webhook change")

    core.engine.webhook_routes = refused
    body = {"name": "Only hook", "instructions": "x", "schedule": "", "model": MODEL}
    r = client.post(
        f"/workspaces/{ws}/automations", json={**body, "steps": MONDAY_STEPS, "hook": True}
    )
    assert r.status_code == 503 and "webhook" in r.text
    assert client.get(f"/workspaces/{ws}/automations").json() == []  # not made at all


FIVE_LINES: list[dict[str, Any]] = [
    {"when": "spaces.task.moved", "field": "data.to.name", "op": "is", "values": ["todo", "final"]},
    {"when": "spaces.task.created", "field": "data.column.name", "op": "is", "values": ["todo"]},
    {"when": None, "field": "data.movedBy", "op": "not_contains", "values": ["via MCP"]},
    {"when": None, "field": "data.createdBy", "op": "not_contains", "values": ["via MCP"]},
    {"when": None, "field": "data.boardId", "op": "is", "values": ["406d5fd2e731"]},
]


def _watcher(team: Env) -> tuple[Any, Any, str, int]:  # noqa: F811
    client, _, core, ws = team
    aid = create(client, ws, name="Board Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    events = ["spaces.task.created", "spaces.task.moved"]
    r = client.post(
        f"/workspaces/{ws}/automations/{aid}/hook",
        json={"on": True, "events": events, "conditions": FIVE_LINES},
    )
    assert r.status_code == 200, r.text
    return client, core, ws, aid


def _cofounder_does(core: Any, ws: str, action: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions import cofounder_actions
    from agos_core.engine import cofounder_actions as rules

    assert rules.unreadable(action) == []
    read = rules._clean(action)
    assert read is not None
    return cofounder_actions._do(core, ws, read.do, read.fields)


def _lines(client: Any, ws: str, aid: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"][
        "conditions"
    ]
    return lines


def test_a_change_from_a_partial_picture_never_wipes_the_other_lines(team: Env) -> None:  # noqa: F811
    """What really happened: the Co-Founder saw 3 of the 5 lines (a screenshot) and sent
    those 3 with Editing added. The 2 it didn't see must stay."""
    client, core, ws, aid = _watcher(team)
    seen = [dict(line) for line in FIVE_LINES[:3]]
    seen[0]["values"] = ["todo", "final", "Editing"]
    result = _cofounder_does(
        core,
        ws,
        {"do": "update_automation", "automation": "Board Watcher", "webhook_conditions": seen},
    )
    lines = _lines(client, ws, aid)
    assert len(lines) == 5
    assert lines[0]["values"] == ["todo", "final", "Editing"]
    assert lines[3:] == FIVE_LINES[3:]  # the createdBy and board lines stay
    from agos_core.actions import cofounder_actions

    cofounder_actions._undo(core, ws, "update_automation", result)
    assert _lines(client, ws, aid) == FIVE_LINES


def test_add_one_value_remove_one_value_and_drop_one_line(team: Env) -> None:  # noqa: F811
    client, core, ws, aid = _watcher(team)
    moved = {"when": "spaces.task.moved", "field": "data.to.name", "op": "is"}
    _cofounder_does(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": "Board Watcher",
            "webhook_conditions": [
                {**moved, "add_values": ["Editing"], "remove_values": ["final"]}
            ],
        },
    )
    lines = _lines(client, ws, aid)
    assert lines[0]["values"] == ["todo", "Editing"] and lines[1:] == FIVE_LINES[1:]
    _cofounder_does(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": "Board Watcher",
            "remove_webhook_conditions": [
                {"when": None, "field": "data.createdBy", "op": "not_contains"}
            ],
            "webhook_events": ["spaces.task.commented"],
        },
    )
    hook = client.get(f"/workspaces/{ws}/automations/{aid}").json()["hook"]
    assert [c["field"] for c in hook["conditions"]] == [
        "data.to.name",
        "data.column.name",
        "data.movedBy",
        "data.boardId",
    ]
    assert sorted(hook["events"]) == [
        "spaces.task.commented",
        "spaces.task.created",
        "spaces.task.moved",
    ]


def test_the_team_view_shows_the_whole_webhook_to_read_first(team: Env) -> None:  # noqa: F811
    """The Co-Founder reads an automation before changing it: its playbook file has
    every event and every Only-if line, as Hermes holds them."""
    from agos_core.actions import automations as automation_actions
    from agos_core.actions import team_files

    _client, core, ws, aid = _watcher(team)
    text = team_files.automation_file(automation_actions.get(core, ws, aid))
    head = json.loads(text.split("---\n")[1])
    assert head["webhook"]["only_if"] == FIVE_LINES
    assert sorted(head["webhook"]["events"]) == ["spaces.task.created", "spaces.task.moved"]


def test_a_field_agos_does_not_read_fails_and_nothing_is_done() -> None:
    from agos_core.engine import cofounder_actions as rules

    assert rules.unreadable(
        {"do": "update_automation", "automation": "x", "webhook_lines": [{"a": 1}]}
    ) == ["webhook_lines"]
    assert (
        rules.unreadable(
            {
                "do": "update_automation",
                "automation": "x",
                "steps": [],
                "webhook_conditions": [],
                "remove_steps": ["a"],
            }
        )
        == []
    )
