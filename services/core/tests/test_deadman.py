"""deploy/agos-deadman.py against a fake core /health and a fake Telegram Bot API."""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "agos-deadman.py"


class Fake:
    """One local server: /health answers as `up` says; /bot<token>/sendMessage is kept."""

    def __init__(self) -> None:
        self.up = True
        self.sent: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                code = 200 if fake.up else 503
                body = json.dumps({"ok": fake.up}).encode()
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                size = int(self.headers.get("content-length") or 0)
                form = parse_qs(self.rfile.read(size).decode())
                fake.sent.append({"path": self.path, **{k: v[0] for k, v in form.items()}})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *_: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def fake() -> Iterator[Fake]:
    server = Fake()
    yield server
    server.server.shutdown()


def _run(tmp: Path, fake: Fake, **env: str) -> str:
    done = subprocess.run(  # noqa: S603 - the script under test
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "AGOS_DATA_DIR": str(tmp),
            "AGOS_HEALTH_URL": f"{fake.url}/health",
            "AGOS_TELEGRAM_API": fake.url,
            **env,
        },
    )
    return done.stdout


def test_down_three_minutes_tells_the_owner_once_then_back(tmp_path: Path, fake: Fake) -> None:
    system = tmp_path / "system"
    root = tmp_path / "root"
    system.mkdir()
    root.mkdir()
    (root / ".env").write_text("OTHER=1\nTELEGRAM_BOT_TOKEN=123456:AAtoken\n")
    (system / "deadman.json").write_text(
        json.dumps({"envFile": str(root / ".env"), "chatId": "777", "workspace": "W"})
    )
    state = system / "deadman.state"
    assert _run(tmp_path, fake) == "" and not state.exists()  # up: nothing
    fake.up = False
    assert "core down 0 s" in _run(tmp_path, fake)
    assert fake.sent == [] and json.loads(state.read_text())["told"] is False
    # Down since 200 s ago: one message, straight to the Bot API.
    state.write_text(json.dumps({"since": time.time() - 200, "told": False}))
    assert "sent to Telegram" in _run(tmp_path, fake)
    [message] = fake.sent
    assert message["path"] == "/bot123456:AAtoken/sendMessage" and message["chat_id"] == "777"
    assert "AGOS is down" in message["text"]
    _run(tmp_path, fake)
    assert len(fake.sent) == 1  # once
    fake.up = True
    _run(tmp_path, fake)
    assert len(fake.sent) == 2 and "back up" in fake.sent[1]["text"] and not state.exists()


def test_no_bot_yet_or_core_unreachable_only_writes_the_journal(tmp_path: Path, fake: Fake) -> None:
    (tmp_path / "system").mkdir()
    state = tmp_path / "system" / "deadman.state"
    state.write_text(json.dumps({"since": time.time() - 500, "told": False}))
    out = _run(tmp_path, fake, AGOS_HEALTH_URL="http://127.0.0.1:9/health")
    assert "journal only" in out and fake.sent == []
