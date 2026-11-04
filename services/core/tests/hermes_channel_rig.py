"""The Hermes-gateway Telegram tests' helpers: connect a workspace bot run by Hermes,
call the bridge as the agos-guard plugin does, and a member's routed topic.

Shared by tests/test_hermes_channel*.py and the other Telegram-on-Hermes tests
(they import it directly). The fake Telegram and `env` are
tests/channels_rig.py.
"""

import time
from typing import Any

import hermes_store
from channels_rig import OWNER, RIG, TOKEN, hermes_lets_in

from agos_core.actions import agent_profiles, hermes_channel


def _hermes_bot(client: Any, core: Any, ws: str) -> tuple[int, str]:
    cid = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": [str(OWNER)], "workspaceId": ws},
    ).json()["id"]
    return cid, hermes_channel.bridge_key(core, ws)


def _bridge(client: Any, ws: str, key: str, path: str, body: dict[str, Any]) -> Any:
    if path in ("incoming", "command", "member-command") and "authorized" not in body:
        # The plugin asks Hermes's own allowlist first and says what it answered.
        body = body | {"authorized": hermes_lets_in(RIG["core"], ws, str(body.get("sender")))}
    answer = client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )
    hermes_store.bridge_keeps(RIG["core"], ws, path, body, answer)
    return answer


def _hermes_takes(core: Any, ws: str, member: str) -> None:
    """The member's gateway takes what waits for it, and confirms it has it."""
    for item in hermes_channel.take_inbox(core, ws, agos=True, member=member):
        hermes_channel.inbox_done(core, ws, item["id"], True)


def _handed(core: Any, address: str, count: int) -> None:
    """Waits (a few seconds at most) until AGOS has handed `count` items to Hermes
    for `address` on its own: nobody starts the answer by hand."""

    for _ in range(100):
        got = core.db.execute(
            "SELECT count(*) FROM hermes_inbox WHERE chat_ref = ? AND kind != 'command'",
            (address,),
        ).fetchone()[0]
        if got >= count:
            return
        time.sleep(0.1)
    raise AssertionError(f"nothing handed to Hermes for {address}")


def _member_topic(client: Any, core: Any, ws: str, key: str, monkeypatch: Any) -> tuple[int, str]:
    """A member's DM (script-writer, its own profile) linked to its own topic of the
    team group; the routes follow at once (no thread in a test)."""
    from agos_core.actions import member_topics

    monkeypatch.setattr(agent_profiles, "ready", lambda _c, _w, a: a == "script-writer")
    monkeypatch.setattr(member_topics, "follow", lambda c, w: member_topics.sync(c, w))
    me = {"sender": str(OWNER)}
    _bridge(client, ws, key, "incoming", me | {"chat": "-1000009", "text": "hi", "chatName": "T"})
    client.put(f"/workspaces/{ws}/telegram-group", json={"group": "-1000009"})
    dm = client.post(f"/workspaces/{ws}/chats", json={"title": "Script Writer"}).json()["id"]
    core.db.execute("UPDATE chats SET kind = 'dm', agent = 'script-writer' WHERE id = ?", (dm,))
    assert client.post(f"/workspaces/{ws}/chats/{dm}/telegram-topic").status_code == 201
    topic = str(
        core.db.execute("SELECT address FROM chat_addresses WHERE chat_id = ?", (dm,)).fetchone()[0]
    )
    return dm, topic
