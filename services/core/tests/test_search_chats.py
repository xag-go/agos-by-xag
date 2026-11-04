"""Step 55: the workspace search's chats come from Hermes's own full-text index of
the workspace's conversations (state.db messages_fts), never from another
workspace's."""

from __future__ import annotations

from chat_rig import MODEL, Env, env, new_chat, say, settle  # noqa: F401 - fixture


def test_search_finds_a_chat_message_through_hermes_index(env: Env) -> None:  # noqa: F811
    client, fake, core, ws = env
    chat = new_chat(client, ws, "Ads")
    say(client, ws, chat, "The summer argan campaign needs a budget")
    settle(core, lambda: bool(fake.bodies))
    found = client.get(f"/workspaces/{ws}/search", params={"q": "argan budget"}).json()
    chats = [r for r in found["results"] if r["type"] == "chat"]
    assert len(chats) == 1 and found["counts"]["chat"] == 1
    hit = chats[0]
    assert hit["title"] == "Ads" and hit["where"] == "You"
    assert hit["href"] == f"/w/{ws}/sessions?chat={chat}"
    assert sorted(hit["excerpt"][a:b].lower() for a, b in hit["marks"]) == ["argan", "budget"]
    # Every word: Hermes's prefix match alone ("argan" matches "argania") is not enough.
    assert (
        client.get(f"/workspaces/{ws}/search", params={"q": "argan winter"}).json()["counts"][
            "chat"
        ]
        == 0
    )
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert (
        client.get(f"/workspaces/{other}/search", params={"q": "argan"}).json()["counts"]["chat"]
        == 0
    )
