"""Each team member is its own Hermes profile: same sandbox and setup as the
workspace, its own SOUL / memory / skills / model, never the Co-Founder's tools."""

import json
from typing import Any

from test_engine_sync import profile_dir
from test_library import MODEL, SKILL, env, item, skill, turn_on, ws  # noqa: F401 - fixture

from agos_core.actions import agent_profiles


def add_agent(client: Any, w: str, name: str, **definition: Any) -> int:
    r = client.post(
        f"/workspaces/{w}/agents",
        json={
            "name": name,
            "title": name.replace("-", " ").title(),
            "definition": {"instructions": f"You write {name} things.", **definition},
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_a_member_is_its_own_hermes_profile(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    sid = skill(client, a)
    writer = add_agent(client, a, "script-writer")
    profile = profile_dir(home, f"agos-{a}--a-script-writer")
    assert (profile / "SOUL.md").is_file()
    soul = (profile / "SOUL.md").read_text()
    assert "Script Writer" in soul and "You write script-writer things." in soul
    config = runner.config[f"agos-{a}--a-script-writer"]
    off = json.loads(config["agent.disabled_toolsets"])
    assert "cronjob" in off  # Hermes's scheduler is the Co-Founder's
    assert json.loads(config["mcp_servers"]) == json.loads(
        runner.config[f"agos-{a}"]["mcp_servers"]
    )
    # The workspace's skills: its Co-Founder's folder, read where it is (no copy),
    # with the same ones off.
    own = str(profile_dir(home, f"agos-{a}") / "skills" / "agos-library")
    cofounder = json.loads(runner.config[f"agos-{a}"]["skills.external_dirs"])
    assert json.loads(config["skills.external_dirs"]) == [*cofounder, own]
    assert str(core.layout.global_dir / "skills") not in json.loads(config["skills.external_dirs"])
    assert "invoice-check" not in json.loads(config["skills.disabled"])
    assert not (profile / "skills" / "agos-library").exists()
    # The owner's Autonomy rules for it.
    policy = json.loads((profile / "agos-guard.json").read_text())
    assert policy["member"] == "script-writer" and "" in policy["rules"]
    # Never another workspace's.
    assert not list((home / "profiles").glob(f"agos-{b}--a-*"))
    assert agent_profiles.existing(core, a) == [(a, "script-writer")]
    # Off the team: kept (its memory), not deleted; deleted: gone.
    client.put(f"/workspaces/{a}/connectors/{writer}", json={"on": False})
    assert (profile / "SOUL.md").is_file()
    assert client.delete(f"/workspaces/{a}/agents/{writer}").status_code in (200, 204)
    client.put(f"/workspaces/{a}/connectors/{sid}", json={"on": True})
    agent_profiles.apply_team(core, a, {}, {})
    assert agent_profiles.existing(core, a) == []


def test_a_members_conversations_go_to_its_own_gateway(env: Any) -> None:  # noqa: F811
    """Routing: what is for a member (its DM, its turn in a group) is taken only by
    its own gateway; the workspace's gateway (the Co-Founder) never takes it; a member
    has no Telegram of its own."""
    from agos_core.actions import hermes_channel
    from agos_core.db.rows import now

    client, core, _runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    assert agent_profiles.ready(core, a, "script-writer")
    bridge = json.loads(
        (profile_dir(home, f"agos-{a}--a-script-writer") / "agos-bridge.json").read_text()
    )
    assert bridge["member"] == "script-writer" and bridge["workspace"] == a
    dm = core.db.execute(
        "INSERT INTO chats (workspace_id, title, kind, agent, channel, created_at, updated_at) "
        "VALUES (?, 'SW', 'dm', 'script-writer', 'web', ?, ?)",
        (a, now(), now()),
    ).lastrowid
    cofounder = cofounder_chat(core, a)
    for address in (f"agos:{dm}", f"agos:{cofounder}", f"agos:{cofounder}.script-writer"):
        core.db.execute(
            "INSERT INTO hermes_inbox (workspace_id, chat_ref, text, created_at) VALUES (?, ?, 'hi', ?)",
            (a, address, now()),
        )
    assert hermes_channel.owner_member(core, a, f"agos:{dm}") == "script-writer"
    assert hermes_channel.owner_member(core, a, f"agos:{cofounder}") is None
    mine = {
        i["chat"] for i in hermes_channel.take_inbox(core, a, agos=True, member="script-writer")
    }
    assert mine == {f"agos:{dm}", f"agos:{cofounder}.script-writer"}
    theirs = {i["chat"] for i in hermes_channel.take_inbox(core, a, agos=True)}
    assert theirs == {f"agos:{cofounder}"}
    assert hermes_channel.take_inbox(core, a, member="script-writer") == []


def test_a_member_never_has_the_cofounders_tools() -> None:
    from agos_core.hermes_plugin import agos_guard

    assert {
        "agos_action",
        "agos_capability",
        "kanban_create",
    } <= agos_guard.COFOUNDER_TOOLS
    assert "agos_add_task" not in agos_guard.COFOUNDER_TOOLS  # Hermes's kanban_create
    assert "agos_plan" not in agos_guard.COFOUNDER_TOOLS  # the old board's plans are gone
    assert "agos_handoff" not in agos_guard.COFOUNDER_TOOLS  # groups are Hermes rooms
    from agos_core.hermes_plugin.agos_guard import bridge

    assert not hasattr(bridge, "handoff_tool") and not hasattr(bridge, "HANDOFF_SCHEMA")


def test_each_workspace_has_its_own_kanban(env: Any) -> None:  # noqa: F811
    """Hermes Kanban, one per workspace: Hermes's own default board of the root
    (no pin: the root is the board home of its profiles), the Co-Founder's gateway
    dispatches only its members' cards, members never dispatch."""
    from agos_core.actions import agent_profiles

    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "script-writer")
    member = profile_dir(home, f"agos-{a}--a-script-writer") / ".env"
    for env_file in (
        profile_dir(home, f"agos-{a}") / ".env",
        profile_dir(home, f"agos-{b}") / ".env",
        member,
    ):
        assert "HERMES_KANBAN_HOME" not in env_file.read_text()
    assert agent_profiles.board_db(core, a) == core.engine.root(a) / "kanban.db"
    assert agent_profiles.board_db(core, a) != agent_profiles.board_db(core, b)
    cofounder = runner.config[f"agos-{a}"]
    assert cofounder["kanban.dispatch_in_gateway"] == "true"
    assert json.loads(cofounder["kanban.dispatch_profiles"]) == ["default", "a-script-writer"]
    assert "kanban" not in json.loads(cofounder["agent.disabled_toolsets"])
    worker = runner.config[f"agos-{a}--a-script-writer"]
    assert worker["kanban.dispatch_in_gateway"] == "false"
    assert "kanban" not in json.loads(worker["agent.disabled_toolsets"])


def test_a_new_sandbox_setup_keeps_the_cofounders_board_tools(env: Any) -> None:  # noqa: F811
    """Live bug: a sync rewrote the sandbox settings (board tools off) while the
    connectors' pairs looked unchanged, so the Co-Founder lost Hermes's Kanban tools."""
    from agos_core.actions import engine as engine_actions

    client, core, runner, home = env
    a = ws(client, "Alpha")
    assert "kanban" not in json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])
    (profile_dir(home, f"agos-{a}") / ".agos-applied").unlink(missing_ok=True)
    engine_actions.sync_workspace(core, a)
    assert "kanban" not in json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])


def test_a_member_on_a_card_waits_for_the_owners_ok(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """On a Kanban card nobody is there to click Allow: an "Ask me" action is stopped,
    AGOS asks him in the Co-Founder's chat (and phone), and Allow once lets that card do it."""
    from agos_core.actions import kanban_asks
    from agos_core.hermes_plugin import agos_guard

    client, core, runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    member_home = profile_dir(home, f"agos-{a}--a-script-writer")
    policy = {"member": "script-writer", "rules": {"script-writer": {"commands": "ask"}}}
    posted: list[dict[str, Any]] = []

    class FakeBridge:
        @staticmethod
        def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
            posted.append(body)
            kanban_asks.ask(
                core, a, body["card"], body["member"], body["action"], body["label"], body["detail"]
            )
            return {"asked": True}

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: FakeBridge)
    monkeypatch.setattr(
        agos_guard.board_waits, "_allowed", lambda card: kanban_asks_allowed(member_home, card)
    )
    block = agos_guard.card_ask(policy, "t_1", "terminal", {"command": "python3 check.py"})
    assert block is not None and block["action"] == "block" and "kanban_block" in block["message"]
    assert '"needs_input"' in block["message"]  # Hermes's typed wait for a person
    agos_guard.card_ask(policy, "t_1", "terminal", {"command": "python3 check.py"})
    waiting = kanban_asks.waiting(core, a)
    assert len(waiting) == 1 and waiting[0]["detail"] == "python3 check.py"  # asked once
    live = client.get(f"/workspaces/{a}/chats/{cofounder_chat(core, a)}/live").json()
    assert [x["card"] for x in live["asks"]] == ["t_1"]
    r = client.post(f"/workspaces/{a}/kanban-asks/{waiting[0]['id']}", json={"allow": True})
    assert r.status_code == 200, r.text
    assert agos_guard.card_ask(policy, "t_1", "terminal", {"command": "x"}) is None  # this card
    assert (
        agos_guard.card_ask(policy, "t_2", "terminal", {"command": "x"}) is not None
    )  # not others
    assert kanban_asks.waiting(core, a)[0]["card"] == "t_2"
    calls = [c for c in runner.calls if "kanban" in c]
    assert any("unblock" in c and "t_1" in c for c in calls)


def kanban_asks_allowed(home: Any, card: str) -> set[str]:
    from agos_core.actions.kanban_asks import ALLOWED_FILE

    try:
        return set(json.loads((home / ALLOWED_FILE).read_text()).get(card) or [])
    except (OSError, ValueError):
        return set()


def cofounder_chat(core: Any, workspace_id: str) -> int:
    from agos_core.actions.services.channel import owner_needs
    from agos_core.db.rows import now

    found = owner_needs.cofounder_chat(core, workspace_id)
    if found is not None:
        return found
    return int(
        core.db.execute(
            "INSERT INTO chats (workspace_id, title, kind, channel, created_at, updated_at) "
            "VALUES (?, 'M', 'dm', 'web', ?, ?)",
            (workspace_id, now(), now()),
        ).lastrowid
    )


def test_the_kanban_page_drives_hermess_own_board(env: Any) -> None:  # noqa: F811
    """AGOS keeps no copy: cards are made, assigned, commented and moved through
    Hermes's Kanban, on this workspace's board only; members show by job title."""
    client, _core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "script-writer")
    r = client.post(
        f"/workspaces/{a}/kanban",
        json={"title": "Write the hook", "body": "For idea 12", "member": "script-writer"},
    )
    assert r.status_code == 201, r.text
    card = r.json()["id"]
    assert runner.kanban[f"agos-{a}"][card]["assignee"] == "a-script-writer"
    assert not runner.kanban.get(f"agos-{b}")  # the other workspace's board is untouched
    board = client.get(f"/workspaces/{a}/kanban").json()
    assert [(c["title"], c["member"], c["status"]) for c in board["cards"]] == [
        ("Write the hook", "script-writer", "ready")
    ]
    # The Co-Founder, the Founder (the owner himself: actions/founder.py), the team.
    assert [m["name"] for m in board["members"]] == ["cofounder", "founder", "script-writer"]
    assert client.get(f"/workspaces/{b}/kanban").json()["cards"] == []
    said = client.post(f"/workspaces/{a}/kanban/{card}/comment", json={"text": "Short"})
    # Step 58: the answer says whom it woke (only the card's member, here on Ready).
    assert said.status_code == 200 and [w["who"] for w in said.json()["woke"]] == ["script-writer"]
    shown = client.get(f"/workspaces/{a}/kanban/{card}").json()
    assert shown["comments"] == [{"id": 0, "author": "You", "body": "Short", "at": 1_800_000_100}]
    assert (
        client.post(f"/workspaces/{a}/kanban/{card}/act", json={"action": "block"}).status_code
        == 204
    )
    assert runner.kanban[f"agos-{a}"][card]["status"] == "blocked"
    assert (
        client.post(f"/workspaces/{a}/kanban/{card}/assign", json={"member": "nobody"}).status_code
        == 400
    )
    assert (
        client.post(f"/workspaces/{a}/kanban", json={"title": "x", "member": "ghost"}).status_code
        == 400
    )
    assert client.get(f"/workspaces/{a}/kanban/..%2Fx").status_code == 404


def test_creating_kanban_cards_is_an_autonomy_rule() -> None:
    from agos_core.actions import autonomy
    from agos_core.hermes_plugin import agos_guard

    assert agos_guard.action_of("kanban_create") == "cards"
    assert agos_guard.action_of("kanban_complete") is None
    assert autonomy.DEFAULTS["cards"] == "ask"
    policy = {"rules": {"": {"cards": "ask"}}}
    asked = agos_guard.decide(policy, "", "kanban_create", {"title": "x"})
    assert asked is not None and asked["action"] == "approve"
    never = agos_guard.decide({"rules": {"*": {"cards": "never"}}}, "", "kanban_create", {})
    assert never is not None and never["action"] == "block"


def test_a_new_card_carries_criteria_model_goal_and_what_it_waits_for(env: Any) -> None:  # noqa: F811
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    first = client.post(f"/workspaces/{a}/kanban", json={"title": "Idea", "triage": True}).json()[
        "id"
    ]
    r = client.post(
        f"/workspaces/{a}/kanban",
        json={
            "title": "Script",
            "body": "Write it",
            "member": "script-writer",
            "criteria": ["Under 60 s", " "],
            "model": MODEL,
            "goal": True,
            "parents": [first],
        },
    )
    assert r.status_code == 201, r.text
    card = runner.kanban[f"agos-{a}"][r.json()["id"]]
    assert card["body"] == "Write it\n\n## Success criteria\n- Under 60 s"
    assert card["goal"] and card["parents"] == [first] and card["model_override"] == MODEL["model"]
    assert runner.kanban[f"agos-{a}"][first]["status"] == "triage"
    bad = client.post(f"/workspaces/{a}/kanban", json={"title": "x", "parents": ["../x"]})
    assert bad.status_code == 400


def test_a_card_answers_shows_its_plan_and_has_its_own_chat(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    import sqlite3

    from agos_core.actions import hermes_channel
    from agos_core.db.rows import now

    client, core, runner, home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    card = client.post(
        f"/workspaces/{a}/kanban", json={"title": "Hook", "member": "script-writer"}
    ).json()["id"]
    # His answer to a card waiting for him: a comment, and Hermes unblocks it.
    runner.kanban[f"agos-{a}"][card]["status"] = "blocked"
    r = client.post(f"/workspaces/{a}/kanban/{card}/answer", json={"text": "Use idea 12"})
    assert r.status_code == 204, r.text
    shown = runner.kanban[f"agos-{a}"][card]
    assert shown["status"] == "ready" and shown["comments"][-1]["body"] == "Use idea 12"
    # Its plan: Hermes's own todo list from the member's work session on the card.
    profile = f"agos-{a}--a-script-writer"
    state = profile_dir(home, profile) / "state.db"
    db = sqlite3.connect(state)
    db.executescript(
        "CREATE TABLE sessions (id TEXT, source TEXT);"
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
        " content TEXT, tool_name TEXT);"
    )
    db.execute("INSERT INTO sessions VALUES ('s1', 'kanban')")
    db.execute(
        "INSERT INTO messages (session_id, role, content) VALUES ('s1', 'user', ?)",
        (f"work kanban task {card}",),
    )
    db.execute(
        "INSERT INTO messages (session_id, role, content, tool_name) VALUES ('s1', 'tool', ?, 'todo')",
        (json.dumps({"todos": [{"id": "1", "content": "Read idea", "status": "completed"}]}),),
    )
    db.commit()
    db.close()
    detail = client.get(f"/workspaces/{a}/kanban/{card}").json()
    assert detail["plan"] == [{"text": "Read idea", "status": "completed"}]
    assert detail["chatId"] is None
    # Its own chat: with the card's member; the card is in the conversation's topic.
    chat = client.post(f"/workspaces/{a}/kanban/{card}/chat").json()["id"]
    assert client.post(f"/workspaces/{a}/kanban/{card}/chat").json()["id"] == chat
    assert hermes_channel.owner_member(core, a, f"agos:{chat}") == "script-writer"
    core.db.execute(
        "INSERT INTO hermes_inbox (workspace_id, chat_ref, text, created_at) VALUES (?, ?, 'hi', ?)",
        (a, f"agos:{chat}", now()),
    )
    taken = hermes_channel.take_inbox(core, a, agos=True, member="script-writer")
    assert taken and taken[0]["text"] == "hi"
    assert taken[0]["topic"].endswith(f"(Kanban card {card})")
    # Its name is the Hermes card's title (no copy): a renamed card shows at once.
    from agos_core.actions import kanban_board
    from agos_core.actions.services.board import kanban_db

    def facts(core: Any, ws: str, ids: list[str]) -> dict[str, dict[str, str]]:
        cards = runner.kanban[f"agos-{ws}"]
        return {c: {"title": str(cards[c]["title"])} for c in ids if c in cards}

    monkeypatch.setattr(kanban_board, "facts", facts)
    monkeypatch.setattr(kanban_db, "facts", facts)  # the card chats' one-time title move
    row = core.db.execute("SELECT title, agent FROM chats WHERE id = ?", (chat,)).fetchone()
    assert row["title"] == ""
    title = runner.kanban[f"agos-{a}"][card]["title"]
    assert client.get(f"/workspaces/{a}/chats/{chat}").json()["title"] == f"Card: {title}"
    runner.kanban[f"agos-{a}"][card]["title"] = "Script, take two"
    assert client.get(f"/workspaces/{a}/chats/{chat}").json()["title"] == "Card: Script, take two"
    # An old copy goes once the board holds the card.
    core.db.execute("UPDATE chats SET title = 'Card: old' WHERE id = ?", (chat,))
    assert kanban_board.move_card_chat_titles(core) == 1
    assert kanban_board.move_card_chat_titles(core) == 0
    # Hermes reassigns the card: its chat is with the member Hermes has on it now.
    add_agent(client, a, "editor")
    old = runner.kanban[f"agos-{a}"][card]["assignee"]
    runner.kanban[f"agos-{a}"][card]["assignee"] = str(old).replace("script-writer", "editor")
    assert client.get(f"/workspaces/{a}/kanban/{card}").json()["chatId"] is None
    other = client.post(f"/workspaces/{a}/kanban/{card}/chat").json()["id"]
    assert other != chat
    assert hermes_channel.owner_member(core, a, f"agos:{other}") == "editor"
    assert client.get(f"/workspaces/{a}/kanban/{card}").json()["chatId"] == other


def test_what_happens_on_the_kanban_reaches_the_cofounders_chat(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Hermes's own Kanban notifier tells the owner: a card that starts with no chat
    following it gets the Co-Founder's conversation as its subscriber (`wake`: the
    Co-Founder's turn is the one message). AGOS reads nothing itself."""
    import sqlite3
    import sys
    import types

    from agos_core.actions import hermes_channel
    from agos_core.actions.services.channel import owner_needs
    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    cofounder = cofounder_chat(core, a)
    home = core.engine.profile_home(a)
    written = json.loads((home / hermes_channel.BRIDGE_FILE).read_text())
    assert written["notify"] == {
        "platform": "agos",
        "chatId": str(cofounder),
        "chatType": "dm",
        "userId": hermes_channel.AGOS_OWNER,
    }
    assert owner_needs.kanban_notify_target(core, a) == written["notify"]

    # In the gateway: Hermes's claim hook → the plugin subscribes through Hermes's
    # own kanban_db_notify (stand-ins here, Hermes isn't installed in the tests).
    subs: dict[str, list[dict[str, Any]]] = {"t_1": [], "t_2": [{"platform": "telegram"}]}
    made: list[dict[str, Any]] = []
    connect = types.ModuleType("hermes_cli.kanban_db_connect")
    notify = types.ModuleType("hermes_cli.kanban_db_notify")
    connect.connect = lambda board=None: types.SimpleNamespace(close=lambda: None)  # type: ignore[attr-defined]
    notify.list_notify_subs = lambda conn, task_id: subs.get(task_id, [])  # type: ignore[attr-defined]
    notify.add_notify_sub = lambda conn, **kw: made.append(kw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_connect", connect)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_notify", notify)
    monkeypatch.setattr(plugin, "bridge", lambda: written)
    plugin.kanban_claimed(task_id="t_1", board=None, profile_name="default")
    plugin.kanban_claimed(task_id="t_2", board=None, profile_name="default")  # a chat follows it
    assert made == [
        {
            "task_id": "t_1",
            "platform": "agos",
            "chat_id": str(cofounder),
            "thread_id": None,
            "user_id": hermes_channel.AGOS_OWNER,
            "chat_type": "dm",
            "notifier_profile": "default",
            "delivery_mode": "wake",
        }
    ]
    # The Co-Founder is told how to answer for the card (its SOUL.md), not per turn.
    soul = (home / "SOUL.md").read_text()
    assert "kanban_unblock" in soul and "waiting for the owner" in soul

    # Answered right under the Co-Founder's chat: the card's question is there (the UI
    # reads Hermes's board).
    from agos_core.actions import agent_profiles

    folder = agent_profiles.board_home(core, a)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, assignee TEXT, status TEXT,"
        " block_kind TEXT);"
        "CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT,"
        " payload TEXT, created_at INTEGER);"
        "INSERT INTO tasks VALUES ('t_1', 'Hook', 'a-script-writer', 'blocked',"
        " 'needs_input');"
    )
    db.execute(
        "INSERT INTO task_events (task_id, kind, payload) VALUES ('t_1', 'blocked', ?)",
        (json.dumps({"kind": "needs_input", "reason": "Which colour?"}),),
    )
    db.commit()
    db.close()
    live = client.get(f"/workspaces/{a}/chats/{cofounder}/live").json()
    assert live["questions"][0]["card"] == "t_1"


def test_an_automation_run_tells_the_owner_once(monkeypatch: Any) -> None:
    """An automation's run speaks once (owner, 2026-10-19): its cards are followed with
    Hermes's `wake` only (no passive line); a step that ends well stops being followed;
    the run's last card stays followed unless its handoff says nothing was done (WALO /
    [SILENT]); an ordinary card is followed with `wake` too. Stand-ins for Hermes's kanban_db
    here; the same flow is checked on the installed Hermes by hand (scratch probe)."""
    import sys
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    key = "agos-automation:2:R1:webhook:"
    tasks = {
        "t_a": key + "triage",
        "t_b": key + "finish",
        "t_n": "agos-automation:2:R2:webhook:triage",  # the next run, after t_b
        "t_o": None,
    }
    children = {"t_a": ["t_b"], "t_b": ["t_n"]}
    subs: dict[str, list[dict[str, Any]]] = {t: [] for t in tasks}

    def add(conn: Any, **kw: Any) -> None:
        subs[kw["task_id"]].append(kw)

    def remove(conn: Any, **kw: Any) -> bool:
        subs[kw["task_id"]] = [s for s in subs[kw["task_id"]] if s["chat_id"] != kw["chat_id"]]
        return True

    kb = types.ModuleType("hermes_cli.kanban_db")
    connect = types.ModuleType("hermes_cli.kanban_db_connect")
    notify = types.ModuleType("hermes_cli.kanban_db_notify")
    kb.get_task = lambda conn, t: types.SimpleNamespace(idempotency_key=tasks[t])  # type: ignore[attr-defined]
    kb.child_ids = lambda conn, t: children.get(t, [])  # type: ignore[attr-defined]
    connect.connect = lambda board=None: types.SimpleNamespace(close=lambda: None)  # type: ignore[attr-defined]
    notify.list_notify_subs = lambda conn, task_id: [  # type: ignore[attr-defined]
        {**s, "platform": s["platform"]} for s in subs[task_id]
    ]
    notify.add_notify_sub = add  # type: ignore[attr-defined]
    notify.remove_notify_sub = remove  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", kb)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_connect", connect)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_notify", notify)
    target = {"platform": "telegram", "chatId": "42", "chatType": "dm"}
    monkeypatch.setattr(plugin, "bridge", lambda: {"notify": target})

    for t in tasks:
        plugin.kanban_claimed(task_id=t, board=None, profile_name="default")
    shape = {
        t: [(s["delivery_mode"], s.get("delivery_metadata")) for s in v] for t, v in subs.items()
    }
    assert shape == {
        "t_a": [("wake", {"agos_run": "step"})],
        "t_b": [("wake", {"agos_run": "last"})],
        "t_n": [("wake", {"agos_run": "last"})],  # its own run: no card after it
        "t_o": [("wake", None)],
    }
    plugin.kanban_completed(task_id="t_a", board=None, summary="Work list handed on")
    plugin.kanban_completed(task_id="t_b", board=None, summary="Script ready: X - link")
    plugin.kanban_completed(task_id="t_o", board=None, summary="WALO")
    assert subs["t_a"] == [] and len(subs["t_b"]) == 1 and len(subs["t_o"]) == 1
    plugin.kanban_completed(task_id="t_b", board=None, summary="**WALO** (choose)")
    assert subs["t_b"] == []
    assert plugin._nothing_done("[SILENT] nothing new") and not plugin._nothing_done("Done")


def test_a_card_made_in_a_chat_tells_the_owner_once(monkeypatch: Any) -> None:
    """A card made in a chat: Hermes subscribes that chat with notify+wake (a plain
    "✔ Kanban t_... done" line AND the Co-Founder's turn). The plugin turns it into
    `wake` when the card starts or ends, so only the Co-Founder speaks; other
    modes (a plain `notify` someone asked for) stay as they are."""
    import sys
    import types

    from agos_core.hermes_plugin.agos_guard import bridge as plugin

    rows = {
        ("t_1", "telegram", "7", ""): "notify+wake",
        ("t_1", "telegram", "7", "3"): "notify",
        ("t_2", "agos", "9", ""): "notify+wake",
        ("t_3", "telegram", "7", ""): "notify+wake",
    }
    calls: list[dict[str, Any]] = []

    def add(conn: Any, **kw: Any) -> None:
        calls.append(kw)
        rows[(kw["task_id"], kw["platform"], kw["chat_id"], kw.get("thread_id") or "")] = kw[
            "delivery_mode"
        ]

    kb = types.ModuleType("hermes_cli.kanban_db")
    connect = types.ModuleType("hermes_cli.kanban_db_connect")
    notify = types.ModuleType("hermes_cli.kanban_db_notify")
    kb.get_task = lambda conn, t: types.SimpleNamespace(idempotency_key=None)  # type: ignore[attr-defined]
    kb.child_ids = lambda conn, t: []  # type: ignore[attr-defined]
    connect.connect = lambda board=None: types.SimpleNamespace(close=lambda: None)  # type: ignore[attr-defined]
    notify.list_notify_subs = lambda conn, task_id: [  # type: ignore[attr-defined]
        {"task_id": k[0], "platform": k[1], "chat_id": k[2], "thread_id": k[3], "delivery_mode": m}
        for k, m in rows.items()
        if k[0] == task_id
    ]
    notify.add_notify_sub = add  # type: ignore[attr-defined]
    notify.remove_notify_sub = lambda conn, **kw: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", kb)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_connect", connect)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_notify", notify)
    monkeypatch.setattr(plugin, "bridge", lambda: {"notify": {"platform": "agos", "chatId": "1"}})

    plugin.kanban_claimed(task_id="t_1", board=None, profile_name="default")
    plugin.kanban_completed(task_id="t_2", board=None, summary="Done")  # claimed before the rule
    plugin.kanban_claimed(task_id="t_3", board=None, profile_name="default")
    assert rows == {
        ("t_1", "telegram", "7", ""): "wake",
        ("t_1", "telegram", "7", "3"): "notify",
        ("t_2", "agos", "9", ""): "wake",
        ("t_3", "telegram", "7", ""): "wake",
    }
    # Already followed: the Co-Founder's conversation isn't added as a second subscriber.
    assert all(c["chat_id"] != "1" for c in calls)
    plugin.kanban_claimed(task_id="t_1", board=None, profile_name="default")
    assert len(calls) == 3  # nothing left to change


def test_the_cofounder_works_cards_too(env: Any) -> None:  # noqa: F811
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "script-writer")
    board = client.get(f"/workspaces/{a}/kanban").json()
    assert board["members"][0] == {"name": "cofounder", "title": "Co-Founder"}
    card = client.post(
        f"/workspaces/{a}/kanban", json={"title": "Plan the week", "member": "cofounder"}
    ).json()["id"]
    shown = runner.kanban[f"agos-{a}"][card]
    assert shown["assignee"] == "default" and shown["status"] == "ready"
    listed = client.get(f"/workspaces/{a}/kanban").json()["cards"][0]
    assert (listed["member"], listed["memberTitle"]) == ("cofounder", "Co-Founder")
    # Its dispatcher starts its own cards too.
    profiles = json.loads(runner.config[f"agos-{a}"]["kanban.dispatch_profiles"])
    assert profiles[0] == "default" and "a-script-writer" in profiles


def test_a_card_keeps_files_on_hermes(env: Any) -> None:  # noqa: F811
    import base64

    client, _core, _runner, _home = env
    a = ws(client, "Alpha")
    card = client.post(f"/workspaces/{a}/kanban", json={"title": "Brief"}).json()["id"]
    r = client.post(
        f"/workspaces/{a}/kanban/{card}/attachments",
        json={"name": "../brief.txt", "data": base64.b64encode(b"hello").decode()},
    )
    assert r.status_code == 204, r.text
    shown = client.get(f"/workspaces/{a}/kanban/{card}").json()
    assert [(f["name"], f["size"], f["by"]) for f in shown["attachments"]] == [
        ("_brief.txt", 5, "You")  # no path in a name
    ]
    assert shown["createdBy"] == "You"
    fid = shown["attachments"][0]["id"]
    assert client.delete(f"/workspaces/{a}/kanban/{card}/attachments/{fid}").status_code == 204
    assert client.get(f"/workspaces/{a}/kanban/{card}").json()["attachments"] == []


def test_session_search_stays_in_its_workspace() -> None:
    from agos_core.hermes_plugin.agos_guard import other_workspace

    cofounder, member = "agos-alpha", "agos-alpha--a-writer"
    assert other_workspace({"query": "logo"}, cofounder) == ""
    assert other_workspace({"profile": "agos-alpha--a-writer"}, cofounder) == ""
    assert other_workspace({"profile": "agos-beta"}, cofounder)
    assert other_workspace({"profile": "agos-beta--a-writer"}, cofounder)
    assert other_workspace({"profile": "agos-alpha-x--a-w"}, cofounder)
    assert other_workspace({"session_id": "@session:agos-beta/123"}, cofounder)
    assert other_workspace({"session_id": "agos-alpha--a-writer/5"}, cofounder) == ""
    assert other_workspace({"profile": "agos-alpha"}, member)  # not the Co-Founder's
    assert other_workspace({"profile": "agos-alpha--a-other"}, member)
    assert other_workspace({"profile": member}, member) == ""
    assert other_workspace({"profile": "default"}, cofounder)


def test_a_raw_run_record_shows_as_words() -> None:
    from agos_core.actions.kanban_board import readable_result

    assert readable_result('{"status": "completed", "output": "WALO."}') == "WALO."
    assert readable_result("Plain words") == "Plain words"
    assert readable_result("{not json") == "{not json"


def test_kanban_news_reach_a_workspace_without_a_cofounder_chat_yet(env: Any) -> None:  # noqa: F811
    """Live bug: an older workspace had no Co-Founder chat, and a card's ✅ was dropped.
    Its profile's setup makes the chat, and Hermes's notifier is pointed at it."""
    from agos_core.actions import hermes_channel, library
    from agos_core.actions.services.channel import owner_needs

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    core.db.execute("DELETE FROM chats WHERE workspace_id = ? AND kind = 'dm'", (a,))
    assert owner_needs.cofounder_chat(core, a) is None
    home = core.engine.profile_home(a)
    hermes_channel.prepare_profile(core, a, home, "http://127.0.0.1:8766")
    cofounder = owner_needs.cofounder_chat(core, a)
    assert cofounder is not None
    written = json.loads((home / hermes_channel.BRIDGE_FILE).read_text())
    assert written["notify"]["chatId"] == str(cofounder)
    assert library.apply_workspace(core, a) is None
