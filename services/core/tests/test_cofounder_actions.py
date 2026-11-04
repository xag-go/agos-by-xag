"""The Co-Founder does what the owner asks from a chat (like Hermes), through the
owner's own actions; each shows as a card with Undo (or Approve in ask mode)."""

from typing import Any

from test_automations import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions
from agos_core.db import chats as chats_repo
from agos_core.engine import cofounder_actions as rules


def _all_agents(core: Any) -> list[dict[str, Any]]:
    """Every workspace's members, as their Hermes profiles say."""
    from agos_core.actions import team

    return [
        {
            "workspace_id": a.workspace_id,
            "name": a.name,
            "title": a.title,
            "summary": a.summary,
            "definition": a.definition,
        }
        for w in core.db.execute("SELECT id FROM workspaces").fetchall()
        for a in team.members(core, str(w["id"]))
    ]


def _actions(*items: dict[str, Any]) -> list[Any]:
    """What the Co-Founder's agos_action tool asks, as AGOS reads it."""
    cleaned = [rules._clean(dict(i)) for i in items]
    return [a for a in cleaned if a is not None]


def test_only_valid_actions_are_kept() -> None:
    items = [
        {"do": "create_automation", "name": "Ideas", "schedule": "0 9 * * 1", "instructions": "x"},
        {"do": "rm_rf", "name": "x"},
        {"do": "create_skill", "name": "no-fields"},
    ]
    assert [a.do for a in _actions(*items)] == ["create_automation"]


def _cofounder_turn(core: Any, ws: str) -> tuple[int, int]:
    from agos_core.actions.workers import open_dm

    chat = open_dm(core, ws, None)
    turn = chats_repo.insert_turn(
        core.db, chat_id=chat, workspace_id=ws, asked_up_to=0, speaker=None
    )
    core.db.execute("UPDATE chat_turns SET status = 'completed' WHERE id = ?", (turn,))
    return int(chat), int(turn)


def _run(core: Any, ws: str, *items: dict[str, Any]) -> list[dict[str, Any]]:
    """The agos_action tool once Hermes let it run (hermes_channel.run_actions):
    each action is done at once and shows as a card."""
    chat, turn = _cofounder_turn(core, ws)
    actions = _actions(*items)
    for action_id in cofounder_actions.save(core, ws, chat, turn, actions):
        row = core.db.execute(
            "SELECT * FROM cofounder_actions WHERE id = ?", (action_id,)
        ).fetchone()
        cofounder_actions._run(core, row)
    return [a.model_dump(by_alias=True) for a in cofounder_actions.of_turn(core.db, turn)]


def test_the_cofounder_creates_an_automation_at_once_and_undo_removes_it(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    assert "create_automation" in cofounder_actions.instructions(core, ws)
    [card] = _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Monday ideas",
            "schedule": "0 9 * * 1",
            "instructions": "Write 10 ideas per style.",
        },
    )
    assert card["status"] == "done" and card["canUndo"], card
    [auto] = client.get(f"/workspaces/{ws}/automations").json()
    assert auto["name"] == "Monday ideas" and auto["schedule"] == "0 9 * * 1" and auto["on"]
    assert auto["model"]["model"] == MODEL["model"]  # the workspace's default model
    (job,) = cron.jobs.values()
    assert job["spec"].schedule == "0 9 * * 1"
    # The instructions now list it, so the Co-Founder can change it later.
    assert "Monday ideas" in cofounder_actions.instructions(core, ws)

    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 200 and r.json()["status"] == "undone"
    assert client.get(f"/workspaces/{ws}/automations").json() == [] and cron.jobs == {}
    # Undo twice is refused.
    again = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert again.status_code == 409


def test_change_pause_and_delete_by_name_then_undo_brings_it_back(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _run(
        core,
        ws,
        {"do": "create_automation", "name": "Daily", "schedule": "0 8 * * *", "instructions": "a"},
    )
    [changed] = _run(
        core, ws, {"do": "update_automation", "automation": "daily", "schedule": "30 7 * * *"}
    )
    assert changed["status"] == "done"
    assert client.get(f"/workspaces/{ws}/automations").json()[0]["schedule"] == "30 7 * * *"
    [paused] = _run(core, ws, {"do": "pause_automation", "automation": "Daily"})
    assert paused["status"] == "done"
    assert client.get(f"/workspaces/{ws}/automations").json()[0]["on"] is False
    [deleted] = _run(core, ws, {"do": "delete_automation", "automation": "Daily"})
    assert client.get(f"/workspaces/{ws}/automations").json() == []
    client.post(f"/workspaces/{ws}/cofounder-actions/{deleted['id']}", json={"choice": "undo"})
    [back] = client.get(f"/workspaces/{ws}/automations").json()
    assert back["name"] == "Daily" and back["schedule"] == "30 7 * * *" and back["on"] is False


def test_the_same_rules_as_the_owners_buttons(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    cards = _run(
        core,
        ws,
        {"do": "create_automation", "name": "Bad", "schedule": "every monday", "instructions": "x"},
        {"do": "pause_automation", "automation": "nothing-here"},
        {"do": "create_mcp", "name": "local", "url": "http://localhost:9000/mcp"},
    )
    assert [c["status"] for c in cards] == ["failed", "failed", "failed"]
    assert "Schedule" in cards[0]["error"] and "no automation" in cards[1]["error"]
    assert "aren't allowed" in cards[2]["error"]
    assert client.get(f"/workspaces/{ws}/automations").json() == []


def _member(client: Any, ws: str, name: str, title: str = "", instructions: str = "x") -> None:
    """A team member made for the test (the API the test rigs use): the Co-Founder
    makes none itself, every new agent of its own is a hire card (test_hire_required)."""
    r = client.post(
        f"/workspaces/{ws}/agents",
        json={"name": name, "title": title, "definition": {"instructions": instructions}},
    )
    assert r.status_code == 201, r.text


def test_skills_are_created_and_turned_on_and_create_agent_makes_no_agent(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    cards = _run(
        core,
        ws,
        {
            "do": "create_skill",
            "name": "Hook Writer",
            "description": "Use when writing video hooks.",
            "instructions": "Write 3 hooks, short.",
        },
        {
            "do": "create_agent",
            "name": "editor",
            "title": "Editor",
            "instructions": "Edit scripts.",
        },
    )
    assert [c["status"] for c in cards] == ["done", "failed"], cards
    # A new agent is a hire: create_agent alone (no kit, no model) is refused, with how.
    assert "create_agent makes no agent any more" in cards[1]["error"]
    assert "hire_agent" in cards[1]["error"] and "kit is missing" in cards[1]["error"]
    on = {
        (c["kind"], c["name"]) for c in client.get(f"/workspaces/{ws}/connectors").json() if c["on"]
    }
    assert ("skill", "hook-writer") in on and ("agent", "editor") not in on
    assert client.get(f"/workspaces/{ws}/agents").json() == []
    client.post(f"/workspaces/{ws}/cofounder-actions/{cards[0]['id']}", json={"choice": "undo"})
    names = {i["name"] for i in client.get(f"/workspaces/{ws}/skills").json()}
    assert "hook-writer" not in names


def test_ask_mode_is_hermess_approval_and_another_workspace_cant_answer(env: Any) -> None:  # noqa: F811
    """Ask mode: Hermes's own Allow / Deny comes before the tool runs (the guard's
    tool_check); a card is never answered from another workspace."""
    from agos_core.actions import hermes_channel

    client, core, _cron, ws = env
    item = {"do": "create_automation", "name": "Wait", "schedule": "0 9 * * *", "instructions": "a"}
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [item]})["ask"] is False
    assert client.put("/cofounder-actions/mode", json={"mode": "ask"}).json() == {"mode": "ask"}
    assert "Approve" in cofounder_actions.instructions(core, ws)
    check = hermes_channel.tool_check(core, "agos_action", {"actions": [item]})
    assert check["ask"] is True and "Wait" in check["message"]
    capability = {"kind": "skill", "name": "x", "on": True}
    assert hermes_channel.tool_check(core, "agos_capability", capability)["ask"] is True
    [card] = _run(core, ws, item)  # he said Allow: it runs
    assert card["status"] == "done"
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    r = client.post(f"/workspaces/{other}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 404
    assert [a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()] == ["Wait"]


def test_agents_get_a_real_job_title(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    assert "Ideas Generator" in cofounder_actions.instructions(core, ws)
    # No title given: a readable one from the name, never the bare slug.
    _member(client, ws, "ideas-generator")
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["name"] == "ideas-generator" and agent["title"] == "Ideas Generator"
    r = client.post(
        f"/workspaces/{ws}/agents",
        json={"name": "script-writer", "definition": {"instructions": "y"}},
    )
    assert r.status_code == 201
    titles = {i["title"] for i in client.get(f"/workspaces/{ws}/agents").json()}
    assert "Script Writer" in titles


def test_rename_by_the_cofounder_or_the_owner_keeps_the_id(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _member(client, ws, "ideas")
    [card] = _run(
        core, ws, {"do": "rename", "kind": "agent", "name": "Ideas", "title": "Ideas Generator"}
    )
    assert card["status"] == "done" and card["canUndo"]
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["title"] == "Ideas Generator" and agent["name"] == "ideas"  # the id never moves
    on = [c for c in client.get(f"/workspaces/{ws}/connectors").json() if c["kind"] == "agent"]
    assert on[0]["on"] and on[0]["title"] == "Ideas Generator"
    client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert client.get(f"/workspaces/{ws}/agents").json()[0]["title"] == "Ideas"
    # The owner renames from the form: same id, new name.
    r = client.put(
        f"/workspaces/{ws}/agents/{agent['id']}",
        json={"name": "ideas", "title": "Idea Scout", "definition": {"instructions": "x"}},
    )
    assert r.status_code == 204, r.text
    assert client.get(f"/workspaces/{ws}/agents").json()[0]["title"] == "Idea Scout"
    [bad] = _run(core, ws, {"do": "rename", "kind": "agent", "name": "nobody", "title": "X"})
    assert bad["status"] == "failed"


def test_creating_an_existing_agent_updates_it_and_undo_restores_it(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _member(client, ws, "ideas", instructions="old role")
    assert "agent `ideas`" in cofounder_actions.instructions(core, ws)
    # The Co-Founder writes "create" for one that exists: it is updated in place.
    [card] = _run(
        core,
        ws,
        {
            "do": "create_agent",
            "name": "ideas",
            "title": "Ideas Generator",
            "instructions": "new " * 5000,
        },
    )
    assert card["status"] == "done", card
    assert card["title"].startswith("Update agent")  # the card says it was an edit
    assert "EDIT, DON'T RECREATE" in cofounder_actions.instructions(core, ws)
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["name"] == "ideas" and agent["title"] == "Ideas Generator"
    assert agent["definition"]["instructions"].startswith("new new")
    # By its display name, with update_agent, only what's given changes.
    [upd] = _run(
        core, ws, {"do": "update_agent", "name": "Ideas Generator", "instructions": "third"}
    )
    assert upd["status"] == "done"
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["title"] == "Ideas Generator" and agent["definition"]["instructions"] == "third"
    client.post(f"/workspaces/{ws}/cofounder-actions/{upd['id']}", json={"choice": "undo"})
    client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["title"] == "Ideas" and agent["definition"]["instructions"] == "old role"
    on = [c for c in client.get(f"/workspaces/{ws}/connectors").json() if c["kind"] == "agent"]
    assert on[0]["on"]  # it was on before, so it stays on


def test_a_failed_card_works_on_try_again(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _member(client, ws, "scripts", instructions="a")
    # A card that failed before updates existed: Try again now updates it.
    [card] = _run(core, ws, {"do": "create_agent", "name": "scripts", "instructions": "b"})
    core.db.execute("UPDATE cofounder_actions SET status='failed' WHERE id = ?", (card["id"],))
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "approve"})
    assert r.json()["status"] == "done"


def test_a_renamed_agent_renames_its_chat(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    from agos_core.actions.workers import open_dm

    _member(client, ws, "ideas")
    dm = open_dm(core, ws, "ideas")
    assert client.get(f"/workspaces/{ws}/chats/{dm}").json()["title"] == "Ideas"
    _run(core, ws, {"do": "update_agent", "name": "ideas", "title": "Ideas Generator"})
    assert client.get(f"/workspaces/{ws}/chats/{dm}").json()["title"] == "Ideas Generator"
    team = client.get(f"/workspaces/{ws}/workers").json()
    assert [m["title"] for m in team["members"]] == ["Ideas Generator"]


def test_small_edits_keep_everything_else(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    from agos_core.storage.layout import workspace_paths

    _member(client, ws, "writer", "Writer", "Line A.\nLine B.")
    cofounder_actions.instructions(core, ws)
    copy = workspace_paths(core.layout, ws).files / "playbooks" / "agents" / "writer.md"
    assert "Line A." in copy.read_text() and "Written by AGOS" in copy.read_text()
    [add] = _run(
        core,
        ws,
        {"do": "update_agent", "name": "Writer", "add_instructions": "Always Darija Latin."},
    )
    [rep] = _run(
        core,
        ws,
        {
            "do": "update_agent",
            "name": "writer",
            "replace": [{"find": "Line B.", "with": "Line B2."}],
        },
    )
    assert add["status"] == rep["status"] == "done"
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["definition"]["instructions"] == "Line A.\nLine B2.\n\nAlways Darija Latin."
    [bad] = _run(
        core,
        ws,
        {"do": "update_agent", "name": "writer", "replace": [{"find": "nope", "with": "x"}]},
    )
    assert bad["status"] == "failed" and "Couldn't find" in bad["error"]
    assert (
        client.get(f"/workspaces/{ws}/agents")
        .json()[0]["definition"]["instructions"]
        .endswith("Latin.")
    )


def test_a_new_workspace_never_sees_or_changes_another_workspaces_team(env: Any) -> None:  # noqa: F811
    """Workspaces are separate 100%: a new project's Co-Founder doesn't know the other
    project's agents, doesn't read their text, and creating one with the same name
    makes its own agent instead of changing the other one."""
    from agos_core.storage.layout import workspace_paths

    client, core, _cron, ws = env
    other = client.post(
        "/workspaces", json={"name": "Smart Investor", "defaultModel": MODEL}
    ).json()["id"]
    _member(client, ws, "ideas-generator", "Ideas Generator", "Video ideas for Sam's content team.")

    # The new project knows nothing of it: not in its Co-Founder's list, no copy of its text.
    text = cofounder_actions.instructions(core, other)
    listing = text.split("don't create them again:")[1]
    assert "ideas-generator" not in listing and "Sam" not in text
    team = workspace_paths(core.layout, other).files / ".agos" / "team"
    assert not any("Sam" in f.read_text() for f in team.glob("*.md"))

    # Its Co-Founder changing "ideas-generator" finds none there: the first is untouched.
    [mine] = _run(
        core,
        other,
        {"do": "update_agent", "name": "ideas-generator", "instructions": "Investing video ideas."},
    )
    assert mine["status"] == "failed", mine
    _member(client, other, "ideas-generator", "Ideas Generator", "Investing video ideas.")
    # Two projects, two separate agents with the same name: each team has its own.
    theirs = {a["workspace_id"]: a for a in _all_agents(core) if a["name"] == "ideas-generator"}
    assert theirs[ws]["definition"]["instructions"] == "Video ideas for Sam's content team."
    assert theirs[other]["definition"]["instructions"] == "Investing video ideas."
    assert [a["name"] for a in client.get(f"/workspaces/{other}/agents").json()] == [
        "ideas-generator"
    ]
    # Renaming from the new project changes only its own agent.
    [ok] = _run(
        core, other, {"do": "rename", "kind": "agent", "name": "ideas-generator", "title": "X"}
    )
    assert ok["status"] == "done", ok
    titles = {a["workspace_id"]: a["title"] for a in _all_agents(core)}
    assert titles == {ws: "Ideas Generator", other: "X"}


def test_the_tools_list_shows_only_this_workspaces_team(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    from agos_core.actions import apps as apps_actions
    from agos_core.actions import capabilities

    client, core, _cron, ws = env
    # The Nous apps list needs a real Hermes; this test is about the team only.
    monkeypatch.setattr(apps_actions, "workspace_apps", lambda core, workspace_id: [])
    other = client.post(
        "/workspaces", json={"name": "Smart Investor", "defaultModel": MODEL}
    ).json()["id"]
    _member(client, ws, "brand-voice-keeper", instructions="Sam's voice.")
    assert "brand-voice-keeper" in capabilities.instructions(core, ws)
    assert "brand-voice-keeper" not in capabilities.instructions(core, other)


def test_steps_and_reads_are_added_never_wiped() -> None:
    """A change names only what changes: the steps and rule files it doesn't name stay."""
    steps = [
        {"key": "a", "title": "A", "agent": "x", "waits_on": []},
        {"key": "b", "title": "B", "agent": "y", "waits_on": ["a"]},
    ]
    out = cofounder_actions.merged_steps(steps, [{"key": "b", "title": "B2"}, {"key": "c"}], [])
    assert [s["key"] for s in out] == ["a", "b", "c"]
    assert out[1]["title"] == "B2" and out[1]["agent"] == "y"
    assert [s["key"] for s in cofounder_actions.merged_steps(steps, [], ["a"])] == ["b"]
    reads = [{"path": "team.md", "mode": "always"}, {"path": "flow.md", "mode": "always"}]
    out_r = cofounder_actions.merged_reads(reads, [{"path": "flow.md", "mode": "demand"}], [])
    assert out_r == [{"path": "team.md", "mode": "always"}, {"path": "flow.md", "mode": "demand"}]
    assert cofounder_actions.merged_reads(reads, [], ["team.md"]) == [reads[1]]
