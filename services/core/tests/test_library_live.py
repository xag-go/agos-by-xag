"""Live: an MCP server and a skill turned on in workspace A only.

AGOS_LIVE_CONNECTORS=1 against a running core (real engine). Uses DeepWiki's
public MCP server (no key). Creates two throwaway workspaces and library items
with a random suffix; removes everything at the end.
"""

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGOS_LIVE_CONNECTORS") != "1", reason="live test (AGOS_LIVE_CONNECTORS=1)"
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


def ask(ws: str, chat: int, text: str) -> tuple[str, list[str]]:
    call("POST", f"/workspaces/{ws}/chats/{chat}/messages", {"body": text})
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(3)
        view = call("GET", f"/workspaces/{ws}/chats/{chat}")
        if not view["working"] and not view["pending"]:
            turn = view["turns"][-1]
            assert turn["status"] == "completed", turn
            tools = [a["title"] for a in turn["activity"] if a["kind"] == "tool"]
            return str(view["messages"][-1]["body"]), tools
    raise AssertionError("no answer in time")


def test_connectors_are_per_workspace() -> None:
    tag = secrets.token_hex(3)
    made: list[str] = []
    items: list[int] = []
    try:
        a = call("POST", "/workspaces", {"name": f"zz-live-{tag}-a", "defaultModel": MODEL})["id"]
        made.append(a)
        b = call("POST", "/workspaces", {"name": f"zz-live-{tag}-b", "defaultModel": MODEL})["id"]
        made.append(b)
        mcp = call(
            "POST",
            f"/workspaces/{a}/mcp",
            {
                "name": f"deepwiki-{tag}",
                "title": "DeepWiki",
                "summary": "Docs of public GitHub repos.",
                "definition": {"transport": "http", "url": "https://mcp.deepwiki.com/mcp"},
            },
        )["id"]
        items.append(mcp)
        test = call("POST", f"/library/items/{mcp}/test")
        print("mcp test:", json.dumps(test)[:300])
        assert test["ok"] and any(t["name"] == "read_wiki_structure" for t in test["tools"])
        skill = call(
            "POST",
            f"/workspaces/{a}/skills",
            {
                "name": f"codeword-{tag}",
                "definition": {
                    "text": f"---\nname: codeword-{tag}\ndescription: Use when asked for the "
                    f"workspace code word.\n---\n\nThe code word is ORCHID-{tag}.\n"
                },
            },
        )["id"]
        for item in (mcp, skill):
            call(
                "PUT",
                f"/workspaces/{a}/connectors/{item}",
                {"on": True, "allowedTools": ["read_wiki_structure"] if item == mcp else []},
            )
        connectors_b = call("GET", f"/workspaces/{b}/connectors")
        assert not any(c["on"] for c in connectors_b if c["itemId"] in items)
        chat_a = call("POST", f"/workspaces/{a}/chats", {"title": "mcp"})["id"]
        chat_b = call("POST", f"/workspaces/{b}/chats", {"title": "mcp"})["id"]
        q = (
            "Look at the tools you can call right now. Write the exact names of every tool "
            "whose name contains 'wiki' (or NONE). Then, if a skill tells you a code word, "
            "give it; otherwise write NO SKILL."
        )
        # What Hermes itself has, per profile (not the model's word).
        hermes = Path.home() / ".hermes" / "hermes-agent"
        py = hermes / "venv" / "bin" / "python"

        def hermes_mcp(ws: str) -> str:
            env = {"HOME": str(Path.home()), "PATH": "/usr/bin:/bin:/usr/local/bin"}
            done = subprocess.run(  # noqa: S603
                [str(py), str(hermes / "hermes"), "-p", f"agos-{ws}", "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                check=False,
                cwd=str(Path.home()),
            )
            return done.stdout

        mcp_a, mcp_b = hermes_mcp(a), hermes_mcp(b)
        assert f"deepwiki-{tag}" in mcp_a and f"deepwiki-{tag}" not in mcp_b
        answer_a, _ = ask(a, chat_a, q)
        answer_b, _ = ask(b, chat_b, q)
        print("A:", answer_a[:500])
        print("B:", answer_b[:500])
        assert f"ORCHID-{tag}" in answer_a  # the skill reached A's agent
        assert "ask_question" not in answer_a  # not in the allowed list
        assert "read_wiki_structure" not in answer_b and "ORCHID" not in answer_b
    finally:
        for ws in made:
            try:
                call("POST", f"/workspaces/{ws}/delete", {"confirm": ws})
                call("DELETE", f"/trash/{ws}")
            except urllib.error.HTTPError as error:
                print("cleanup", ws, error.code, error.read()[:200])
        for item in items:
            try:
                call("DELETE", f"/library/items/{item}")
            except urllib.error.HTTPError as error:
                print("cleanup item", item, error.code)
