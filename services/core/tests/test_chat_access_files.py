"""A chat's access (Full access, Ask me) and its attachments, on a fake Hermes."""

from chat_rig import (
    MODEL,
    PNG,
    Env,
    get,
    new_chat,
    say,
    settle,
)
from chat_rig import env as env
from fake_gateway import ask_me_first, pump, switch_access

from agos_core.db import chats as chats_repo
from agos_core.engine import attachments as files


def test_full_access_allows_once_by_itself_and_ask_waits(env: Env) -> None:
    client, fake, core, ws = env
    ask_me_first(core, ws)  # tests Ask me
    chat = new_chat(client, ws)
    assert get(client, ws, chat)["access"] == "ask"
    assert switch_access(client, core, ws, chat, "full") == 204
    assert client.put(f"/workspaces/{ws}/chats/{chat}", json={"access": "yolo"}).status_code == 422
    say(client, ws, chat, "clean the build")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "approval.request", "command": "rm -rf build"})
    # Full access is Hermes's own YOLO for the conversation: nothing is asked.
    settle(core, lambda: "run_1" in getattr(fake, "yolo", []))
    assert fake.approvals == []
    fake.push("run_1", {"event": "run.completed", "output": "Done."})
    settle(core, lambda: not get(client, ws, chat)["working"])


def test_new_chats_follow_the_workspace_access(env: Env) -> None:
    """The workspace's Full access is its Hermes profiles' approvals: every chat,
    a new one too, shows it (its own switch stays Hermes's /yolo, off)."""
    client, _fake, _core, ws = env
    settings = client.get(f"/workspaces/{ws}").json()
    body = {
        "name": settings["name"],
        "description": "",
        "defaultModel": MODEL,
        "chatAccess": "full",
    }
    assert client.put(f"/workspaces/{ws}", json=body).status_code in (200, 204)
    chat = get(client, ws, new_chat(client, ws))
    assert chat["workspaceFull"] is True and chat["access"] == "ask"


def test_a_screenshot_goes_to_the_model_and_stays_in_the_workspace(env: Env) -> None:
    client, fake, core, ws = env
    chat = new_chat(client, ws)
    r = client.post(
        f"/workspaces/{ws}/chats/{chat}/messages",
        json={
            "body": "What is this?",
            "attachments": [
                {"kind": "image", "name": "../../shot.png", "mime": "image/png", "data": PNG}
            ],
        },
    )
    assert r.status_code == 201, r.text
    settle(core, lambda: bool(fake.bodies))
    # Hermes's conversation gets the words and the image itself (as from Telegram).
    body = fake.bodies[0]
    assert body["input"] == "What is this?"
    (image,) = body["media"]
    assert "/.agos/uploads/" in image["path"] and image["path"].endswith(".png")
    message = get(client, ws, chat)["messages"][0]
    shot = message["attachments"][0]
    assert shot["name"] == "shot.png" and shot["kind"] == "image"  # no path climbing
    served = client.get(f"/workspaces/{ws}/chats/{chat}/attachments/{shot['id']}")
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    folder = core.layout.workspaces / ws / "files" / ".agos" / "uploads" / f"chat-{chat}"
    [kept] = [p.name for p in folder.iterdir()]
    assert kept.endswith("-0-shot.png")
    fake.push("run_1", {"event": "run.completed", "output": "A chart."})
    settle(core, lambda: not get(client, ws, chat)["working"])
    assert client.delete(f"/workspaces/{ws}/chats/{chat}").status_code == 204
    assert folder.exists()  # the files stay in the workspace for the project
    assert client.get(f"/workspaces/{ws}/chats/{chat}/attachments/{shot['id']}").status_code == 404


def test_bad_attachments_are_refused(env: Env) -> None:
    client, _fake, _core, ws = env
    chat = new_chat(client, ws)
    url = f"/workspaces/{ws}/chats/{chat}/messages"
    svg = {"kind": "image", "name": "x.svg", "mime": "image/svg+xml", "data": PNG}
    assert client.post(url, json={"attachments": [svg]}).status_code == 400
    broken = {"kind": "file", "name": "a.txt", "mime": "text/plain", "data": "@@@"}
    assert client.post(url, json={"attachments": [broken]}).status_code == 400
    many = [
        {"kind": "file", "name": f"{i}.txt", "mime": "text/plain", "data": PNG} for i in range(9)
    ]
    assert client.post(url, json={"attachments": many}).status_code == 422
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert client.get(f"/workspaces/{other}/chats/{chat}/attachments/1").status_code == 404


def test_turn_content_shapes() -> None:
    assert files.turn_content(["hi"], []) == "hi"
    stored = [files.Stored("file", "a.csv", "text/csv", ".agos/uploads/chat-1/1-0-a.csv", None)]
    assert "/workspace/.agos/uploads/chat-1/1-0-a.csv" in str(files.turn_content(["see"], stored))
    assert files.safe_name("../../etc/passwd") == "passwd"
    assert files.safe_name("a;rm -rf.png") == "a_rm -rf.png"


def test_a_new_chat_never_inherits_a_deleted_chats_hermes_session(env: Env) -> None:
    client, fake, core, ws = env
    first = new_chat(client, ws)
    say(client, ws, first, "hello")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "run.completed", "output": "Hi."})
    settle(core, lambda: not get(client, ws, first)["working"])
    old = fake.bodies[0]["session_id"]
    assert client.delete(f"/workspaces/{ws}/chats/{first}").status_code == 204
    second = new_chat(client, ws)
    assert second != first  # the deleted chat keeps its id and data
    say(client, ws, second, "hello again")
    settle(core, lambda: len(fake.bodies) == 2)
    assert fake.bodies[1]["session_id"] != old
    assert fake.bodies[1]["address"] != fake.bodies[0]["address"]


def test_a_command_hermes_asks_reaches_the_phone(env: Env) -> None:
    """The event stream dropped (or the core restarted) while the answer waits on a
    command: the chat still shows it, and the phone gets Hermes's own Allow once /
    Deny card in the conversation's Telegram place (AGOS queues no card of its own)."""
    client, fake, core, ws = env
    ask_me_first(core, ws)  # tests Ask me
    phone = core.db.execute(
        """INSERT INTO channel_connections (kind, name, workspace_id, created_at)
             VALUES ('telegram', 'Phone', ?, 'now')""",
        (ws,),
    ).lastrowid
    linked = chats_repo.insert_chat(
        core.db,
        workspace_id=ws,
        title="Phone",
        channel="telegram",
    )
    chat = new_chat(client, ws)
    # The card goes to the conversation's own Telegram place (not another chat's).
    core.db.execute(
        """INSERT INTO chat_addresses (chat_id, connection_id, address, notify, created_at)
           VALUES (?, ?, '-100', 1, 'now')""",
        (chat, phone),
    )
    assert linked
    say(client, ws, chat, "clean the build")
    settle(core, lambda: bool(fake.bodies))
    # Hermes waits on a command (its approval hook tells AGOS).
    fake.push(
        "run_1",
        {"event": "approval.request", "command": "rm -rf build", "description": "delete the build"},
    )

    def waiting() -> bool:
        view = client.get(f"/workspaces/{ws}/chats/{chat}/live").json()["live"]
        return bool(view) and view["status"] == "waiting"

    settle(core, waiting)
    assert getattr(fake, "phone_cards", None) == [{"chat": "-100", "thread": ""}]
    assert core.db.execute("SELECT count(*) FROM channel_outbox").fetchone()[0] == 0
    # Answered in AGOS (or with Hermes's own button): Hermes is answered once.
    r = client.post(f"/workspaces/{ws}/chats/{chat}/approval", json={"choice": "once"})
    assert r.status_code == 204
    pump(core, fake)
    assert fake.approvals == [("run_1", "once")]


def test_full_access_allows_a_command_by_itself(env: Env) -> None:
    client, fake, core, ws = env
    ask_me_first(core, ws)
    chat = new_chat(client, ws)
    assert switch_access(client, core, ws, chat, "full") == 204
    say(client, ws, chat, "clean the build")
    settle(core, lambda: bool(fake.bodies))
    fake.push("run_1", {"event": "approval.request", "command": "ls"})
    settle(core, lambda: "run_1" in getattr(fake, "yolo", []))
