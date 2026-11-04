"""Automations know who does them: one agent of the team, the Co-Founder, or team
steps (several agents one after another) that AGOS puts on the Kanban at each fire.
The owner approves a team automation's steps once; an agent that's gone never
stops an automation (the Co-Founder does its part, and the owner is told)."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from test_automations import FakeCron
from test_cofounder_actions import _run
from work_env import MODEL, Env, agent, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.actions import automations as automation_actions
from agos_core.engine.cron import automation_prompt

TEAM = ["researcher", "ideas"]

MONDAY_STEPS = [
    {
        "key": "research",
        "title": "This week's topics",
        "agent": "researcher",
        "description": "Trending topics per style.",
    },
    {
        "key": "ideas",
        "title": "10 ideas per style",
        "agent": "ideas",
        "waits_on": ["research"],
        "description": "10 ideas per style from the research.",
    },
    {
        "key": "check",
        "title": "Check the ideas",
        "agent": "researcher",
        "kind": "review",
        "reviews": "ideas",
        "description": "Check the facts.",
    },
]


@pytest.fixture
def team(env: Env, fake_board: None) -> Env:  # noqa: F811
    client, _, core, ws = env
    for name in TEAM:
        agent(client, ws, name)
    cron = FakeCron()
    cron.runner = core.engine.runner
    core.engine.cron_bridge = cron
    return env


def create(client: Any, ws: str, **extra: Any) -> int:
    body = {
        "name": "Monday ideas",
        "instructions": "Every Monday: 10 video ideas for each of our 3 styles.",
        "schedule": "0 9 * * 1",
        "model": MODEL,
        "on": True,
        **extra,
    }
    r = client.post(f"/workspaces/{ws}/automations", json=body)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def steps_on_board(core: Any, ws: str, cards: list[str]) -> dict[str, dict[str, Any]]:
    """The run's cards by step (the step key ends the card's idempotency key)."""
    board = kanban_of(core, ws)
    return {str(board[c]["key"]).rsplit(":", 1)[1]: board[c] for c in cards}


def finish_card(core: Any, ws: str, card: dict[str, Any], result: str) -> None:
    card["status"], card["result"] = "done", result


def cofounder_messages(core: Any, ws: str) -> list[str]:
    return [
        r["body"]
        for r in core.db.execute(
            """SELECT m.body FROM messages m JOIN chats c ON c.id = m.chat_id
               WHERE c.workspace_id = ? AND c.kind = 'dm' AND c.agent IS NULL ORDER BY m.id""",
            (ws,),
        )
    ]


# ---- the schedule -------------------------------------------------------------------


def fire(core: Any, ws: str, aid: int) -> list[str] | None:
    """Hermes's cron fires the automation's job: its script puts the run on the
    Kanban itself (None: it didn't start)."""
    import hermes_script

    home = core.engine.profile_home(ws)
    code, said = core.engine.cron_bridge.fire(home, f"agos-automation-{aid}.py")
    assert code == 0, said
    return hermes_script.cards_made(said)


# ---- one agent ------------------------------------------------------------------------


def _home(core: Any, ws: str, agent: str | None = None) -> str:
    from agos_core.actions import agent_profiles

    key = agent_profiles.key(ws, agent) if agent else ws
    return str(core.engine.profile_home(key))


def _agent_id(core: Any, ws: str, name: str) -> int:
    row = core.db.execute(
        "SELECT id FROM library_items WHERE kind='agent' AND name=? AND workspace_id=?", (name, ws)
    ).fetchone()
    return int(row["id"])


def test_a_one_agent_automation_is_a_job_in_that_agents_own_hermes_cron(team: Env) -> None:
    """Who does it is whose Hermes cron holds its job: the member's own profile
    (Hermes runs it as that member, with its SOUL.md). No role text in the prompt."""
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws, "ideas")
    assert "You are ideas." not in job["spec"].prompt and "@ideas" not in job["spec"].prompt
    # Its role is in the member's own SOUL.md, which Hermes's cron reads.
    soul = (core.engine.profile_home(f"{ws}--a-ideas") / "SOUL.md").read_text()
    assert "You are ideas." in soul
    # A failed run is told in the Co-Founder chat (named: a member's profile has no home chat).
    from agos_core.actions.hermes_channel import cofounder_chat

    assert job["spec"].failure_deliver == f"agos:{cofounder_chat(core, ws)}"
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["agent"] == "ideas" and auto["steps"] == [] and auto["notice"] is None
    # Hermes says who does it: AGOS keeps no copy.
    row = core.db.execute("SELECT agent FROM automations WHERE id = ?", (aid,)).fetchone()
    assert row["agent"] is None
    # Its instructions are the job's prompt: AGOS keeps no file of them.
    assert not (core.layout.workspaces / ws / auto["file"]).exists()

    # The agent's instructions change: its SOUL.md follows; the job stays as it is.
    r = client.put(
        f"/workspaces/{ws}/agents/{_agent_id(core, ws, 'ideas')}",
        json={"name": "ideas", "title": "Ideas Generator", "definition": {"instructions": "NEW"}},
    )
    assert r.status_code in (200, 204), r.text
    automation_actions.keep_in_step(core)
    assert list(cron.jobs) == [job["id"]] and "NEW" not in job["spec"].prompt

    # Run now and delete act on the member's cron.
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
    assert cron.fired == [job["id"]]
    assert client.delete(f"/workspaces/{ws}/automations/{aid}").status_code == 200
    assert cron.jobs == {}

    # A stranger can't be picked.
    bad = client.post(
        f"/workspaces/{ws}/automations",
        json={
            "name": "x",
            "instructions": "x",
            "schedule": "0 9 * * *",
            "model": MODEL,
            "agent": "stranger",
        },
    )
    assert bad.status_code in (400, 409, 422), bad.text


def test_a_members_pinned_skills_ride_on_its_own_cron_jobs(team: Env) -> None:
    """Hermes's cron leaves `skills.auto_load` out of a run (cron/scheduler.py
    skip_context_files), so the member's skills are its job's own `skills`
    (cron/jobs.py create_job), and they follow when the member's skills change."""
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    body = {"name": "ideas", "title": "Ideas", "definition": {"instructions": "x"}}
    url = f"/workspaces/{ws}/agents/{_agent_id(core, ws, 'ideas')}"
    pinned = body | {"definition": {"instructions": "x", "skills": ["copywriting"]}}
    assert client.put(url, json=pinned).status_code in (200, 204)
    create(client, ws, name="Weekly mail", agent="ideas")
    cofounder = create(client, ws, name="Co-Founder's own")
    by_name = {j["spec"].name: j for j in cron.jobs.values()}
    del cofounder
    mine = by_name["Weekly mail"]
    assert mine["spec"].skills == ("copywriting",)
    assert by_name["Co-Founder's own"]["spec"].skills == ()  # the root pins none
    # The member's skills change: its job's skills follow at once.
    more = body | {"definition": {"instructions": "x", "skills": ["copywriting", "seo"]}}
    assert client.put(url, json=more).status_code in (200, 204)
    assert mine["spec"].skills == ("copywriting", "seo")
    # Changed behind AGOS's back (the config edited by hand): keep_in_step follows.
    core.engine._hermes(f"{ws}--a-ideas", "config", "set", "skills.auto_load", '["seo"]')
    automation_actions.keep_in_step(core)
    assert mine["spec"].skills == ("seo",)


def test_picking_another_agent_moves_the_job(team: Env) -> None:
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    (first,) = cron.jobs
    cron.finish(first, "run-a", True, "## Response\n\nTen ideas.", 1)
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    body = {k: got[k] for k in ("name", "instructions", "schedule", "model", "on")}
    r = client.put(f"/workspaces/{ws}/automations/{aid}", json=body | {"agent": "researcher"})
    assert r.status_code == 200, r.text
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws, "researcher") and job["id"] != first
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["agent"] == "researcher"
    # Hermes removed the old job's runs with it (AGOS keeps no run copies).
    assert client.get(f"/workspaces/{ws}/automations/{aid}/runs").json() == []
    # To the Co-Founder: the root's cron.
    r = client.put(f"/workspaces/{ws}/automations/{aid}", json=body | {"agent": None})
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws) and job["spec"].failure_deliver == "agos"
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["agent"] is None


def test_an_agent_that_is_gone_hands_the_automation_to_the_cofounder(team: Env) -> None:
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    assert (
        client.delete(f"/workspaces/{ws}/agents/{_agent_id(core, ws, 'ideas')}").status_code == 204
    )
    # Its job left the member's cron before its profile went: the Co-Founder's cron has it.
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws) and job["enabled"]
    automation_actions.keep_in_step(core)
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["on"] and "Co-Founder does it" in (auto["notice"] or "")
    assert auto["agent"] == "ideas"  # the owner's pick, shown with the notice
    msgs = cofounder_messages(core, ws)
    assert any("Weekly mail" in m and "Co-Founder does it" in m for m in msgs)
    # Told once, not at every pass.
    automation_actions.keep_in_step(core)
    assert len(cofounder_messages(core, ws)) == len(msgs)
    assert list(cron.jobs.values()) == [job]


def test_an_agent_turned_off_and_on_again_takes_its_automation_back(team: Env) -> None:
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    item = _agent_id(core, ws, "ideas")
    assert client.put(f"/workspaces/{ws}/connectors/{item}", json={"on": False}).status_code < 300
    automation_actions.keep_in_step(core)
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws)  # never run as an agent that is off
    assert (
        "Co-Founder does it" in (client.get(f"/workspaces/{ws}/automations/{aid}").json()["notice"])
    )
    assert client.put(f"/workspaces/{ws}/connectors/{item}", json={"on": True}).status_code < 300
    automation_actions.keep_in_step(core)
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws, "ideas")
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["agent"] == "ideas" and auto["notice"] is None


def _old_style(core: Any, ws: str, aid: int, cron: Any) -> str:
    """The automation as AGOS made it before: its job in the Co-Founder's cron, the
    member's role pasted into the prompt, the agent kept in AGOS's row, the
    instructions' master in AGOS's file."""
    from agos_core.engine.cron import JobSpec

    for job in list(cron.jobs.values()):
        cron.remove(Path(job["home"]), job["id"])
    spec = JobSpec(
        name=f"agos-automation-{aid}",
        prompt="Do it.\n\nYou do this automation as @ideas of the team; work in that role:\n\nYou are ideas.",
        schedule="0 9 * * 1",
        model="claude-sonnet-5",
        provider="anthropic",
        reasoning_effort="medium",
        enabled=True,
    )
    old = cron.create(Path(_home(core, ws)), spec)
    core.db.execute(
        "UPDATE automations SET agent = 'ideas', name = 'Weekly mail', hermes_job_id = ?"
        " WHERE id = ?",
        (old["id"], aid),
    )
    (core.layout.workspaces / ws / "automations" / "weekly-mail.md").write_text(
        '---\nname: "Weekly mail"\n---\n\nDo it.\n'
    )
    return str(old["id"])


def test_the_live_migration_moves_old_member_jobs_once(team: Env) -> None:
    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    old = _old_style(core, ws, aid, cron)
    cron.finish(old, "run-old", False, "# Cron Job: x\n\nError: boom\n", 1)
    cron.pause(Path(_home(core, ws)), old, "Account pause in AGOS")  # held: stays held
    automation_actions.keep_in_step(core)
    (job,) = cron.jobs.values()
    assert job["home"] == _home(core, ws, "ideas") and job["id"] != old
    assert job["spec"].prompt == automation_prompt("Do it.")  # from the file
    assert job["spec"].name == "Weekly mail"  # the owner's name, now Hermes's own
    assert not (core.layout.workspaces / ws / "automations" / "weekly-mail.md").exists()
    assert job["paused_reason"] == "Account pause in AGOS"
    row = core.db.execute("SELECT * FROM automations WHERE id = ?", (aid,)).fetchone()
    assert row["hermes_job_id"] == job["id"] and row["agent"] is None
    # Again: nothing moves, nothing is made twice.
    made = cron.n
    automation_actions.keep_in_step(core)
    assert cron.n == made and list(cron.jobs) == [job["id"]]


def test_a_move_stopped_halfway_ends_with_one_job(team: Env) -> None:
    """Made in the member's cron but not linked yet (AGOS stopped there): the next
    pass takes that job and removes the old one; no second job is made."""
    from agos_core.engine.cron import JobSpec

    client, _, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, name="Weekly mail", agent="ideas")
    old = _old_style(core, ws, aid, cron)
    spec = JobSpec(**{**cron.jobs[old]["spec"].as_dict(), "prompt": "Do it."})
    half = cron.create(Path(_home(core, ws, "ideas")), spec)["id"]
    made = cron.n
    automation_actions.keep_in_step(core)
    assert list(cron.jobs) == [half] and cron.n == made
    assert core.db.execute("SELECT hermes_job_id FROM automations").fetchone()[0] == half


def test_archive_holds_a_members_job_and_the_pause_holds_the_root(team: Env) -> None:
    from agos_core.actions import account_pause

    client, _, core, ws = team
    cron = core.engine.cron_bridge
    create(client, ws, name="Weekly mail", agent="ideas")
    (job,) = cron.jobs.values()
    # The account pause is Hermes's own pause (ADR 0022): the root's ESTOP holds
    # the whole workspace — the member's job itself stays exactly as it is.
    account_pause.apply(core, "Claude at 95%")
    assert (core.engine.profile_home(ws) / "ESTOP").exists()
    assert job["enabled"] is True and not job.get("paused_reason")
    account_pause.apply(core, None)
    assert not (core.engine.profile_home(ws) / "ESTOP").exists()
    assert job["enabled"] is True
    assert client.post(f"/workspaces/{ws}/archive").status_code < 300
    assert job["paused_reason"] == "Workspace archived in AGOS"
    assert client.post(f"/workspaces/{ws}/unarchive").status_code < 300
    (job,) = cron.jobs.values()
    assert job["enabled"] is True and job["home"] == _home(core, ws, "ideas")


# ---- a team automation ---------------------------------------------------------------


def test_a_team_automation_puts_its_steps_on_the_kanban_and_reports(team: Env) -> None:
    client, _fake, core, ws = team
    cron = core.engine.cron_bridge
    aid = create(client, ws, steps=MONDAY_STEPS)
    # Its clock is a Hermes cron job that runs a script (no agent, no tokens): the
    # script itself puts the run on the Kanban (Hermes's CLI), AGOS isn't called.
    (job,) = cron.jobs.values()
    assert job["spec"].script == f"agos-automation-{aid}.py" and job["spec"].prompt == ""
    script = (core.engine.profile_home(ws) / "scripts" / job["spec"].script).read_text()
    assert "hermes-bridge" not in script and '"kanban"' in script
    assert "a-researcher" in script and "a-ideas" in script  # who does each step
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert [s["agent"] for s in auto["steps"]] == ["researcher", "ideas", "researcher"]
    assert auto["nextRunAt"] and datetime.fromisoformat(auto["nextRunAt"]).weekday() == 0
    file = core.layout.workspaces / ws / auto["file"]
    # The file holds the brief only (AGOS's team plan); who does what is the steps'.
    text = file.read_text()
    assert "Every Monday: 10 video ideas" in text and "Monday ideas" not in text
    assert "done_by" not in text and "model" not in text

    # Not fired: nothing on the board. Hermes's cron fires it (its script).
    assert kanban_of(core, ws) == {}
    from agos_core.actions import hermes_channel

    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/automation-fire",
        json={"automation": aid},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404  # AGOS no longer fires automations
    cards = fire(core, ws, aid)
    assert cards is not None and len(cards) == 3
    steps = steps_on_board(core, ws, cards)
    assert steps["research"]["assignee"] == "a-researcher"
    assert steps["ideas"]["assignee"] == "a-ideas"
    assert "10 video ideas for each of our 3 styles" in steps["ideas"]["body"]
    # Each step's card waits on the cards of the steps it waits on.
    assert steps["ideas"]["parents"] == [steps["research"]["id"]]
    assert steps["check"]["parents"] == [steps["ideas"]["id"]]
    assert "Review the work of “10 ideas per style”" in steps["check"]["body"]
    assert steps["research"]["model_override"] == MODEL["model"]
    # The other workspace's board is never touched.
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert kanban_of(core, other) == {}

    # A second fire while its cards are still open doesn't start a second copy.
    assert fire(core, ws, aid) is None and len(kanban_of(core, ws)) == 3
    assert not any("still going" in m for m in cofounder_messages(core, ws))
    runs_url = f"/workspaces/{ws}/automations/{aid}/runs"
    assert client.get(runs_url).json() == []  # nothing finished yet (read from the cards)

    # The members work the cards (Hermes's dispatcher); once all are done the run is
    # in Runs with what the last card gave.
    finish_card(core, ws, steps["research"], "Topics: AI phones, Ramadan recipes.")
    finish_card(core, ws, steps["ideas"], "30 ideas in ideas/2026-09-28.md")
    assert client.get(runs_url).json() == []
    finish_card(core, ws, steps["check"], "All facts check out.")
    # AGOS keeps no copy of the run: it is read from Hermes's cards.
    [run] = client.get(runs_url).json()
    assert run["result"] == "ok" and run["source"] == "schedule"
    assert run["report"] == "All facts check out."
    # Done: the next fire starts a new run.
    assert fire(core, ws, aid) and len(kanban_of(core, ws)) == 6


def test_run_now_a_missed_fire_and_a_gone_member(team: Env) -> None:
    client, _, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS)
    # Run now starts it at once: Hermes runs its job (`hermes cron run`), AGOS
    # doesn't run the script itself; again while it runs is refused.
    cron = core.engine.cron_bridge
    cron.run_script = None  # never AGOS's own run of it
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
    assert len(kanban_of(core, ws)) == 3 and len(cron.ran_inline) == 1
    still = client.post(f"/workspaces/{ws}/automations/{aid}/run")
    assert still.status_code == 409 and "still going" in still.text
    del cron.run_script
    for card in kanban_of(core, ws).values():
        card["status"] = "done"

    # A member is deleted: its steps go to the Co-Founder, the owner is told once.
    row = core.db.execute(
        "SELECT id FROM library_items WHERE kind='agent' AND name='ideas' AND workspace_id=?", (ws,)
    ).fetchone()
    client.delete(f"/workspaces/{ws}/agents/{row['id']}")
    automation_actions.keep_in_step(core)
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert "@ideas" in (auto["notice"] or "") and "Co-Founder does those steps" in auto["notice"]
    before = set(kanban_of(core, ws))
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
    new = [c for c in kanban_of(core, ws) if c not in before]
    steps = steps_on_board(core, ws, new)
    assert steps["ideas"]["assignee"] == "default"  # the Co-Founder's
    assert steps["research"]["assignee"] == "a-researcher"

    # Paused: Hermes's job is paused, so its script never runs.
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    (job,) = core.engine.cron_bridge.jobs.values()
    assert job["enabled"] is False and job["paused_reason"] == "Turned off in AGOS"


def test_check_first_puts_the_owners_ok_before_the_team(team: Env) -> None:
    client, _, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS[:2], checkFirst=True)
    cards = fire(core, ws, aid)
    assert cards is not None
    steps = steps_on_board(core, ws, cards)
    ok = steps["owner-ok"]
    assert ok["assignee"] is None and ok["status"] == "todo"  # his, nobody works it
    assert steps["research"]["parents"] == [ok["id"]]
    assert steps["ideas"]["parents"] == [steps["research"]["id"]]


def test_bad_team_steps_are_refused(team: Env) -> None:
    client, _, _, ws = team
    for steps in (
        [{"key": "a", "title": "A", "agent": "stranger"}],
        [
            {"key": "a", "title": "A", "waits_on": ["b"]},
            {"key": "b", "title": "B", "waits_on": ["a"]},
        ],
    ):
        r = client.post(
            f"/workspaces/{ws}/automations",
            json={
                "name": "Bad",
                "instructions": "x",
                "schedule": "0 9 * * 1",
                "model": MODEL,
                "steps": steps,
            },
        )
        assert r.status_code == 400, r.text
    assert client.get(f"/workspaces/{ws}/automations").json() == []


# ---- the Co-Founder decides who ---------------------------------------------------------


def test_the_cofounder_knows_the_team_and_a_team_automation_waits_for_one_approve(
    team: Env,
) -> None:
    client, _, core, ws = team
    from agos_core.actions import cofounder_actions

    text = cofounder_actions.instructions(core, ws)
    assert "@researcher" in text and "@ideas" in text
    assert 'Never say "no agent does this"' in text

    # A simple job: one agent, done at once (direct mode).
    [card] = _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Friday mail",
            "schedule": "0 17 * * 5",
            "instructions": "Mail the week's ideas to the owner.",
            "agent": "ideas",
        },
    )
    assert card["status"] == "done" and "@ideas" in card["title"], card
    # Several roles: a team automation waits for the owner's one Allow (Hermes's
    # approval before the tool runs, even in direct mode).
    from agos_core.actions import hermes_channel

    item = {
        "do": "create_automation",
        "name": "Monday ideas",
        "schedule": "0 9 * * 1",
        "instructions": "10 ideas per style.",
        "steps": MONDAY_STEPS,
    }
    check = hermes_channel.tool_check(core, "agos_action", {"actions": [item]})
    assert check["ask"] is True and "@researcher → @ideas → @researcher" in check["message"]
    names = [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()]
    assert names == ["Friday mail"]
    [card] = _run(core, ws, item)  # he said Allow
    assert card["status"] == "done", card
    assert "Who does what" in card["detail"] and "10 ideas per style — @ideas" in card["detail"]
    monday = next(
        a for a in client.get(f"/workspaces/{ws}/automations").json() if a["name"] == "Monday ideas"
    )
    assert len(monday["steps"]) == 3
    # The Co-Founder's list now says who does each.
    text = cofounder_actions.instructions(core, ws)
    assert "done by @ideas" in text and "done by the team:" in text

    # Undo removes it.
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 200
    assert [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()] == [
        "Friday mail"
    ]

    # Give it back to the Co-Founder; Undo brings the agent back.
    [card] = _run(
        core, ws, {"do": "update_automation", "automation": "Friday mail", "agent": "cofounder"}
    )
    friday = client.get(f"/workspaces/{ws}/automations").json()[0]
    assert card["status"] == "done" and friday["agent"] is None
    client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert client.get(f"/workspaces/{ws}/automations").json()[0]["agent"] == "ideas"


def test_archiving_every_card_ends_the_run_so_the_next_one_can_start(team: Env) -> None:
    client, _, core, ws = team
    aid = create(client, ws, steps=MONDAY_STEPS)
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
    for card in list(kanban_of(core, ws)):
        r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json={"action": "archive"})
        assert r.status_code < 300, r.text
    [run] = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    assert run["result"] == "failed" and "archived" in run["report"]
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
