"""Step 48, routines: typed variables filled into the cards and the prompt, a
revision per save with restore, concurrency policies against the open cards, the
run history grouped by run with a derived status, a heartbeat per member as a
Hermes cron job, a task watchdog that wakes once per stop fingerprint, and the
ticket on-ramp presets (Linear / Jira / Asana / GitHub issues → cards)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_automation_hooks import deliver, hook_on
from test_automation_team import MONDAY_STEPS, create, fire, steps_on_board, team
from work_env import MODEL, Env, agent, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.actions import automation_variables, heartbeat, watchdogs
from agos_core.engine import automation_run
from agos_core.engine.cron import automation_prompt, instructions_of

team = team  # the team fixture (researcher + ideas), with a FakeCron

VARIABLES = [
    {"name": "topic", "type": "text", "default": "Argan oil"},
    {"name": "count", "type": "number", "default": "10"},
    {"name": "style", "type": "select", "default": "short", "options": ["short", "long"]},
    {"name": "urgent", "type": "boolean", "default": "no"},
]
STEPS = [
    {
        "key": "research",
        "title": "Research {topic}",
        "agent": "researcher",
        "description": "Find {count} facts on {topic} ({style}). Urgent: {urgent}. Date {run.date}.",
    },
    {
        "key": "ideas",
        "title": "Ideas",
        "agent": "ideas",
        "waits_on": ["research"],
        "description": "{count} ideas.",
    },
]


def _vars(client: Any, ws: str, aid: int) -> list[dict[str, Any]]:
    return list(client.get(f"/workspaces/{ws}/automations/{aid}").json()["variables"])


# ---- variables ---------------------------------------------------------------------------


def test_fill_replaces_known_holes_and_keeps_the_rest() -> None:
    values = {"topic": "Argan", "count": "3"}
    assert automation_run.fill("{count} on {topic}: {unknown} {run.date}", values).startswith(
        "3 on Argan: {unknown} 20"
    )
    payload = {"data": {"title": "Hi", "state": {"type": "done"}, "tags": ["a", "b"]}}
    assert (
        automation_run.fill("{payload.data.title} / {payload.data.state.type}", {}, payload)
        == "Hi / done"
    )
    assert automation_run.fill("{payload.data.nope}", {}, payload) == "{payload.data.nope}"
    # Jira's document (ADF) becomes its words.
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"text": "Fix it"}]}]}
    assert automation_run.render("{d}", {"d": adf}) == "Fix it"
    assert automation_run.render(["{a}", "{b}"], {"b": 7}) == "7"


def test_variables_are_checked_by_type() -> None:
    from agos_core.actions.errors import ActionError

    clean = automation_variables.check_variables(VARIABLES)
    assert [v["name"] for v in clean] == ["topic", "count", "style", "urgent"]
    assert clean[3]["default"] == "no"
    with pytest.raises(ActionError, match="not a number"):
        automation_variables.check_variables([{"name": "n", "type": "number", "default": "x"}])
    with pytest.raises(ActionError, match="needs its options"):
        automation_variables.check_variables([{"name": "s", "type": "select"}])
    with pytest.raises(ActionError, match="listed twice"):
        automation_variables.check_variables([{"name": "a"}, {"name": "a"}])
    from agos_core.db.records import AutomationVariable

    typed = [AutomationVariable.model_validate(v) for v in clean]
    given = automation_variables.check_values(typed, {"count": "5", "urgent": "true"})
    assert given == {"topic": "Argan oil", "count": "5", "style": "short", "urgent": "yes"}
    with pytest.raises(ActionError, match="pick one of"):
        automation_variables.check_values(typed, {"style": "medium"})
    with pytest.raises(ActionError, match="not one of this automation"):
        automation_variables.check_values(typed, {"nope": "1"})


def test_variables_fill_the_cards_of_a_run_and_run_now_may_give_values(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=STEPS, variables=VARIABLES)
    assert [v["name"] for v in _vars(client, ws, aid)] == ["topic", "count", "style", "urgent"]
    cards = fire(core, ws, aid)
    assert cards is not None
    by_step = steps_on_board(core, ws, cards)
    assert by_step["research"]["title"] == "Monday ideas: Research Argan oil"
    body = by_step["research"]["body"]
    assert "Find 10 facts on Argan oil (short). Urgent: no. Date 20" in body
    assert "## Variables of this run\n- topic: Argan oil" in body
    # Run now with values: the manual run dialog's values reach the cards (Hermes's
    # runtime runs the script with them on stdin; the open run is skipped first).
    for card in by_step.values():
        card["status"] = "done"
    r = client.post(
        f"/workspaces/{ws}/automations/{aid}/run",
        json={"variables": {"topic": "Ramadan", "count": "3", "urgent": "yes"}},
    )
    assert r.status_code == 202, r.text
    titles = [c["title"] for c in kanban_of(core, ws).values()]
    assert "Monday ideas: Research Ramadan" in titles
    manual = next(c for c in kanban_of(core, ws).values() if "Ramadan" in c["title"])
    assert "Find 3 facts on Ramadan (short). Urgent: yes." in manual["body"]
    assert ":manual:" in manual["key"]
    # A value of the wrong type is refused before anything runs.
    r = client.post(f"/workspaces/{ws}/automations/{aid}/run", json={"variables": {"count": "x"}})
    assert r.status_code == 400 and "not a number" in r.json()["detail"]


def test_a_webhook_run_fills_payload_fields(team: Env) -> None:
    client, _fake, core, ws = team
    steps = [
        {
            "key": "s",
            "title": "Handle {payload.data.title}",
            "agent": "researcher",
            "description": "Moved to {payload.data.to} by {who}.",
        }
    ]
    aid = create(
        client,
        ws,
        schedule="",
        steps=steps,
        hook=True,
        variables=[{"name": "who", "default": "Tracker"}],
    )
    path = hook_on(client, ws, aid, secret="")["path"]
    payload = {"event": "moved", "data": {"title": "Argan", "to": "todo"}}
    assert deliver(client, path, payload, secret=None).status_code == 200
    (card,) = kanban_of(core, ws).values()
    assert card["title"] == "Monday ideas: Handle Argan"
    assert card["body"].startswith("Moved to todo by Tracker.")


def test_a_one_agent_prompt_keeps_the_holes_and_lists_the_defaults(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, instructions="Write {count} lines on {topic}.", variables=VARIABLES)
    (job,) = core.engine.cron_bridge.jobs.values()
    prompt = job["spec"].prompt
    assert "Write {count} lines on {topic}." in prompt
    assert "## Variables" in prompt and "- topic = Argan oil" in prompt and "- count = 10" in prompt
    # Read back, the prompt is the instructions as written (the one copy).
    assert instructions_of(prompt) == "Write {count} lines on {topic}."
    assert instructions_of(automation_prompt("Plain.")) == "Plain."
    assert (
        client.get(f"/workspaces/{ws}/automations/{aid}").json()["instructions"]
        == "Write {count} lines on {topic}."
    )
    # Run now with other values can't reach a Hermes job's run: said plainly.
    r = client.post(f"/workspaces/{ws}/automations/{aid}/run", json={"variables": {"count": "2"}})
    assert r.status_code == 409 and "default values" in r.json()["detail"]
    assert (
        client.post(
            f"/workspaces/{ws}/automations/{aid}/run", json={"variables": {"count": "10"}}
        ).status_code
        == 202
    )


# ---- revisions ---------------------------------------------------------------------------


def _revisions(client: Any, ws: str, aid: int) -> list[dict[str, Any]]:
    r = client.get(f"/workspaces/{ws}/automations/{aid}/revisions")
    assert r.status_code == 200, r.text
    return list(r.json())


def test_every_save_that_changed_something_is_a_revision_and_restore_is_a_new_save(
    team: Env,
) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS, variables=VARIABLES[:1])
    (v1,) = _revisions(client, ws, aid)
    assert v1["n"] == 1 and v1["who"] == "owner" and v1["snapshot"]["name"] == "Monday ideas"
    assert {c["field"] for c in v1["changes"]} >= {
        "name",
        "instructions",
        "schedule",
        "steps",
        "variables",
    }
    body = {
        "name": "Tuesday ideas",
        "instructions": "Every Monday: 10 video ideas for each of our 3 styles.",
        "schedule": "0 9 * * 2",
        "model": MODEL,
        "on": True,
        "steps": MONDAY_STEPS,
        "variables": [{"name": "topic", "default": "Dates"}],
        "policy": "coalesce_if_active",
    }
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code == 200
    v2, _ = _revisions(client, ws, aid)
    assert v2["n"] == 2 and v2["summary"] == "changed name, schedule, variables, policy"
    changed = {c["field"]: (c["before"], c["after"]) for c in v2["changes"]}
    assert changed["name"] == ("Monday ideas", "Tuesday ideas")
    assert changed["variables"] == ("topic = Argan oil", "topic = Dates")
    assert changed["policy"] == ("skip_if_active", "coalesce_if_active")
    # The same save again: nothing changed, no revision.
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code == 200
    assert len(_revisions(client, ws, aid)) == 2
    # Restore v1: a new save (Hermes's job follows), recorded as a revision.
    r = client.post(f"/workspaces/{ws}/automations/{aid}/revisions/1/restore")
    assert r.status_code == 200, r.text
    v3 = _revisions(client, ws, aid)[0]
    assert v3["n"] == 3 and v3["restoredFrom"] == 1 and v3["summary"] == "restored from v1"
    now = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert now["name"] == "Monday ideas" and now["schedule"] == "0 9 * * 1"
    assert now["variables"][0]["default"] == "Argan oil" and now["policy"] == "skip_if_active"
    (job,) = core.engine.cron_bridge.jobs.values()
    assert job["spec"].name == "Monday ideas" and job["spec"].schedule == "0 9 * * 1"
    assert client.post(f"/workspaces/{ws}/automations/{aid}/revisions/9/restore").status_code == 404
    # The Co-Founder's change never wipes what it doesn't name (variables, policy).
    from test_cofounder_actions import _run

    _run(
        core, ws, {"do": "update_automation", "automation": "Monday ideas", "schedule": "0 8 * * 1"}
    )
    now = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert now["variables"][0]["default"] == "Argan oil" and now["schedule"] == "0 8 * * 1"
    assert _revisions(client, ws, aid)[0]["who"] == "cofounder"
    # It may set variables (by name) and the policy itself.
    _run(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": "Monday ideas",
            "variables": [
                {"name": "topic", "default": "Dates"},
                {"name": "n", "type": "number", "default": "3"},
            ],
            "policy": "always_enqueue",
        },
    )
    now = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert [(v["name"], v["default"]) for v in now["variables"]] == [("topic", "Dates"), ("n", "3")]
    assert now["policy"] == "always_enqueue"
    _run(
        core,
        ws,
        {"do": "update_automation", "automation": "Monday ideas", "remove_variables": ["n"]},
    )
    now = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert [v["name"] for v in now["variables"]] == ["topic"]


# ---- concurrency policies ---------------------------------------------------------------------


def _open_cards(core: Any, ws: str) -> list[dict[str, Any]]:
    return [c for c in kanban_of(core, ws).values() if c["status"] in automation_run.OPEN]


def test_skip_if_active_is_the_default_and_makes_no_new_cards(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS)
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["policy"] == "skip_if_active"
    assert fire(core, ws, aid) is not None
    assert fire(core, ws, aid) is None  # Hermes's own overlap skip, said in the output
    assert len(kanban_of(core, ws)) == 3


def test_coalesce_if_active_comments_the_open_cards_once(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS, policy="coalesce_if_active")
    cards = fire(core, ws, aid)
    assert cards is not None
    assert fire(core, ws, aid) is None
    assert len(kanban_of(core, ws)) == 3
    comments = [c["comments"] for c in kanban_of(core, ws).values()]
    assert all(len(cs) == 1 and cs[0]["body"].startswith("Triggered again at ") for cs in comments)
    # Run now while the run is open: refused with the same words (409).
    r = client.post(f"/workspaces/{ws}/automations/{aid}/run")
    assert r.status_code == 409 and "noted on its open cards" in r.json()["detail"]


def test_always_enqueue_makes_new_cards_after_the_open_run(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS, policy="always_enqueue")
    first = fire(core, ws, aid)
    second = fire(core, ws, aid)
    assert first is not None and second is not None and len(kanban_of(core, ws)) == 6
    last_of_first = steps_on_board(core, ws, first)["check"]["id"]
    assert steps_on_board(core, ws, second)["research"]["parents"] == [last_of_first]


# ---- run history -------------------------------------------------------------------------


def test_run_history_groups_the_cards_by_run_and_derives_the_status(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS, policy="always_enqueue")
    a = fire(core, ws, aid)
    b = fire(core, ws, aid)
    assert a is not None and b is not None
    groups = client.get(f"/workspaces/{ws}/automation-runs").json()
    assert len(groups) == 2 and groups[0]["runId"] > groups[1]["runId"]
    assert {g["status"] for g in groups} == {"waiting"}
    assert groups[1]["automationName"] == "Monday ideas" and len(groups[1]["cards"]) == 3
    assert {c["step"] for c in groups[1]["cards"]} == {"research", "ideas", "check"}
    first = steps_on_board(core, ws, a)
    first["research"]["status"] = "running"
    assert client.get(f"/workspaces/{ws}/automation-runs").json()[1]["status"] == "running"
    first["research"]["status"] = "blocked"
    assert client.get(f"/workspaces/{ws}/automation-runs").json()[1]["status"] == "needs_you"
    for card in first.values():
        card["status"] = "done"
    assert client.get(f"/workspaces/{ws}/automation-runs").json()[1]["status"] == "completed"
    for card in steps_on_board(core, ws, b).values():
        card["status"] = "archived"
    assert client.get(f"/workspaces/{ws}/automation-runs").json()[0]["status"] == "stopped"


# ---- heartbeat per member --------------------------------------------------------------------


def _jobs_in(core: Any, home: str) -> list[dict[str, Any]]:
    return [j for j in core.engine.cron_bridge.jobs.values() if j["home"] == home]


def test_heartbeat_is_a_hermes_cron_job_in_the_members_profile(team: Env) -> None:
    client, _fake, core, ws = team
    from agos_core.actions import agent_profiles

    member_home = str(core.engine.profile_home(agent_profiles.key(ws, "researcher")))
    root_home = str(core.engine.profile_home(ws))
    beats = {h["agent"]: h for h in client.get(f"/workspaces/{ws}/heartbeats").json()}
    assert set(beats) == {"", "researcher", "ideas"} and not any(h["on"] for h in beats.values())
    r = client.put(f"/workspaces/{ws}/heartbeats/researcher", json={"on": True, "interval": "1h"})
    assert r.status_code == 200, r.text
    assert r.json()["on"] and r.json()["interval"] == "1h"
    (job,) = _jobs_in(core, member_home)
    spec = job["spec"]
    assert spec.name == heartbeat.JOB_NAME and spec.schedule == "1h" and spec.enabled
    assert "hermes kanban list --mine" in spec.prompt
    assert "pending questions and proposals" in spec.prompt
    assert "Co-Founder's recent requests" in spec.prompt
    assert "connectors' inboxes" in spec.prompt
    assert "agos_propose" in spec.prompt and "agos_ask_owner" in spec.prompt
    assert "Nothing to do." in spec.prompt and "stay cheap" in spec.prompt
    assert "team's blocked or stalled cards" not in spec.prompt
    # Another interval re-times the same job (no second job).
    client.put(f"/workspaces/{ws}/heartbeats/researcher", json={"on": True, "interval": "daily"})
    (job,) = _jobs_in(core, member_home)
    assert job["spec"].schedule == "0 8 * * *"
    beats = {h["agent"]: h for h in client.get(f"/workspaces/{ws}/heartbeats").json()}
    assert beats["researcher"]["interval"] == "daily"
    # The Co-Founder's own: the root's cron, with the team line.
    r = client.put(f"/workspaces/{ws}/heartbeats/cofounder", json={"on": True, "interval": "4h"})
    assert r.status_code == 200
    (root_job,) = _jobs_in(core, root_home)
    assert "team's blocked or stalled cards" in root_job["spec"].prompt
    assert "workspace goal" in root_job["spec"].prompt and "agos_goals" in root_job["spec"].prompt
    # Last heartbeat: Hermes's executions ledger.
    core.engine.cron_bridge.finish(job["id"], "hb-1", True, "Nothing to do.", 1)
    mine = next(
        h for h in client.get(f"/workspaces/{ws}/heartbeats").json() if h["agent"] == "researcher"
    )
    assert mine["lastAt"] == "2026-09-25T10:00:01+00:00" and mine["lastStatus"] == "ok"
    # Pausing the member pauses its heartbeat; back on resumes it.
    from agos_core.actions import team as team_actions

    team_actions.park(core, ws, "researcher", True)
    assert job["enabled"] is False and job["paused_reason"] == heartbeat.PARKED_REASON
    mine = next(
        h for h in client.get(f"/workspaces/{ws}/heartbeats").json() if h["agent"] == "researcher"
    )
    assert mine["on"] and mine["problem"] == "Paused with the member."
    team_actions.park(core, ws, "researcher", False)
    assert job["enabled"] is True
    # Off removes the job; a bad interval is refused.
    assert (
        client.put(f"/workspaces/{ws}/heartbeats/researcher", json={"on": False}).status_code == 200
    )
    assert _jobs_in(core, member_home) == []
    assert (
        client.put(
            f"/workspaces/{ws}/heartbeats/researcher", json={"on": True, "interval": "2h"}
        ).status_code
        == 422
    )
    assert client.put(f"/workspaces/{ws}/heartbeats/nobody", json={"on": True}).status_code == 404


def test_heartbeat_prompt_template() -> None:
    plain = heartbeat.prompt_for("researcher", cofounder_lines=False)
    extra = heartbeat.prompt_for(None, cofounder_lines=True)
    assert plain.startswith(heartbeat.PROMPT_HEAD)
    assert "5. The team's blocked or stalled cards" in extra and "5." not in plain
    assert heartbeat.interval_of("0 8 * * *") == "daily" and heartbeat.interval_of("7h") is None
    # Hermes saves the parsed schedule (cron/jobs.py): each interval reads back as itself.
    for name, minutes in (("15m", 15), ("1h", 60), ("4h", 240)):
        saved = {"kind": "interval", "minutes": minutes, "display": f"every {minutes}m"}
        assert heartbeat.interval_of(saved) == name
        assert heartbeat.interval_of(saved["display"]) == name  # as job_state reads it
    assert heartbeat.interval_of({"kind": "cron", "expr": "0 8 * * *"}) == "daily"
    assert heartbeat.interval_of({"kind": "interval", "minutes": 120}) is None
    assert heartbeat.interval_of("every 120m") is None
    assert heartbeat.interval_of({"kind": "once", "run_at": "x"}) is None


# ---- task watchdog -----------------------------------------------------------------------------


def _tree(core: Any, ws: str) -> tuple[str, list[str]]:
    """A root card with two leaves on the fake board."""
    from test_cofounder_actions import _run  # noqa: F401  (import keeps the fixture order)

    cards = kanban_of(core, ws)
    root = "t_root"
    cards[root] = {
        "id": root,
        "title": "Launch",
        "body": "",
        "status": "todo",
        "parents": [],
        "comments": [],
        "key": None,
        "created_at": 1,
    }
    leaves = []
    for n in (1, 2):
        cid = f"t_leaf{n}"
        cards[cid] = {
            "id": cid,
            "title": f"Leaf {n}",
            "body": "",
            "status": "ready",
            "parents": [root],
            "comments": [],
            "key": None,
            "created_at": 2,
        }
        leaves.append(cid)
    return root, leaves


@pytest.fixture
def fake_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """holds.subtree reads the board database; here, the fake's cards."""
    from agos_core.actions import holds
    from agos_core.actions.errors import NotFoundError

    def subtree(core: Any, ws: str, root: str) -> dict[str, str]:
        cards = kanban_of(core, ws)
        if root not in cards:
            raise NotFoundError("This card")
        found = {root: str(cards[root]["status"])}
        for c in cards.values():
            if root in (c.get("parents") or []):
                found[c["id"]] = str(c["status"])
        return found

    monkeypatch.setattr(holds, "subtree", subtree)


def test_watchdog_wakes_once_per_stop_and_escalates_after_three_acts(
    team: Env, fake_tree: None
) -> None:
    client, _fake, core, ws = team
    root, leaves = _tree(core, ws)
    root_home = str(core.engine.profile_home(ws))
    assert (
        client.put(f"/workspaces/{ws}/watchdogs/{leaves[0]}", json={"on": True}).status_code == 400
    )
    r = client.put(f"/workspaces/{ws}/watchdogs/{root}", json={"on": True})
    assert r.status_code == 200, r.text
    wid = r.json()["id"]
    (job,) = _jobs_in(core, root_home)
    assert job["spec"].schedule == watchdogs.SCHEDULE and job["spec"].name.endswith(root)
    assert f"agos_watchdog_observe(watchdog_id={wid}" in job["spec"].prompt
    assert "stop fingerprint" in job["spec"].prompt and "kanban unblock" in job["spec"].prompt
    assert client.get(f"/workspaces/{ws}/kanban/{root}").json()["watchdogId"] == wid
    observe = f"/workspaces/{ws}/watchdogs/{wid}/observe"
    fp = f"{leaves[0]}:ready,{leaves[1]}:blocked"
    assert client.post(observe, json={"fingerprint": fp}).json() == {"answer": "act", "acts": 1}
    # The same stop again (the job's next run): no second wake.
    assert client.post(observe, json={"fingerprint": fp}).json() == {"answer": "seen", "acts": 1}
    assert (
        client.post(observe, json={"fingerprint": f"{leaves[1]}:blocked,{leaves[0]}:ready"}).json()[
            "answer"
        ]
        == "seen"
    )
    # The agent reopened a leaf; it stopped again with the same open leaves: act 2.
    fp2 = f"{leaves[0]}:blocked,{leaves[1]}:blocked"
    assert client.post(observe, json={"fingerprint": fp2}).json() == {"answer": "act", "acts": 2}
    # Third act with no leaf finished: the root card goes to the owner (needs_input).
    fp3 = f"{leaves[0]}:ready,{leaves[1]}:ready"
    assert client.post(observe, json={"fingerprint": fp3}).json() == {
        "answer": "escalate",
        "acts": 0,
    }
    assert kanban_of(core, ws)[root]["status"] == "blocked"
    listed = client.get(f"/workspaces/{ws}/watchdogs").json()
    assert listed[0]["escalatedAt"] and listed[0]["fingerprint"] == fp3
    # Progress (a leaf finished): the count starts again.
    assert client.post(observe, json={"fingerprint": f"{leaves[1]}:ready"}).json() == {
        "answer": "act",
        "acts": 1,
    }
    # The bridge path the agent's tool uses answers the same.
    from agos_core.actions import hermes_channel as channel

    good = {"authorization": f"Bearer {channel.bridge_key(core, ws)}"}
    r = client.post(
        f"/hermes-bridge/{ws}/watchdog-observe",
        json={"watchdog_id": wid, "fingerprint": f"{leaves[1]}:ready"},
        headers=good,
    )
    assert r.status_code == 200 and r.json()["answer"] == "seen"
    # Off: the row and the job go.
    assert client.put(f"/workspaces/{ws}/watchdogs/{root}", json={"on": False}).status_code == 200
    assert (
        _jobs_in(core, root_home) == [] and client.get(f"/workspaces/{ws}/watchdogs").json() == []
    )
    assert client.post(observe, json={"fingerprint": "x"}).status_code == 404


def test_watchdog_sweep_forgets_a_finished_tree(team: Env, fake_tree: None) -> None:
    client, _fake, core, ws = team
    root, _ = _tree(core, ws)
    assert client.put(f"/workspaces/{ws}/watchdogs/{root}", json={"on": True}).status_code == 200
    watchdogs.sweep(core)
    assert len(client.get(f"/workspaces/{ws}/watchdogs").json()) == 1
    kanban_of(core, ws)[root]["status"] = "done"
    watchdogs.sweep(core)
    assert client.get(f"/workspaces/{ws}/watchdogs").json() == []


def test_watchdog_tool_tells_the_agent_what_next() -> None:
    from agos_core.hermes_plugin.agos_guard import watchdog as tool

    answers: list[dict[str, Any] | None] = [{"answer": "act", "acts": 1}, None, {"error": "gone"}]
    posted: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any], timeout: float) -> dict[str, Any] | None:
        posted.append((path, body))
        return answers.pop(0)

    said = json.loads(tool.observe_tool({"watchdog_id": 3, "fingerprint": "a:ready"}, post=post))
    assert said["answer"] == "act" and "unblock" in said["next"]
    assert posted == [("watchdog-observe", {"watchdog_id": 3, "fingerprint": "a:ready"})]
    assert (
        "can't be reached"
        in json.loads(tool.observe_tool({"watchdog_id": 3, "fingerprint": ""}, post=post))["error"]
    )
    assert json.loads(tool.observe_tool({"watchdog_id": 3, "fingerprint": ""}, post=post)) == {
        "error": "gone"
    }
    assert "watchdog_id" in json.loads(tool.observe_tool({"fingerprint": "x"}, post=post))["error"]


# ---- ticket on-ramps ------------------------------------------------------------------------


def _ticket_cards(core: Any, ws: str, source: str) -> dict[str, dict[str, Any]]:
    prefix = f"agos-ticket:{source}:"
    return {
        str(c["key"])[len(prefix) :]: c
        for c in kanban_of(core, ws).values()
        if str(c.get("key") or "").startswith(prefix)
    }


def test_ticket_presets_are_listed_with_their_mapping(team: Env) -> None:
    client, _fake, _core, _ws = team
    presets = {p["source"]: p for p in client.get("/ticket-presets").json()}
    assert set(presets) == {"linear", "jira", "asana", "github"}
    assert presets["linear"]["signed"] and presets["github"]["events"] == ["issues"]
    assert (
        presets["jira"]["conditions"][0]["field"] == "webhookEvent"
        and not presets["jira"]["signed"]
    )
    assert presets["linear"]["step"]["title"] == "Work the Linear issue"


def test_linear_issues_become_cards_and_close_with_the_issue(team: Env) -> None:
    client, _fake, core, ws = team
    preset = next(p for p in client.get("/ticket-presets").json() if p["source"] == "linear")
    step = {**preset["step"], "agent": "researcher"}
    aid = create(
        client,
        ws,
        name="Linear",
        schedule="",
        steps=[step],
        hook=True,
        ticket={"source": "linear", "member": "researcher"},
    )
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["ticket"] == {"source": "linear", "member": "researcher"}
    path = hook_on(client, ws, aid, secret="", conditions=preset["conditions"])["path"]

    def issue(
        identifier: str, title: str, state: str, action: str = "create", **extra: Any
    ) -> dict[str, Any]:
        return {
            "action": action,
            "type": "Issue",
            "data": {
                "id": "uuid-1",
                "identifier": identifier,
                "title": title,
                "description": "Fix the login",
                "url": f"https://linear.app/x/{identifier}",
                "state": {"type": state},
            },
            **extra,
        }

    assert (
        deliver(client, path, issue("ENG-1", "Login broken", "started"), secret=None).status_code
        == 200
    )
    cards = _ticket_cards(core, ws, "linear")
    assert set(cards) == {"ENG-1"}
    card = cards["ENG-1"]
    assert card["title"] == "[Linear ENG-1] Login broken" and card["assignee"].endswith(
        "researcher"
    )
    assert "Fix the login" in card["body"] and "https://linear.app/x/ENG-1" in card["body"]
    assert "Work the Linear issue" not in card["title"] and "within your role" in card["body"]
    # An update to the open issue: one comment, no second card (the key is the issue's).
    assert (
        deliver(
            client, path, issue("ENG-1", "Login broken on iOS", "started", "update"), secret=None
        ).status_code
        == 200
    )
    assert len(_ticket_cards(core, ws, "linear")) == 1
    assert card["comments"][0]["body"].startswith("Updated upstream: Login broken on iOS")
    # Closed upstream: the card is completed with Hermes's `kanban complete`.
    assert (
        deliver(
            client, path, issue("ENG-1", "Login broken on iOS", "completed", "update"), secret=None
        ).status_code
        == 200
    )
    assert card["status"] == "done" and "Closed upstream" in card["result"]
    # A comment event (not an Issue) is dropped by the route's filter, like Hermes would.
    other = {"action": "create", "type": "Comment", "data": {"id": "c1", "body": "hi"}}
    assert deliver(client, path, other, secret=None).json() == {
        "status": "ignored",
        "reason": "filter",
    }
    events = client.get(f"/workspaces/{ws}/automations/{aid}/events").json()
    assert events[0]["detail"].startswith("Linear ENG-1: closed, card")
    assert "card" in events[2]["detail"]


def test_github_jira_and_asana_payloads_map_to_cards(team: Env) -> None:
    client, _fake, core, ws = team
    for source, payload, key, title in (
        (
            "github",
            {
                "event_type": "issues",
                "action": "opened",
                "issue": {
                    "number": 7,
                    "title": "Crash",
                    "body": "Stack",
                    "html_url": "https://github.com/o/r/issues/7",
                },
                "repository": {"full_name": "o/r"},
            },
            "o/r#7",
            "[GitHub o/r#7] Crash",
        ),
        (
            "jira",
            {
                "webhookEvent": "jira:issue_created",
                "issue": {
                    "key": "AG-12",
                    "self": "https://x.atlassian.net/rest/api/2/issue/1",
                    "fields": {
                        "summary": "Slow page",
                        "description": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Takes 9s"}],
                                }
                            ],
                        },
                        "status": {"statusCategory": {"key": "new"}},
                    },
                },
            },
            "AG-12",
            "[Jira AG-12] Slow page",
        ),
        (
            "asana",
            {
                "events": [
                    {
                        "action": "added",
                        "resource": {
                            "gid": "555",
                            "resource_type": "task",
                            "name": "Call supplier",
                        },
                    },
                    {"action": "added", "resource": {"gid": "9", "resource_type": "story"}},
                ]
            },
            "555",
            "[Asana 555] Call supplier",
        ),
    ):
        preset = next(p for p in client.get("/ticket-presets").json() if p["source"] == source)
        aid = create(
            client,
            ws,
            name=source.title(),
            schedule="",
            steps=[preset["step"]],
            hook=True,
            ticket={"source": source},
        )
        path = hook_on(
            client, ws, aid, secret="", events=preset["events"], conditions=preset["conditions"]
        )["path"]
        assert deliver(client, path, payload, secret=None).status_code == 200
        cards = _ticket_cards(core, ws, source)
        assert set(cards) == {key}, source
        assert cards[key]["title"] == title
        assert cards[key]["assignee"] == core.engine.hermes_name(ws)  # no member: the Co-Founder
    assert "Takes 9s" in _ticket_cards(core, ws, "jira")["AG-12"]["body"]
    # Jira's done bucket closes the card.
    jira_path = client.get(f"/workspaces/{ws}/automations").json()
    jira = next(a for a in jira_path if a["name"] == "Jira")
    closed = {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "AG-12",
            "fields": {"summary": "Slow page", "status": {"statusCategory": {"key": "done"}}},
        },
    }
    assert deliver(client, jira["hook"]["path"], closed, secret=None).status_code == 200
    assert _ticket_cards(core, ws, "jira")["AG-12"]["status"] == "done"
    # A ticket on-ramp without the webhook makes no sense: refused.
    r = client.post(
        f"/workspaces/{ws}/automations",
        json={
            "name": "x",
            "instructions": "x",
            "schedule": "0 9 * * *",
            "model": MODEL,
            "ticket": {"source": "linear"},
        },
    )
    assert r.status_code == 400 and "webhook" in r.json()["detail"]


def test_plan_carries_variables_policy_and_ticket_for_hermess_script(team: Env) -> None:
    client, _fake, core, ws = team
    from agos_core.actions import automation_cards, automations

    aid = create(
        client,
        ws,
        schedule="",
        steps=MONDAY_STEPS,
        hook=True,
        variables=VARIABLES[:2],
        policy="always_enqueue",
        ticket={"source": "github", "member": "ideas"},
    )
    automation = automations.get(core, ws, aid)
    assert automation is not None
    plan = automation_cards.plan(core, automation, "webhook")
    assert plan["variables"] == [
        {"name": "topic", "default": "Argan oil"},
        {"name": "count", "default": "10"},
    ]
    assert plan["policy"] == "always_enqueue"
    assert plan["ticket"]["source"] == "github" and plan["ticket"]["assignee"].endswith("ideas")
    assert plan["ticket"]["id"] == "{repository.full_name}#{issue.number}"
