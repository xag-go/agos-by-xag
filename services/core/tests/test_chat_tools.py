"""The Co-Founder's and the workspace's tools in a chat: Hermes tools, kept per
workspace; reading an app is not changing it; an Ask-me rule still asks."""

from chat_rig import (
    MODEL,
    Env,
    new_chat,
    say,
    settle,
)
from chat_rig import env as env

from agos_core.engine.chat import LiveTurn


def test_an_ask_me_rule_shows_its_card_even_on_full_access() -> None:

    turn = LiveTurn(turn_id=1)
    turn.apply(
        {
            "event": "approval.request",
            "command": "x",
            "description": "[AGOS rule: Ask me] Change things in connected apps: x",
        }
    )
    snap = turn.snapshot()
    assert snap["activity"][0]["status"] == "waiting"  # the app shows Allow once / Deny
    turn.apply({"event": "approval.responded", "choice": "once"})
    assert turn.snapshot()["activity"][0]["title"] == "Allowed once"


def test_reading_an_app_is_not_changing_it() -> None:
    from agos_core.hermes_plugin.agos_guard import _READ_VERBS

    for name in (
        "mcp__app_google__sheets_info",
        "mcp__app_google__drive_download",
        "mcp__app_google__sheets_read",
        "mcp__app_google__drive_search",
    ):
        assert _READ_VERBS.search(name), name
    for name in (
        "mcp__app_google__sheets_write",
        "mcp__app_google__drive_upload",
        "mcp__app_google__docs_append",
    ):
        assert not _READ_VERBS.search(name), name


def test_the_cofounders_actions_are_a_hermes_tool(env: Env) -> None:
    """agos_action: AGOS says whether Hermes asks first (his Co-Founder mode, an action
    that touches every workspace), then does each action now, with Undo on its card."""
    client, fake, core, ws = env
    from agos_core.actions import cofounder_actions, hermes_channel

    skill = {
        "do": "create_skill",
        "name": "hook-writing",
        "description": "Hooks",
        "instructions": "Write hooks.",
    }
    check = hermes_channel.tool_check(core, "agos_action", {"actions": [skill]})
    assert check["ask"] is False and "hook-writing" in check["message"].lower()
    rule = {"do": "add_owner_rule", "text": "Answer in Darija", "why": "he said so"}
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [rule]})["ask"] is True
    cofounder_actions.set_mode(core, "ask")
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [skill]})["ask"] is True
    cofounder_actions.set_mode(core, "direct")

    chat = new_chat(client, ws)
    say(client, ws, chat, "make a hook skill")
    settle(core, lambda: bool(fake.bodies))
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/actions",
        json={"chat": f"agos:{chat}", "actions": [skill, {"do": "nope"}]},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert [x["status"] for x in out["results"]] == ["done"] and "skipped" in out
    row = core.db.execute("SELECT * FROM cofounder_actions WHERE chat_id = ?", (chat,)).fetchone()
    assert row["status"] == "done" and row["turn_id"] is not None


def test_a_workspaces_tools_never_reach_another_workspace(env: Env) -> None:
    """Each workspace is on its own: its Hermes (its bridge key) can't add a card or
    act from another workspace's chats, nor report a card's tokens there."""
    client, _fake, core, ws = env
    from agos_core.actions import hermes_channel

    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    theirs = client.post(f"/workspaces/{other}/chats", json={"title": "Secret"}).json()["id"]
    mine = {"authorization": f"Bearer {hermes_channel.bridge_key(core, ws)}"}
    calls = [
        ("actions", {"chat": f"agos:{theirs}", "actions": [{"do": "add_method", "text": "t"}]}),
    ]
    for path, body in calls:
        r = client.post(f"/hermes-bridge/{ws}/{path}", json=body, headers=mine)
        assert r.status_code == 200 and "error" in r.json(), (path, r.text)
        # Their own address under their id: refused with my key.
        assert client.post(
            f"/hermes-bridge/{other}/{path}", json=body, headers=mine
        ).status_code in (
            401,
            403,
        )
    tokens = {"card": "t_1", "level": 1, "tokens": 9, "usual": 3}
    assert client.post(
        f"/hermes-bridge/{other}/card-tokens-told", json=tokens, headers=mine
    ).status_code in (
        401,
        403,
    )
    from agos_core.actions import token_watch

    assert not token_watch.knows(core, other, "t_1")
