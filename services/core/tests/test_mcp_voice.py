"""Step 59: the workspace's tools over MCP (F71).

MCP: Streamable HTTP JSON-RPC behind the workspace's own sealed token; a token
opens its own workspace only (ws A's token on ws B is refused), a new token ends
the old one; tools go through the same actions as the web.
"""

from __future__ import annotations

from typing import Any

from test_automations import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import inbox, kanban_board, mcp_tools, proposals, search


def _mcp(client: Any, ws: str, token: str | None, body: Any) -> Any:
    headers = {"x-agos-mcp-token": token} if token else {}
    return client.post(f"/workspaces/{ws}/mcp-serve", json=body, headers=headers)


def _rpc(method: str, params: dict[str, Any] | None = None, rid: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


def test_mcp_serves_this_workspaces_tools_with_its_token_only(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    assert client.get(f"/workspaces/{ws}/mcp-token").json()["token"] is None
    made = client.post(f"/workspaces/{ws}/mcp-token").json()
    token = made["token"]
    assert token.startswith("agos_mcp_") and made["madeAt"] and "cards_list" in made["tools"]
    theirs = client.post(f"/workspaces/{other}/mcp-token").json()["token"]
    # Sealed at rest: the token is not in the database as written.
    raw = core.db.execute(
        "SELECT value FROM app_settings WHERE key = ?", (f"mcp_token:{ws}",)
    ).fetchone()
    assert token not in str(raw["value"])

    boards = {
        ws: [{"id": "t_1", "title": "Ours", "status": "todo", "member": ""}],
        other: [{"id": "t_9", "title": "Theirs", "status": "todo", "member": ""}],
    }
    made_cards: list[tuple[str, str, str]] = []
    monkeypatch.setattr(kanban_board, "board", lambda core, w: {"cards": boards[w]})

    def create(core: Any, w: str, title: str, body: str, member: str, **k: Any) -> str:
        made_cards.append((w, title, member))
        return "t_2"

    monkeypatch.setattr(kanban_board, "create", create)
    monkeypatch.setattr(search, "for_agent", lambda core, w, q, t: f"{w}:{q}")

    first = _mcp(client, ws, None, _rpc("ping"))
    assert first.status_code == 401, first.text
    assert _mcp(client, ws, theirs, _rpc("ping")).status_code == 401  # B's token on A
    assert _mcp(client, other, token, _rpc("ping")).status_code == 401  # A's token on B
    init = _mcp(client, ws, token, _rpc("initialize", {"protocolVersion": "2025-03-26"})).json()
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert init["result"]["serverInfo"]["name"] == f"agos-{ws}"
    note = _mcp(client, ws, token, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202
    listed = _mcp(client, ws, token, _rpc("tools/list")).json()["result"]["tools"]
    assert {t["name"] for t in listed} == set(mcp_tools.TOOLS)
    assert all(t["inputSchema"]["type"] == "object" for t in listed)

    def call(tool: str, args: dict[str, Any], who: str = ws, key: str = token) -> dict[str, Any]:
        r = _mcp(client, who, key, _rpc("tools/call", {"name": tool, "arguments": args}))
        assert r.status_code == 200, r.text
        return dict(r.json()["result"])

    cards = call("cards_list", {})
    assert '"t_1"' in cards["content"][0]["text"] and "t_9" not in cards["content"][0]["text"]
    assert call("cards_list", {}, other, theirs)["content"][0]["text"].count("t_9") == 1
    call("card_create", {"title": "From Claude", "member": "writer"})
    assert made_cards == [(ws, "From Claude", "writer")]
    assert call("search", {"query": "argan"})["content"][0]["text"] == f"{ws}:argan"
    missing = call("card_comment", {"card": "t_1"})
    assert missing["isError"] and "text" in missing["content"][0]["text"]
    assert call("nope", {})["isError"]
    batch = _mcp(client, ws, token, [_rpc("ping", rid=1), _rpc("tools/list", rid=2)]).json()
    assert [b["id"] for b in batch] == [1, 2]
    assert _mcp(client, ws, token, _rpc("bogus")).json()["error"]["code"] == -32601

    # Inbox: a proposal is decided through the same action as the web's.
    monkeypatch.setattr(
        inbox,
        "items",
        lambda core, w, **k: (
            [
                {
                    "key": "ask:5",
                    "type": "proposal",
                    "title": "Hire",
                    "card": "",
                    "memberName": "",
                    "createdAt": "",
                }
            ]
            if w == ws
            else []
        ),
    )
    decided: list[tuple[str, int, str]] = []

    def decide(
        core: Any, w: str, ask: int, choice: str, note: str = "", payload: Any = None
    ) -> Any:
        decided.append((w, ask, choice))
        return {}

    monkeypatch.setattr(proposals, "decide", decide)
    assert '"ask:5"' in call("inbox_list", {})["content"][0]["text"]
    call("inbox_answer", {"key": "ask:5", "choice": "approve"})
    assert decided == [(ws, 5, "approve")]
    assert call("inbox_answer", {"key": "ask:5", "choice": "approve"}, other, theirs)["isError"]

    # A new token ends the old one; removing it closes the door.
    fresh = client.post(f"/workspaces/{ws}/mcp-token").json()["token"]
    assert fresh != token and _mcp(client, ws, token, _rpc("ping")).status_code == 401
    assert _mcp(client, ws, fresh, _rpc("ping")).status_code == 200
    assert client.delete(f"/workspaces/{ws}/mcp-token").status_code == 204
    assert _mcp(client, ws, fresh, _rpc("ping")).status_code == 401


# ---- voice notes ---------------------------------------------------------------------------

STATE = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, chat_id TEXT, thread_id TEXT,
  title TEXT, model TEXT, started_at REAL, archived INTEGER, auto_archived INTEGER,
  end_reason TEXT);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
  role TEXT NOT NULL, content TEXT, tool_calls TEXT, tool_call_id TEXT, timestamp REAL NOT NULL,
  message_uid TEXT, platform_message_id TEXT, display_kind TEXT, active INTEGER DEFAULT 1,
  compacted INTEGER DEFAULT 0, _compressed_summary INTEGER DEFAULT 0);
"""
