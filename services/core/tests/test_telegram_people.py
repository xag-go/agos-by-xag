"""Who may talk to a workspace's bot: Hermes's own allowlist and pairing."""

import hashlib
import json
import os
import secrets
import time
from typing import Any

from channels_rig import (
    OWNER,
    TOKEN,
    hermes_says_connected,
    tick,
)
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram


def hermes_pairs(core: Any, ws: str, user: int, name: str = "Owner") -> str:
    """What Hermes's gateway does when someone new writes to the bot in private
    (unauthorized_dm_behavior: pair): a pending request in its pairing store, the
    code only as a salted hash (gateway/pairing.py generate_code). Its request id."""

    folder = core.engine.profile_home(ws) / "platforms" / "pairing"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "telegram-pending.json"
    pending = json.loads(path.read_text()) if path.exists() else {}
    request_id, salt = secrets.token_hex(8), os.urandom(16)
    pending[request_id] = {
        "hash": hashlib.sha256(salt + b"ABCD2345").hexdigest(),
        "salt": salt.hex(),
        "user_id": str(user),
        "user_name": name,
        "created_at": time.time(),
    }
    path.write_text(json.dumps(pending))
    return request_id


def test_people_are_hermes_allowlist_and_pairing(env: Any) -> None:
    client, core, _fake, tg, ws = env
    # The bot's own id (start of the token) is refused as a person.
    bot_id = TOKEN.split(":")[0]
    wrong = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": [bot_id], "workspaceId": ws},
    )
    assert wrong.status_code == 400 and "bot's own id" in wrong.text
    # A workspace bot can start with nobody allowed: Hermes answers nobody yet.
    cid = client.post(
        "/channels", json={"kind": "telegram", "secret": TOKEN, "allowed": [], "workspaceId": ws}
    ).json()["id"]
    # Its @name isn't known until the workspace's Hermes connects the bot.
    assert client.post(f"/channels/{cid}/claim").status_code == 400
    hermes_says_connected(core, ws)
    # The link is the bot itself: he writes there and Hermes gives him its pairing code.
    assert client.post(f"/channels/{cid}/claim").json()["link"] == "https://t.me/agos_test_bot"
    tg.message("hello?", chat=OWNER)
    tick(core)
    request = hermes_pairs(core, ws, OWNER, "Sara")
    bot = client.get("/channels").json()[0]
    assert bot["allowed"] == [] and bot["pending"][0]["requestId"] == request
    assert bot["pending"][0]["id"] == str(OWNER) and bot["pending"][0]["name"] == "Sara"
    # The owner approves him in AGOS: Hermes's own approval; he is told in Telegram.
    assert client.post(f"/channels/{cid}/pairing/{request}").status_code == 204
    bot = client.get("/channels").json()[0]
    assert bot["allowed"] == [str(OWNER)] and bot["pending"] == []
    assert bot["people"] == [{"id": str(OWNER), "name": "Sara"}]
    assert ["pairing", "approve", "telegram", request] == core.engine.runner.calls[-1][-4:]
    tick(core)
    assert any("Connected to the AGOS workspace" in m["text"] for m in tg.sent)
    tg.message("Hi cofounder", chat=OWNER)
    tick(core)
    dm = next(
        c for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if c["agent"] is None
    )
    msgs = client.get(f"/workspaces/{ws}/chats/{dm['id']}").json()["messages"]
    assert msgs[-1]["body"] == "Hi cofounder" and all(m["body"] != "hello?" for m in msgs)
    # A request that is gone (an hour) can't be approved.
    assert client.post(f"/channels/{cid}/pairing/{request}").status_code == 400
    # He removes him: Hermes's own revoke; the bot stops listening to him.
    assert client.delete(f"/channels/{cid}/people/{OWNER}").status_code == 204
    assert client.get("/channels").json()[0]["allowed"] == []
    assert (
        core.db.execute(
            "SELECT count(*) FROM chat_addresses WHERE address = ?", (f"{OWNER}:0",)
        ).fetchone()[0]
        == 0
    )
