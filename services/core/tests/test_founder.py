"""The Founder: the owner himself as a box beside the Co-Founder, and the tasks only a
person can do, as cards on Hermes's board assigned to `founder` (actions/founder.py).

- the Co-Founder gives him one (agos_action assign_founder): a Hermes card with the
  `founder` assignee, the cards it unblocks linked to it, never in the dispatcher's
  list; he hears it in his Inbox and on Telegram (once, with Done);
- a member never can (AGOS's assign paths and the guard refuse it); the owner can
  (the Board's card modal and bulk move);
- Done (his Inbox / Today / the box / the phone / the Co-Founder told "salit") is
  Hermes's complete, and the pipeline rules see the move;
- Today's You list and the Board show his cards; the watchdog leaves them alone;
- one workspace never sees another's.
The real Hermes side (no worker, the child promoted on Done) is
tests/test_founder_live.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_automations import MODEL, env  # noqa: F401 - fixture
from test_team_hierarchy import _agent
from work_env import kanban_of

from agos_core.actions import (
    agent_profiles,
    founder,
    hermes_channel,
    kanban_board,
    pipelines,
    questions,
    watchdogs,
)
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.channel import owner_needs
from agos_core.actions.services.vision import plan_board as vision_plan_board
from agos_core.hermes_plugin import agos_guard


@pytest.fixture
def space(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, str]:  # noqa: F811
    """A workspace with one member; the Founder's cards read from the fake Hermes's
    board (the real query: test_founder_live.py)."""
    client, core, _cron, ws = env
    _agent(client, ws, "editor")

    def rows(core: Any, ws: str) -> list[dict[str, Any]]:
        cards = kanban_of(core, ws)
        return [
            {
                "id": c["id"],
                "title": c["title"],
                "body": c.get("body") or "",
                "status": c["status"],
                "createdAt": c.get("created_at") or 0,
                "completedAt": None,
                "createdBy": "",
                "result": c.get("result") or "",
                "waitsOn": list(c.get("parents") or []),
                "unblocks": [
                    x["id"] for x in cards.values() if c["id"] in (x.get("parents") or [])
                ],
            }
            for c in cards.values()
            if c.get("assignee") == founder.FOUNDER and c["status"] != "archived"
        ]

    monkeypatch.setattr(founder, "_rows", rows)
    return client, core, ws


@pytest.fixture
def pushed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What reaches his Telegram (the Co-Founder's owner path, owner_needs.push),
    deduped by source the way the outbox's unique key does."""
    sent: list[dict[str, Any]] = []

    def push(core: Any, ws: str, body: str, source: str, **kw: Any) -> int:
        if any(s["source"] == source and s["ws"] == ws for s in sent):
            return 0
        sent.append({"ws": ws, "body": body, "source": source, **kw})
        return 1

    monkeypatch.setattr(owner_needs, "push", push)
    return sent


def _asked(core: Any) -> list[list[str]]:
    return [c[1:] for c in core.engine.runner.calls if c[1:2] == ["kanban"]]


def _give(core: Any, ws: str, **fields: Any) -> dict[str, Any]:
    said = hermes_channel.run_actions(
        core, ws, "kanban:t_cofounder1", [{"do": "assign_founder", **fields}]
    )
    return dict(said["results"][0])


def test_the_cofounder_gives_him_a_task_on_hermess_board(space: Any, pushed: Any) -> None:
    client, core, ws = space
    edit = kanban_board.create(core, ws, "Edit the intro", "", "editor")
    result = _give(
        core,
        ws,
        title="Record the intro",
        what="Record a 30 s intro in the studio, phone vertical.",
        due="Friday",
        unblocks=[edit],
    )
    assert result["status"] == "done", result
    cards = kanban_of(core, ws)
    [card] = [c for c in cards.values() if c["assignee"] == founder.FOUNDER]
    # Hermes's own card: assigned to `founder`, made by the Co-Founder's profile.
    made = next(a for a in _asked(core) if a[1] == "create" and a[2] == "Record the intro")
    assert made[made.index("--assignee") + 1] == "founder"
    assert made[made.index("--created-by") + 1] == core.engine.hermes_name(ws)
    assert "By: Friday" in card["body"] and f"Unblocks: {edit}" in card["body"]
    assert founder.NOTE in card["body"]
    # The card it unblocks waits on it (Hermes's link, parent -> child).
    assert ["kanban", "link", card["id"], edit] in _asked(core)
    assert cards[edit]["parents"] == [card["id"]]
    # No worker: `founder` is never in the root's dispatcher list (Hermes skips it,
    # skipped_nonspawnable), and no profile is named so.
    assert founder.FOUNDER not in json.loads(agent_profiles.dispatch_list(core, ws))
    assert not any(a[1] == "dispatch" for a in _asked(core))
    # His phone: once, in the Co-Founder's chat, with Done.
    [phone] = [p for p in pushed if p["source"] == f"founder:{card['id']}"]
    assert "Record the intro" in phone["body"] and "Friday" in phone["body"]
    assert phone["buttons"] == [("Done", f"fdone:{card['id']}")]
    assert phone["chat_id"] == owner_needs.cofounder_chat(core, ws)
    assert founder.sweep(core, ws) == 0  # a tick later: not again
    # His Inbox, with the card and its Done.
    items = client.get(f"/workspaces/{ws}/inbox").json()["items"]
    [mine] = [i for i in items if i["type"] == "founder"]
    assert mine["card"] == card["id"] and mine["founder"]["canFinish"] is True
    assert mine["memberName"] == "Founder"
    # The Co-Founder's prompt lists his open task.
    from agos_core.actions import cofounder_actions

    text = cofounder_actions.instructions(core, ws)
    assert "THE FOUNDER" in text and f"{card['id']} — “Record the intro” (ready)" in text


def test_a_task_waiting_on_cards_reaches_him_when_its_parents_are_done(
    space: Any, pushed: Any
) -> None:
    _client, core, ws = space
    script = kanban_board.create(core, ws, "Write the script", "", "editor")
    _give(core, ws, title="Record it", parents=[script])
    cards = kanban_of(core, ws)
    [card] = [c for c in cards.values() if c["assignee"] == founder.FOUNDER]
    assert card["status"] == "todo" and pushed == []  # not his yet
    with pytest.raises(ActionError, match="still waits"):
        founder.done(core, ws, card["id"])
    card["status"] = "ready"  # Hermes promoted it (its parent finished)
    assert founder.sweep(core, ws) == 1
    assert pushed[0]["source"] == f"founder:{card['id']}"


def test_done_completes_his_card_and_the_pipeline_sees_it(
    space: Any, pushed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    del pushed
    client, core, ws = space
    card = founder.assign(core, ws, "Pay the studio", "Pay 400 MAD to the studio.")
    moved: list[str] = []
    real = pipelines.card_moved

    def seen(core: Any, ws: str, card_id: str) -> int:
        moved.append(card_id)
        return int(real(core, ws, card_id))

    monkeypatch.setattr(pipelines, "card_moved", seen)
    r = client.post(f"/workspaces/{ws}/founder/{card}/done", json={"note": "paid cash"})
    assert r.status_code == 204, r.text
    shown = kanban_of(core, ws)[card]
    assert shown["status"] == "done" and shown["result"] == "Done by the founder: paid cash"
    assert [
        "kanban",
        "complete",
        card,
        "--result=Done by the founder: paid cash",
        "--summary=Done by the founder: paid cash",
    ] in _asked(core)
    assert moved == [card]  # the pipeline rules look at the move
    # Done twice is nothing; another card is not his.
    assert founder.done(core, ws, card) is False
    other = kanban_board.create(core, ws, "Cut", "", "editor")
    assert client.post(f"/workspaces/{ws}/founder/{other}/done", json={}).status_code == 404
    # His box: the done task under Done, none open.
    box = client.get(f"/workspaces/{ws}/founder").json()
    assert box["openCount"] == 0 and [d["id"] for d in box["done"]] == [card]


def test_the_cofounder_closes_it_when_he_says_salit_and_the_phone_button(
    space: Any, pushed: Any
) -> None:
    del pushed
    _client, core, ws = space
    first = founder.assign(core, ws, "Sign the contract")
    said = hermes_channel.run_actions(
        core, ws, "kanban:t_cofounder1", [{"do": "founder_done", "card": first, "note": "salit"}]
    )
    assert said["results"][0]["status"] == "done", said
    assert kanban_of(core, ws)[first]["status"] == "done"
    assert "he told the Co-Founder" in str(kanban_of(core, ws)[first]["result"])
    second = founder.assign(core, ws, "Call the bank")
    assert founder.button(core, {ws}, second) == "Done: the cards waiting on it go on."
    assert founder.button(core, {ws}, second) == "Already done."
    assert founder.button(core, {"other-ws"}, founder.assign(core, ws, "X")) == "That task is gone."


def test_a_member_never_gives_him_a_task(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _client, core, ws = space
    # AGOS's own assign paths refuse `founder` unless the owner / Co-Founder says so.
    with pytest.raises(ActionError, match="Only the Co-Founder gives the Founder"):
        kanban_board.create(core, ws, "Record", "", founder.FOUNDER)
    card = kanban_board.create(core, ws, "Cut", "", "editor")
    with pytest.raises(ActionError, match="Only the Co-Founder"):
        kanban_board.assign(core, ws, card, founder.FOUNDER)
    # A member's suggested task naming him goes to the asker instead.
    asked = questions.ask(
        core, ws, "editor", "suggest_tasks", {"tasks": [{"title": "Film", "member": "founder"}]}
    )
    row = core.db.execute("SELECT id FROM kanban_asks WHERE card = ?", (asked["card"],)).fetchone()
    questions.answer(core, ws, int(row["id"]), {"accepted": [0]})
    film = next(c for c in kanban_of(core, ws).values() if c["title"] == "Film")
    assert film["assignee"] != founder.FOUNDER
    # The guard in a member's profile: Hermes's kanban_create and a terminal
    # `hermes kanban` naming him are refused with "ask your lead".

    class Bridge:
        agent_of_session = staticmethod(lambda session: "editor")

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: Bridge)
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "editor", "rules": {}})
    monkeypatch.setattr(agos_guard.tool_checks, "own_instructions", lambda tool, args: None)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    for tool, args in (
        ("kanban_create", {"title": "Film", "assignee": "founder"}),
        ("terminal", {"command": "hermes kanban assign t_1 founder"}),
        ("terminal", {"command": "hermes kanban create Film --assignee founder"}),
    ):
        verdict, _asks = agos_guard._verdict(tool, args, "s1")
        assert verdict is not None and verdict["action"] == "block", tool
        assert "ask your lead or the Co-Founder" in verdict["message"]
    # Reading the board, or a word that only contains it, is not refused.
    assert not agos_guard.founder_refused("terminal", {"command": "hermes kanban list"})
    assert not agos_guard.founder_refused("terminal", {"command": "kanban assign t_1 cofounders"})
    # The Co-Founder's own kanban_create to him is Hermes's, allowed.
    assert not agos_guard.founder_refused("kanban_create", {"assignee": "editor"})
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "", "rules": {}})
    verdict, _asks = agos_guard._verdict(
        "kanban_create", {"title": "Film", "assignee": "founder"}, "s1"
    )
    assert verdict is None


def test_the_owner_gives_himself_a_card_on_the_board(space: Any, pushed: Any) -> None:
    client, core, ws = space
    made = client.post(f"/workspaces/{ws}/kanban", json={"title": "Buy a mic", "member": "founder"})
    assert made.status_code == 201, made.text
    card = made.json()["id"]
    assert kanban_of(core, ws)[card]["assignee"] == "founder"
    other = client.post(f"/workspaces/{ws}/kanban", json={"title": "Cut", "member": "editor"})
    moved = client.post(
        f"/workspaces/{ws}/kanban/{other.json()['id']}/assign", json={"member": "founder"}
    )
    assert moved.status_code == 204, moved.text
    assert {p["source"] for p in pushed} == {f"founder:{card}", f"founder:{other.json()['id']}"}
    # The Board shows him as the card's member, and in the member filter.
    board = client.get(f"/workspaces/{ws}/kanban").json()
    shown = next(c for c in board["cards"] if c["id"] == card)
    assert (shown["member"], shown["memberTitle"]) == ("founder", "Founder")
    assert [m["name"] for m in board["members"]][:2] == ["cofounder", "founder"]
    # His name (Settings → General, one for every workspace; a plain setting, no
    # account) is what his cards, the filter and his notices show; the title sits
    # under it.
    assert client.get("/preferences/owner-name").json() == {"name": ""}
    r = client.put("/preferences/owner-name", json={"name": "  Sara  "})
    assert r.status_code == 200 and r.json() == {"name": "Sara"}
    r = client.put(f"/workspaces/{ws}/founder", json={"title": "  CEO  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"name": "Sara", "title": "CEO", "shown": "Sara"}
    board = client.get(f"/workspaces/{ws}/kanban").json()
    assert next(c for c in board["cards"] if c["id"] == card)["memberTitle"] == "Sara"
    assert next(m for m in board["members"] if m["name"] == "founder")["title"] == "Sara"
    box = client.get(f"/workspaces/{ws}/founder").json()
    assert (box["name"], box["title"], box["openCount"]) == ("Sara", "CEO", 2)
    items = client.get(f"/workspaces/{ws}/inbox").json()["items"]
    assert {i["memberName"] for i in items if i["type"] == "founder"} == {"Sara"}
    from agos_core.actions import cofounder_actions

    assert "the Founder is Sara (CEO)" in cofounder_actions.instructions(core, ws)
    third = founder.assign(core, ws, "Sign")
    assert next(p for p in pushed if p["source"] == f"founder:{third}")["body"].startswith(
        "🙋 **For you, Sara**: Sign"
    )
    # One name for every workspace; the title is this workspace's.
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert founder.who(core, other) == {"name": "Sara", "title": "Founder", "shown": "Sara"}
    # His card has no agent chat: it is talked about with the Co-Founder.
    with pytest.raises(ActionError, match="talk about it with the Co-Founder"):
        kanban_board.chat_of(core, ws, card)


def test_today_lists_his_tasks_and_ticks_them(
    space: Any, pushed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    del pushed
    client, core, ws = space
    card = founder.assign(core, ws, "Record the intro")
    tasks = [
        {
            "id": c["id"],
            "status": c["status"],
            "body": c.get("body") or "",
            "title": c["title"],
            "assignee": c.get("assignee") or "",
            "key": c.get("key") or "",
        }
        for c in kanban_of(core, ws).values()
    ]
    monkeypatch.setattr(vision_plan_board, "board_tasks", lambda core, ws: (tasks, []))
    you = client.get(f"/workspaces/{ws}/vision").json()["today"]["you"]
    assert [(i["id"], i["founder"], i["done"]) for i in you] == [(card, True, False)]
    assert client.post(f"/workspaces/{ws}/vision/today/{card}/done").status_code == 204
    assert kanban_of(core, ws)[card]["status"] == "done"


def test_the_watchdog_leaves_his_cards_alone(space: Any, pushed: Any) -> None:
    del pushed
    _client, core, ws = space
    card = founder.assign(core, ws, "Record the intro")
    core.db.execute(
        "INSERT INTO kanban_watchdogs (workspace_id, root_card, created_at) VALUES (?, ?, ?)",
        (ws, "t_root", "2026-11-01T00:00:00Z"),
    )
    wid = int(
        core.db.execute("SELECT id FROM kanban_watchdogs WHERE workspace_id = ?", (ws,)).fetchone()[
            0
        ]
    )
    # Only his leaf open: the tree waits on him, never an act or an escalation.
    for _ in range(4):
        assert watchdogs.observe(core, ws, wid, f"{card}:ready")["answer"] == "seen"
    # With a team leaf too, his is left out of the stop's fingerprint.
    assert watchdogs.observe(core, ws, wid, f"{card}:ready,t_other:ready")["answer"] == "act"
    row = core.db.execute(
        "SELECT fingerprint FROM kanban_watchdogs WHERE id = ?", (wid,)
    ).fetchone()
    assert row["fingerprint"] == "t_other:ready"
    assert "assigned to `founder`" in watchdogs.prompt_for(wid, "t_root")
    from agos_core.actions import heartbeat

    assert "assigned to `founder`" in heartbeat.prompt_for(None, True)


def test_one_workspace_never_sees_anothers_founder_tasks(space: Any, pushed: Any) -> None:
    client, core, ws = space
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    card = founder.assign(core, ws, "Record the intro")
    founder.save_who(core, ws, "CEO")
    assert client.get(f"/workspaces/{other}/founder").json()["open"] == []
    assert client.get(f"/workspaces/{other}/founder").json()["title"] == "Founder"
    assert client.post(f"/workspaces/{other}/founder/{card}/done", json={}).status_code == 404
    with pytest.raises(NotFoundError):
        founder.done(core, other, card)
    assert not any(
        i["type"] == "founder" for i in client.get(f"/workspaces/{other}/inbox").json()["items"]
    )
    assert all(p["ws"] == ws for p in pushed)
    assert kanban_of(core, ws)[card]["status"] == "ready"
