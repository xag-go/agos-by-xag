"""A workspace's own Telegram bot, made from a QR code (Hermes's own setup client),
against a fake setup server and a fake Telegram Bot API."""

import json
import shutil
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from channels_rig import (
    OWNER,
    TOKEN,
    tick,
)
from channels_rig import env as env
from channels_rig import fake_telegram as fake_telegram

from agos_core.config import EngineConfig

# ---- a workspace's own bot, made from a QR code ----------------------------------


class FakeSetup:
    def __init__(self) -> None:
        self.ready = False
        self.bad_token = False
        self.refuse = False

    def handle(self, method: str, path: str, auth: str) -> tuple[int, dict[str, Any]]:
        if method == "POST" and path == "/v1/telegram/pairings":
            if self.refuse:
                return 503, {"error": "busy"}
            return 201, {
                "pairing_id": "p1",
                "poll_token": "poll-secret",
                "deep_link": "https://t.me/SetupBot?start=pair_p1",
                "suggested_username": "agos_bot",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        if method == "GET" and path == "/v1/telegram/pairings/p1":
            if auth != "Bearer poll-secret":
                return 401, {"error": "unauthorized"}
            if not self.ready:
                return 200, {"status": "waiting"}
            return 200, {
                "status": "ready",
                "token": "nope" if self.bad_token else TOKEN,
                "bot_username": "agos_test_bot",
                "owner_user_id": OWNER,
            }
        return 404, {"error": "not found"}


# Hermes's own client (hermes_cli/telegram_managed_bot.py) makes every call; in these
# tests a stand-in with its two functions runs in its place (the real one is used by
# test_qr_setup_through_hermes_own_client when Hermes is installed).
STAND_IN = """
import os
from dataclasses import dataclass
import httpx

@dataclass(frozen=True)
class TelegramPairing:
    pairing_id: str
    poll_token: str
    suggested_username: str
    deep_link: str
    qr_payload: str
    expires_at: str | None = None

@dataclass(frozen=True)
class TelegramBotSetupResult:
    token: str
    bot_username: str | None = None
    owner_user_id: int | None = None

URL = os.environ["TELEGRAM_ONBOARDING_URL"]

def create_pairing(api_url=None, bot_name="Hermes Agent", timeout=10.0):
    r = httpx.post(URL + "/v1/telegram/pairings", json={"bot_name": bot_name})
    if r.status_code not in (200, 201):
        return None
    d = r.json()
    return TelegramPairing(d["pairing_id"], d["poll_token"], d["suggested_username"],
                           d["deep_link"], d["deep_link"], d.get("expires_at"))

def poll_pairing_result_once(api_url, pairing, timeout=10.0):
    r = httpx.get(URL + "/v1/telegram/pairings/" + pairing.pairing_id,
                  headers={"Authorization": "Bearer " + pairing.poll_token})
    d = r.json()
    if r.status_code != 200 or d.get("status") != "ready" or ":" not in d.get("token", ""):
        return None
    return TelegramBotSetupResult(d["token"], d.get("bot_username"), int(d["owner_user_id"]))
"""


def _serve(fake: FakeSetup) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _answer(self, method: str) -> None:
            code, body = fake.handle(method, self.path, self.headers.get("authorization") or "")
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length") or 0))
            self._answer("POST")

        def do_GET(self) -> None:
            self._answer("GET")

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def fake_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSetup]:

    from agos_core.engine import telegram_setup

    fake = FakeSetup()
    server = _serve(fake)
    # Hermes's own variable for its setup service's address.
    monkeypatch.setenv("TELEGRAM_ONBOARDING_URL", f"http://127.0.0.1:{server.server_address[1]}")
    pkg = tmp_path / "stand-in" / "hermes_cli"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "telegram_managed_bot.py").write_text(STAND_IN)
    python = tmp_path / "stand-in" / "python"
    python.write_text(f'#!/bin/sh\nPYTHONPATH="{pkg.parent}" exec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    monkeypatch.setattr(telegram_setup, "hermes_python", lambda engine: str(python))
    yield fake
    server.shutdown()


def test_workspace_bot_from_a_qr_code_is_the_cofounder_chat(
    env: Any, fake_setup: FakeSetup
) -> None:
    client, core, _fake, tg, ws = env
    r = client.post("/channels/telegram/setup", json={"name": "Argan bot", "workspaceId": ws})
    assert r.status_code == 201, r.text
    setup = r.json()
    assert setup["status"] == "waiting" and setup["link"].startswith("https://t.me/")
    assert "poll-secret" not in r.text and setup["id"] != "p1"  # the service's ids stay inside
    url = f"/channels/telegram/setup/{setup['id']}"
    assert client.get(url).json()["status"] == "waiting"
    fake_setup.ready = True  # the owner tapped "Create bot" in Telegram
    done = client.get(url)
    assert done.json()["status"] == "saved" and TOKEN not in done.text
    (conn,) = client.get(f"/workspaces/{ws}/bots").json()
    assert conn["identity"] == "@agos_test_bot" and conn["allowed"] == [str(OWNER)]
    assert conn["workspaceId"] == ws and conn["secret"] == "••••" + TOKEN[-4:]
    # Already linked: his private chat with the bot is the Co-Founder chat, with notifications.
    dm = next(
        c for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if c["agent"] is None
    )
    (addr,) = client.get(f"/workspaces/{ws}/chats/{dm['id']}/addresses").json()
    assert addr["address"] == f"{OWNER}:0" and addr["notify"] is True
    assert client.get(url).json()["status"] == "saved"  # polling again changes nothing
    tg.message("Hi cofounder", chat=OWNER)
    tick(core)
    msgs = client.get(f"/workspaces/{ws}/chats/{dm['id']}").json()["messages"]
    assert msgs[-1]["body"] == "Hi cofounder"
    # A stranger writing to the bot is ignored.
    tg.message("hello", sender=777, chat=777)
    tick(core)
    assert (
        client.get(f"/workspaces/{ws}/chats/{dm['id']}").json()["messages"][-1]["body"]
        == "Hi cofounder"
    )


def test_workspace_bot_links_its_private_chat_on_the_first_message(env: Any) -> None:
    client, core, _fake, tg, ws = env
    r = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": [str(OWNER)], "workspaceId": ws},
    )
    assert r.status_code == 201, r.text
    tg.message("first", chat=OWNER)
    tick(core)
    dm = next(
        c for c in client.get(f"/workspaces/{ws}/workers").json()["dms"] if c["agent"] is None
    )
    assert (
        client.get(f"/workspaces/{ws}/chats/{dm['id']}").json()["messages"][-1]["body"] == "first"
    )
    # A group message to that bot is not linked by itself.
    tg.message("in a group", chat=-100)
    tick(core)
    assert (
        client.get(f"/workspaces/{ws}/chats/{dm['id']}").json()["messages"][-1]["body"] == "first"
    )
    # An unknown workspace can't own a bot.
    bad = client.post(
        "/channels",
        json={"kind": "telegram", "secret": TOKEN, "allowed": ["1"], "workspaceId": "ghost"},
    )
    assert bad.status_code == 404


def test_bad_or_expired_qr_setup(env: Any, fake_setup: FakeSetup) -> None:
    from agos_core.engine import telegram_setup

    client, _core, _fake, _tg, ws = env
    assert client.post("/channels/telegram/setup", json={"workspaceId": "ghost"}).status_code == 404
    assert client.get("/channels/telegram/setup/unknown").status_code == 404
    setup = client.post("/channels/telegram/setup", json={"workspaceId": ws}).json()
    url = f"/channels/telegram/setup/{setup['id']}"
    # A broken answer is "not ready yet" for Hermes's client: nothing is saved…
    fake_setup.ready, fake_setup.bad_token = True, True
    assert client.get(url).json()["status"] == "waiting"
    assert client.get(f"/workspaces/{ws}/bots").json() == []
    # … until the QR code expires.
    pairing = telegram_setup.get(setup["id"])
    assert pairing is not None
    pairing.expires_at = 0
    got = client.get(url).json()
    assert got["status"] == "expired" and client.get(f"/workspaces/{ws}/bots").json() == []
    # The service refusing a pairing is said plainly.
    fake_setup.refuse = True
    r = client.post("/channels/telegram/setup", json={"workspaceId": ws})
    assert r.status_code == 502 and "Telegram setup service" in r.text


def test_qr_setup_through_hermes_own_client(fake_setup: FakeSetup) -> None:
    """The real Hermes module, in Hermes's runtime, against the fake service."""

    from agos_core.engine import models as engine_models
    from agos_core.engine import telegram_setup

    hermes = shutil.which("hermes")
    home = Path.home()
    if hermes is None or not (home / ".hermes" / "tools").is_dir():
        pytest.skip("Hermes isn't installed here")
    # The install's own home and runtime (read only: a pairing is made, nothing saved);
    # a fresh home would first build a runtime of its own.
    engine = EngineConfig(
        hermes_bin=hermes,
        docker_bin="/bin/docker",
        hermes_home=home / ".hermes",
        profile_prefix="agos-",
        sandbox_image="img:1",
        host_home=home,
        roots_dir=home / ".agos-test-roots",  # never made: the QR setup only reads
        runtime_dir=home / ".hermes" / "tools",
    )
    try:
        engine_models.hermes_python(engine)
    except (OSError, RuntimeError):
        pytest.skip("Hermes's runtime isn't usable here")
    real = engine_models.hermes_python
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(telegram_setup, "hermes_python", real)
        pairing = telegram_setup.start(engine, "AGOS test", None)
        assert pairing.link == "https://t.me/SetupBot?start=pair_p1"
        assert telegram_setup.poll(engine, pairing).status == "waiting"
        fake_setup.ready = True
        assert telegram_setup.poll(engine, pairing).status == "ready"
        assert pairing.token == TOKEN and pairing.owner_id == str(OWNER)
        assert pairing.bot_username == "agos_test_bot"
