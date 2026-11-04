"""The Telegram tests' rig: a fake Telegram Bot API (a real HTTP server), the `env`
and `fake_telegram` fixtures, and the helpers that connect a bot and let a sender in.

Shared by tests/test_channels.py and every Telegram test (they import it directly).
"""

import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import hermes_store
import pytest
from chat_rig import CLIENT, FakeHermes
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import channels, hermes_channel
from agos_core.actions import chat as chat_actions
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}
TOKEN = "123456789:" + "A" * 35
OWNER = 555


class FakeTelegram:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.revoked = False
        self.next_id = 100
        self.topics = 0
        self.answered: list[str] = []
        self.reactions: list[tuple[str, int, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.edited: list[dict[str, Any]] = []
        self.menus: list[dict[str, Any]] = []
        self.asked_me = 0

    def handle(self, method: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.revoked:
            return 401, {"ok": False, "description": "Unauthorized"}
        if method == "getMe":
            self.asked_me += 1  # AGOS never asks: the bot is Hermes's to check
            return 200, {"ok": True, "result": {"username": "agos_test_bot"}}
        if method == "getUpdates":
            offset = int(params.get("offset") or 0)
            ready = [u for u in self.updates if u["update_id"] >= offset]
            return 200, {"ok": True, "result": ready}
        if method == "sendMessage":
            self.next_id += 1
            self.sent.append(params | {"message_id": self.next_id})
            return 200, {"ok": True, "result": {"message_id": self.next_id}}
        if method == "editMessageText":
            self.edited.append(params)
            return 200, {"ok": True, "result": True}
        if method == "createForumTopic":
            self.topics += 1
            return 200, {"ok": True, "result": {"message_thread_id": 40 + self.topics}}
        if method == "setMessageReaction":
            self.reactions.append(
                (str(params["chat_id"]), int(params["message_id"]), params["reaction"][0]["emoji"])
            )
            return 200, {"ok": True, "result": True}
        if method == "answerCallbackQuery":
            self.answered.append(params["text"])
            return 200, {"ok": True, "result": True}
        if method == "setMyCommands":
            self.menus.append(params)
            return 200, {"ok": True, "result": True}
        if method == "sendChatAction":
            self.actions.append((str(params["chat_id"]), params["action"]))
            return 200, {"ok": True, "result": True}
        return 404, {"ok": False, "description": "no such method"}

    def message(
        self,
        text: str,
        *,
        sender: int = OWNER,
        chat: int = -100,
        topic: int = 0,
        reply_to: int | None = None,
    ) -> None:
        msg: dict[str, Any] = {
            "message_id": 1000 + len(self.updates),
            "chat": {"id": chat},
            "from": {"id": sender, "username": "owner" if sender == OWNER else "stranger"},
            "text": text,
        }
        if topic:
            msg |= {"message_thread_id": topic, "is_topic_message": True}
        if reply_to:
            msg["reply_to_message"] = {"message_id": reply_to}
        self.updates.append({"update_id": len(self.updates) + 1, "message": msg})

    def press(self, data: str, *, chat: int = -100, topic: int = 0) -> None:
        self.updates.append(
            {
                "update_id": len(self.updates) + 1,
                "callback_query": {
                    "id": f"cb{len(self.updates)}",
                    "from": {"id": OWNER, "username": "owner"},
                    "data": data,
                    "message": {"message_id": 7, "chat": {"id": chat}, "message_thread_id": topic},
                },
            }
        )


@pytest.fixture
def fake_telegram() -> Iterator[FakeTelegram]:
    fake = FakeTelegram()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            method = self.path.rsplit("/", 1)[-1]
            length = int(self.headers.get("content-length") or 0)
            params = json.loads(self.rfile.read(length) or b"{}")
            assert self.path.startswith(f"/bot{TOKEN}/")
            code, body = fake.handle(method, params)
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from conftest import FAKE_TELEGRAM

    FAKE_TELEGRAM["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield fake
    server.shutdown()
    FAKE_TELEGRAM["url"] = None


@pytest.fixture
def env(
    tmp_path: Path, fake_telegram: FakeTelegram
) -> Iterator[tuple[TestClient, Any, FakeHermes, FakeTelegram, str]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        core.engine.runner = FakeRunner(hermes_home)
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: True
        core.engine.stop = lambda workspace_id, **_: None
        fake = FakeHermes()
        core.engine.runs_client = fake
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        CLIENT["client"] = client
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        RIG.update(client=client, tg=fake_telegram, ws=ws, done=0, core=core)
        yield client, core, fake, fake_telegram, ws
        for live in chat_actions._state(core).live.values():
            live.stop = True


RIG: dict[str, Any] = {}


def connect(client: TestClient, allowed: list[str] | None = None) -> int:
    """The workspace's Telegram bot (each workspace has its own channels)."""
    r = client.post(
        "/channels",
        json={
            "kind": "telegram",
            "name": "Phone",
            "secret": TOKEN,
            "allowed": allowed or [str(OWNER)],
            "workspaceId": RIG["ws"],
        },
    )
    assert r.status_code == 201, r.text
    if "core" in RIG:
        hermes_says_connected(RIG["core"], RIG["ws"])
    return int(r.json()["id"])


def hermes_says_connected(core: Any, ws: str, name: str = "agos_test_bot") -> None:
    """What the workspace's Hermes gateway does once its Telegram is up: its
    gateway_state.json says so, and its plugin tells AGOS the bot's @name."""
    home = core.engine.profile_home(ws)
    home.mkdir(parents=True, exist_ok=True)
    (home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "gateway_state": "running",
                "platforms": {"telegram": {"state": "connected"}},
            }
        )
    )
    hermes_channel.bot_is(core, ws, name)


def hermes_lets_in(core: Any, ws: str, sender: str) -> bool:
    """Hermes's own allowlist and DM pairing (actions/telegram_people.py): what the
    plugin asks Hermes before it hands anything to AGOS."""
    from agos_core.actions import telegram_people

    return sender in telegram_people.ids(core, ws)


def tick(core: Any) -> None:
    """What the workspace's Hermes gateway passes to AGOS (as the agos-guard plugin
    does), then AGOS's sending round."""
    client, tg, ws = RIG["client"], RIG["tg"], RIG["ws"]
    key = hermes_channel.bridge_key(core, ws)
    for update in tg.updates[RIG["done"] :]:
        RIG["done"] += 1
        q = update.get("callback_query")
        msg = (q or {}).get("message") or update.get("message") or {}
        address = f"{msg['chat']['id']}:{msg.get('message_thread_id') or 0}"
        sender = str(((q or msg).get("from") or {}).get("id"))
        authorized = hermes_lets_in(core, ws, sender)
        if q:
            if not authorized:
                continue  # Hermes's own button check turns him away
            path, body = (
                "callback",
                {"chat": address, "data": q["data"], "messageId": str(msg["message_id"])},
            )
        elif not authorized and not str(msg["text"]).startswith("/start "):
            continue  # a stranger: Hermes's to turn away, AGOS never hears of it
        else:
            reply = (msg.get("reply_to_message") or {}).get("message_id")
            path, body = (
                "incoming",
                {
                    "chat": address,
                    "sender": str(msg["from"]["id"]),
                    "text": msg["text"],
                    "messageId": str(msg["message_id"]),
                    "replyTo": str(reply) if reply else None,
                    "authorized": authorized,
                },
            )
        answer = client.post(
            f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
        )
        hermes_store.bridge_keeps(core, ws, path, body, answer)  # what Hermes keeps of it
        got = answer.json()
        if q and got.get("text"):
            tg.answered.append(got["text"])  # the plugin shows it on the tap
    channels.send_round(core)
