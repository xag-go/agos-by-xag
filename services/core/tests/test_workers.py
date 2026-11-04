"""Workers: a Slack-like team per workspace — DMs and groups (a group chat is a
Hermes room: tests/test_rooms.py)."""

from typing import Any

import chat_rig
import pytest
from chat_rig import Env, FakeHermes, get, say, settle
from fastapi.testclient import TestClient

from agos_core.storage.layout import workspace_paths

env = chat_rig.env  # the chat tests' fixture (fake Hermes)

# ---- through the API, with a fake Hermes -----------------------------------------


def agent(client: TestClient, ws: str, name: str, title: str, summary: str = "") -> None:
    r = client.post(
        f"/workspaces/{ws}/agents",
        json={
            "name": name,
            "title": title,
            "summary": summary,
            "definition": {"instructions": f"You are {title}."},
        },
    )
    assert r.status_code == 201, r.text  # made in this team: on straight away


def finish(fake: FakeHermes, run: str, text: str) -> None:
    fake.push(run, {"event": "run.completed", "output": text})


def answer_runs(fake: FakeHermes, replies: dict[str, str]) -> bool:
    """Answers the runs that exist yet; False so it can lead an `or` chain."""
    for run, text in replies.items():
        if run in fake.events and not fake.events[run]:
            finish(fake, run, text)
    return False


def test_team_lists_the_cofounder_and_members_on_in_connectors(env: Env) -> None:
    client, _, _, ws = env
    agent(client, ws, "designer", "Designer", "Logos and visuals")
    off = client.post(
        f"/workspaces/{ws}/agents", json={"name": "off-agent", "definition": {"instructions": "x"}}
    ).json()["id"]
    client.put(f"/workspaces/{ws}/connectors/{off}", json={"on": False})
    data = client.get(f"/workspaces/{ws}/workers").json()
    assert data["cofounder"]["name"] is None and data["cofounder"]["title"] == "Co-Founder"
    assert data["cofounder"]["profile"] == f"agos-{ws}"
    assert [(m["name"], m["role"]) for m in data["members"]] == [("designer", "Logos and visuals")]
    # The Co-Founder's own chat is there from the start (Hermes's home channel, where its
    # Kanban notifier tells the owner); members' DMs come when opened.
    assert data["groups"] == [] and [c["agent"] for c in data["dms"]] == [None]


def test_a_dm_is_one_per_member_and_talks_as_that_agent(env: Env) -> None:
    client, fake, core, ws = env
    agent(client, ws, "designer", "Designer")
    r = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "designer"})
    dm = r.json()["id"]
    again = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "designer"}).json()["id"]
    assert again == dm
    assert client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "ghost"}).status_code == 400
    say(client, ws, dm, "Draw a logo")
    settle(
        core,
        lambda: (
            answer_runs(fake, {"run_1": "Here it is."})
            or (not get(client, ws, dm)["working"] and len(get(client, ws, dm)["messages"]) == 2)
        ),
    )
    body = fake.bodies[0]
    # Its own SOUL.md (its role), and the chat's name as Hermes's conversation topic.
    assert "You are Designer." in body["instructions"]
    assert "**Channel Topic:** Designer" in body["instructions"]
    assert get(client, ws, dm)["messages"][1]["speaker"] == "designer"
    # DMs and groups stay out of the classic Chats list; the Workers list has them.
    assert [c["title"] for c in client.get(f"/workspaces/{ws}/chats").json()] == ["General"]
    dms = client.get(f"/workspaces/{ws}/workers").json()["dms"]
    assert [c["id"] for c in dms if c["agent"]] == [dm]
    # A DM can't be turned into another agent from the chat header.
    r = client.put(f"/workspaces/{ws}/chats/{dm}", json={"agent": ""})
    assert r.status_code == 400
    # Hidden then opened again: the same conversation comes back, history kept.
    client.delete(f"/workspaces/{ws}/chats/{dm}")
    back = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "designer"}).json()["id"]
    assert back == dm and len(get(client, ws, dm)["messages"]) == 2


def test_group_members_must_be_on(env: Env) -> None:
    client, _fake, _core, ws = env
    agent(client, ws, "designer", "Designer")
    r = client.post(f"/workspaces/{ws}/workers/groups", json={"title": "X", "members": ["ghost"]})
    assert r.status_code == 400 and "ghost" in r.json()["detail"]
    g = client.post(
        f"/workspaces/{ws}/workers/groups", json={"title": "X", "members": ["designer"]}
    ).json()["id"]
    item_id = next(i["id"] for i in client.get(f"/workspaces/{ws}/agents").json())
    client.put(f"/workspaces/{ws}/connectors/{item_id}", json={"on": False})
    r = client.put(f"/workspaces/{ws}/workers/groups/{g}/members", json={"members": ["designer"]})
    assert r.status_code == 400


@pytest.mark.parametrize("kind", ["dm", "group"])
def test_workers_stay_inside_their_workspace(env: Env, kind: str) -> None:
    client, _, _, ws = env
    agent(client, ws, "designer", "Designer")
    other = client.post(
        "/workspaces", json={"name": "Other", "defaultModel": get_model(client, ws)}
    ).json()["id"]
    if kind == "dm":
        r = client.post(f"/workspaces/{other}/workers/dm", json={"agent": "designer"})
    else:
        r = client.post(
            f"/workspaces/{other}/workers/groups", json={"title": "x", "members": ["designer"]}
        )
    assert r.status_code == 400  # not on in Other's Connectors


def get_model(client: TestClient, ws: str) -> Any:
    return client.get(f"/workspaces/{ws}").json()["defaultModel"]


def test_tasks_from_team_conversations_go_on_the_board_by_themselves(env: Env) -> None:
    """A task in a team conversation (a DM, a group) is Hermes's own kanban_create,
    given to who does it: it starts at once; "check with me" makes it wait for him."""
    client, fake, core, ws = env
    agent(client, ws, "designer", "Designer")
    dm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": ""}).json()["id"]
    say(client, ws, dm, "Prepare the label for the 50 ml bottle, gold on green, for Monday.")
    settle(core, lambda: bool(fake.bodies))
    # The rules on tasks are the SOUL.md's (Hermes's), not a text AGOS adds per turn.
    rules = " ".join(fake.bodies[0]["instructions"].split())
    assert "[AGOS" not in rules
    assert "kanban_create" in rules and "agos_add_task" not in rules
    assert "goes on the" in rules and "Never for a question" in rules
    assert "dir hadi task" in rules and 'initial_status = "blocked"' in rules
    assert "a-<name>" in rules and "idempotency_key" in rules
    # Whether he is asked first is his Autonomy rule "Create Kanban cards" (the guard).
    from agos_core.hermes_plugin.agos_guard import decide

    assert decide({}, "", "kanban_create", {"title": "Label"}) is None
    rule = {"rules": {"": {"cards": "ask"}}}
    asked = decide(rule, "", "kanban_create", {"title": "Label"})
    assert asked is not None and asked["action"] == "approve"


def test_autonomy_rules_follow_the_agent_answering_and_never_is_hermes_own(env: Env) -> None:
    """Who answers comes from AGOS when the answer starts (the guard applies that
    agent's rules); a Never for everyone on a whole toolset is Hermes's own
    agent.disabled_toolsets."""
    import json

    client, _fake, core, ws = env
    from agos_core.actions import autonomy, hermes_channel, library

    agent(client, ws, "writer", "Writer")
    dm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "writer"}).json()["id"]
    start = hermes_channel.turn_start(core, ws, f"agos:{dm}", "s-1")
    assert start["agent"] == "writer"
    mdm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": ""}).json()["id"]
    assert hermes_channel.turn_start(core, ws, f"agos:{mdm}", "s-2")["agent"] == ""
    autonomy.set_rule(core, ws, "*", "browser", "never")
    assert autonomy.never_toolsets(core, ws) == ["browser"]
    pairs = library.profile_settings([], never=autonomy.never_toolsets(core, ws))
    assert "browser" in json.loads(pairs["agent.disabled_toolsets"])
    # One member allowed: the toolset stays (the guard blocks the others).
    autonomy.set_rule(core, ws, "writer", "browser", "do")
    assert autonomy.never_toolsets(core, ws) == []
    # Files share a toolset with reading: always the guard's.
    autonomy.set_rule(core, ws, "*", "files", "never")
    assert "file" not in autonomy.never_toolsets(core, ws)


def test_the_cofounder_looks_things_up_in_hermes(env: Env) -> None:
    """No AGOS copy of the project for the Co-Founder: it is told where to look in
    Hermes (its sessions, its members' profiles, the Kanban, cron), and only there."""
    client, fake, core, ws = env
    mdm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": ""}).json()["id"]
    say(client, ws, mdm, "Where do we stand?")
    settle(
        core,
        lambda: (
            answer_runs(fake, {"run_1": "All good."}) or len(get(client, ws, mdm)["messages"]) == 2
        ),
    )
    said = fake.bodies[-1]["instructions"]
    assert "you know the whole project" in said and "session_search" in said
    assert "kanban_list" in said and "another workspace" in said
    assert not (workspace_paths(core.layout, ws).files / ".agos" / "project-log").exists()


def test_a_session_given_to_an_agent_is_answered_by_its_own_hermes(env: Env) -> None:
    """The role lives in the member's SOUL.md (with the workspace's rules): a Session
    given to that agent is that member's Hermes conversation; AGOS adds no text."""
    from agos_core.actions import agent_profiles, hermes_channel
    from agos_core.engine import identity

    client, fake, core, ws = env
    agent(client, ws, "designer", "Designer")
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Logo work"}).json()["id"]
    assert (
        client.put(f"/workspaces/{ws}/chats/{chat}", json={"agent": "designer"}).status_code == 204
    )
    assert hermes_channel.owner_member(core, ws, f"agos:{chat}") == "designer"
    soul = (core.engine.profile_home(agent_profiles.key(ws, "designer")) / "SOUL.md").read_text()
    assert "You are Designer." in soul and identity.RULES in soul
    say(client, ws, chat, "Draw a logo")
    settle(core, lambda: bool(fake.bodies))
    body = fake.bodies[0]["instructions"]
    assert "You are Designer." in body and "**Channel Topic:** Logo work" in body
    assert "[AGOS" not in body


def test_a_dm_s_name_is_its_member_s_hermes_name(env: Env) -> None:
    """No copy in chats.title: the DM shows its member's Hermes display name (the
    profile.yaml Hermes's write_profile_meta writes), so a rename shows at once.
    An old copy moves once (into the profile when it has none), and a DM whose
    member profile is gone keeps its name."""
    from agos_core.actions import team
    from agos_core.engine import profile_meta

    client, _, core, ws = env
    agent(client, ws, "designer", "Designer")
    dm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "designer"}).json()["id"]
    cofounder = next(
        c["id"] for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if not c["agent"]
    )
    stored = core.db.execute(
        "SELECT title FROM chats WHERE id IN (?, ?)", (dm, cofounder)
    ).fetchall()
    assert [r["title"] for r in stored] == ["", ""]
    assert get(client, ws, dm)["title"] == "Designer"
    assert get(client, ws, cofounder)["title"] == "Co-Founder"
    where = team.home(core, ws, "designer")
    assert where is not None
    core.engine.set_display_name(where, "Brand designer")  # renamed in Hermes
    assert get(client, ws, dm)["title"] == "Brand designer"
    # An old copy (before step 28) and a profile without a name: moved into Hermes.
    core.db.execute("UPDATE chats SET title = 'Logo maker' WHERE id = ?", (dm,))
    core.db.execute("UPDATE chats SET title = 'Co-Founder' WHERE id = ?", (cofounder,))
    core.engine.set_display_name(where, "")
    assert team.move_dm_titles(core) == 2
    assert profile_meta.display_name(profile_meta.read(where)) == "Logo maker"
    assert get(client, ws, dm)["title"] == "Logo maker"
    assert team.move_dm_titles(core) == 0  # once
    # A DM whose member profile is gone keeps its name.
    core.db.execute(
        "INSERT INTO chats (workspace_id, title, channel, kind, agent, created_at, updated_at)"
        " VALUES (?, 'Old writer', 'web', 'dm', 'writer', 'x', 'x')",
        (ws,),
    )
    assert team.move_dm_titles(core) == 0
    gone = core.db.execute("SELECT title FROM chats WHERE agent = 'writer'").fetchone()
    assert gone["title"] == "Old writer"


def test_renaming_a_dm_renames_its_member_in_hermes_and_survives_a_restart(env: Env) -> None:
    """B4/B2 (925047d): a DM's rename is its member's Hermes display name (no
    chats.title copy), so the start-up mover (team.move_dm_titles) can't lose it."""
    from agos_core.actions import team
    from agos_core.engine import profile_meta

    client, _, core, ws = env
    agent(client, ws, "designer", "Designer")
    dm = client.post(f"/workspaces/{ws}/workers/dm", json={"agent": "designer"}).json()["id"]
    r = client.put(f"/workspaces/{ws}/chats/{dm}", json={"title": "Logo maker"})
    assert r.status_code == 204, r.text
    stored = core.db.execute("SELECT title FROM chats WHERE id = ?", (dm,)).fetchone()
    assert stored["title"] == ""
    where = team.home(core, ws, "designer")
    assert where is not None
    assert profile_meta.display_name(profile_meta.read(where)) == "Logo maker"
    team.move_dm_titles(core)  # what every core start runs
    assert get(client, ws, dm)["title"] == "Logo maker"
    cofounder = next(
        c["id"] for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if not c["agent"]
    )
    r = client.put(f"/workspaces/{ws}/chats/{cofounder}", json={"title": "Boss"})
    assert r.status_code == 400 and get(client, ws, cofounder)["title"] == "Co-Founder"
