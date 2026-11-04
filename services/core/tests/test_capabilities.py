"""The Co-Founder asks for a capability from a chat; nothing changes until the owner approves."""

from typing import Any

import pytest
from test_apps import DOCS, NOTION, connect, fake_spawn, servers
from test_apps import fake_catalog as fake_catalog
from test_library import env, skill, turn_off, ws  # noqa: F401 - fixture

from agos_core.actions import capabilities
from agos_core.db import chats as chats_repo
from agos_core.engine import capabilities as rules


def _cofounder_turn(client: Any, core: Any, w: str) -> tuple[int, int]:
    from agos_core.actions.workers import open_dm

    dm = {"id": open_dm(core, w, None)}
    turn = chats_repo.insert_turn(
        core.db,
        chat_id=dm["id"],
        workspace_id=w,
        asked_up_to=0,
        speaker=None,
    )
    core.db.execute("UPDATE chat_turns SET status = 'completed' WHERE id = ?", (turn,))
    return int(dm["id"]), int(turn)


def _requests(client: Any, w: str, chat: int) -> list[dict[str, Any]]:
    turns = client.get(f"/workspaces/{w}/chats/{chat}").json()["turns"]
    return [r for t in turns for r in t["requests"]]


def test_cofounder_lists_what_exists_and_asks(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, runner, _ = env
    w = ws(client, "Alpha")
    text = capabilities.instructions(core, w)
    assert "app `notion`" in text and "not connected yet" in text
    assert "app `asana`" in text and "locked" in text
    chat, turn = _cofounder_turn(client, core, w)
    saved = capabilities.save(
        core,
        w,
        chat,
        turn,
        [
            rules.Ask("app", "deepwiki", True, "docs"),
            rules.Ask("app", "asana", True, ""),  # locked: dropped
            rules.Ask("app", "nothere", True, ""),  # unknown: dropped
            rules.Ask("app", "deepwiki", False, ""),  # already off: dropped
        ],
    )
    assert len(saved) == 1
    # Nothing is on until the owner decides.
    assert "app-deepwiki" not in servers(runner, w)
    [req] = _requests(client, w, chat)
    assert req["status"] == "proposed" and req["title"] == "Deepwiki" and req["turnOn"]
    # The same ask again isn't stored twice.
    assert capabilities.save(core, w, chat, turn, [rules.Ask("app", "deepwiki", True, "")]) == []

    r = client.post(f"/workspaces/{w}/capability-requests/{req['id']}", json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["request"]["status"] == "done" and r.json()["loginUrl"] is None
    assert servers(runner, w)["app-deepwiki"]["url"] == DOCS.url
    # The Co-Founder is told in the chat, and carries on.
    msgs = client.get(f"/workspaces/{w}/chats/{chat}").json()["messages"]
    assert "Deepwiki (app) is now on" in msgs[-1]["body"]
    # Deciding twice changes nothing.
    again = client.post(f"/workspaces/{w}/capability-requests/{req['id']}", json={"approve": False})
    assert again.json()["request"]["status"] == "done"


def test_refused_and_other_workspaces(env: Any) -> None:  # noqa: F811
    client, core, runner, _ = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    chat, turn = _cofounder_turn(client, core, a)
    capabilities.save(core, a, chat, turn, [rules.Ask("app", "deepwiki", True, "")])
    [req] = _requests(client, a, chat)
    # Another workspace can't answer it.
    assert (
        client.post(
            f"/workspaces/{b}/capability-requests/{req['id']}", json={"approve": True}
        ).status_code
        == 404
    )
    r = client.post(f"/workspaces/{a}/capability-requests/{req['id']}", json={"approve": False})
    assert r.json()["request"]["status"] == "rejected"
    assert "app-deepwiki" not in servers(runner, a)


def test_library_items_too(env: Any) -> None:  # noqa: F811
    client, core, _runner, _ = env
    w = ws(client, "Alpha")
    sid = skill(client, w, "seo-check", "---\nname: seo-check\ndescription: x\n---\nDo it.")
    assert turn_off(client, w, sid) == 204  # the owner had turned it off here
    chat, turn = _cofounder_turn(client, core, w)
    assert (
        len(capabilities.save(core, w, chat, turn, [rules.Ask("skill", "seo-check", True, "")]))
        == 1
    )
    [req] = _requests(client, w, chat)
    client.post(f"/workspaces/{w}/capability-requests/{req['id']}", json={"approve": True})
    on = {c["name"]: c["on"] for c in client.get(f"/workspaces/{w}/connectors").json()}
    assert on["seo-check"] is True


def test_an_app_not_connected_logs_in_first_then_turns_on(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, runner, _ = env
    fake_spawn(monkeypatch)
    w = ws(client, "Alpha")
    chat, turn = _cofounder_turn(client, core, w)
    capabilities.save(core, w, chat, turn, [rules.Ask("app", "notion", True, "the plan")])
    [req] = _requests(client, w, chat)
    r = client.post(
        f"/workspaces/{w}/capability-requests/{req['id']}",
        json={"approve": True, "redirectUri": "http://localhost:3001/connectors/callback"},
    ).json()
    assert r["request"]["status"] == "connecting"
    assert r["loginUrl"].startswith("https://mcp.notion.com/")
    assert "app-notion" not in servers(runner, w)
    # The owner logs in; the login's return turns it on and tells the Co-Founder.
    done = client.post("/apps/callback", json={"state": "STATE123abc", "code": "abc"})
    assert done.json()["status"] == "connected"
    assert servers(runner, w)["app-notion"]["url"] == NOTION.url
    assert _requests(client, w, chat)[0]["status"] == "done"
    msgs = client.get(f"/workspaces/{w}/chats/{chat}").json()["messages"]
    assert "Notion (app) is now on" in msgs[-1]["body"]


def test_already_connected_app_turns_on_at_once(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, runner, _ = env
    fake_spawn(monkeypatch)
    w = ws(client, "Alpha")
    connect(client, w)  # this workspace's own login (on at once)…
    assert client.put(f"/workspaces/{w}/apps/notion", json={"on": False}).status_code == 204
    chat, turn = _cofounder_turn(client, core, w)
    capabilities.save(core, w, chat, turn, [rules.Ask("app", "notion", True, "")])
    [req] = _requests(client, w, chat)
    r = client.post(f"/workspaces/{w}/capability-requests/{req['id']}", json={"approve": True})
    assert r.json()["request"]["status"] == "done"
    assert "app-notion" in servers(runner, w)
