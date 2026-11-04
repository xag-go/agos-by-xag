"""Live: SOUL identity and per-workspace memory with real Hermes + Docker.

Run with AGOS_LIVE_IDENTITY=1 against a running core (AGOS_CORE_URL, default
http://127.0.0.1:8766) that uses the real engine. Creates two throwaway
workspaces with a random prefix and removes them (trash + purge) at the end.
"""

import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGOS_LIVE_IDENTITY") != "1", reason="live test (AGOS_LIVE_IDENTITY=1)"
)

CORE = os.environ.get("AGOS_CORE_URL", "http://127.0.0.1:8766")
if not CORE.startswith(("http://", "https://")):
    raise ValueError("AGOS_CORE_URL must be http(s)")
DATA = Path(os.environ.get("AGOS_DATA_DIR", "agos-data"))
MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "low"}


def call(method: str, path: str, body: Any = None, timeout: float = 120) -> Any:
    token = (DATA / "system" / "internal.token").read_text().strip()
    req = urllib.request.Request(  # noqa: S310 - http(s) only, checked above
        CORE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-agos-internal": token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        raw = r.read()
        return json.loads(raw) if raw else None


def ask(ws: str, chat: int, text: str) -> str:
    call("POST", f"/workspaces/{ws}/chats/{chat}/messages", {"body": text})
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        time.sleep(3)
        view = call("GET", f"/workspaces/{ws}/chats/{chat}")
        if not view["working"] and not view["pending"]:
            turn = view["turns"][-1]
            assert turn["status"] == "completed", turn
            return str(view["messages"][-1]["body"])
    raise AssertionError("no answer in time")


def test_identity_and_memory_are_per_workspace() -> None:
    tag = secrets.token_hex(3)
    made: list[str] = []
    try:
        a = call(
            "POST",
            "/workspaces",
            {
                "name": f"zz-live-{tag}-alpha",
                "description": "Sells argan oil to hotels in Agadir.",
                "defaultModel": MODEL,
            },
        )["id"]
        made.append(a)
        b = call(
            "POST",
            "/workspaces",
            {
                "name": f"zz-live-{tag}-beta",
                "description": "Tracks bakery invoices.",
                "defaultModel": MODEL,
            },
        )["id"]
        made.append(b)
        call(
            "PUT",
            f"/workspaces/{a}/memory/memory",
            {"entries": [f"The secret code word is ZEBRA-{tag}."]},
        )
        chat_a = call("POST", f"/workspaces/{a}/chats", {"title": "who"})["id"]
        chat_b = call("POST", f"/workspaces/{b}/chats", {"title": "who"})["id"]
        q = (
            "Without using any tool: in one line, which workspace are you for and what is it "
            "about? Then, if your memory holds a code word, write it; otherwise write NONE."
        )
        answer_a = ask(a, chat_a, q)
        answer_b = ask(b, chat_b, q)
        print("A:", answer_a)
        print("B:", answer_b)
        assert "argan" in answer_a.lower()
        assert f"ZEBRA-{tag}" in answer_a
        assert "bakery" in answer_b.lower() or "invoice" in answer_b.lower()
        assert "ZEBRA" not in answer_b
    finally:
        for ws in made:
            try:
                call("POST", f"/workspaces/{ws}/delete", {"confirm": ws})
                call("DELETE", f"/trash/{ws}")
            except urllib.error.HTTPError as error:
                print("cleanup", ws, error.code, error.read()[:200])
