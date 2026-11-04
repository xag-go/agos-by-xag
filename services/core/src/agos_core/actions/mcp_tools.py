"""This workspace's tools over MCP, for outside assistants (Step 59, F71).

The owner's Claude Desktop, Claude Code or Codex delegates into ONE workspace:
list / show / create / comment / complete its cards, read its goals' status, list
and answer its Inbox, search it. Hermes's own `hermes mcp serve` speaks stdio and
serves conversations and approvals only (mcp_serve.py: no plugin tools, no token),
so AGOS serves these itself: MCP's Streamable HTTP transport (JSON-RPC 2.0 over one
POST, plain JSON answers), reached at AGOS's own address /api/mcp/<workspace>
(Tailscale only, like AGOS), with the workspace's own token (Settings →
Connections). The token is sealed in app_settings `mcp_token:<ws>`; a token opens
its own workspace and nothing else. Every tool goes through the same actions the
web uses (Hermes's Kanban CLI, the goals, the Inbox).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import delete_setting, get_setting, set_setting
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.domain.secrets import same_secret
from agos_core.security.secrets import decrypt_secret, encrypt_secret

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_VERSION = "59"


def _setting(workspace_id: str) -> str:
    return f"mcp_token:{workspace_id}"


def _context(workspace_id: str) -> str:
    return f"agos-mcp-token:{workspace_id}"


def token(core: Core, workspace_id: str) -> dict[str, Any]:
    """The workspace's token (shown to the owner, to copy into his assistant)."""
    saved = get_setting(core.db, _setting(workspace_id), None)
    if not isinstance(saved, dict) or not saved.get("sealed"):
        return {"token": None, "madeAt": None}
    value = decrypt_secret(core.master_key, str(saved["sealed"]), _context(workspace_id))
    return {"token": value, "madeAt": saved.get("made_at")}


def new_token(core: Core, workspace_id: str) -> dict[str, Any]:
    """A new token (the old one stops working)."""
    value = "agos_mcp_" + secrets.token_urlsafe(32)
    sealed = encrypt_secret(core.master_key, value, _context(workspace_id))
    with transaction(core.db):
        set_setting(core.db, _setting(workspace_id), {"sealed": sealed, "made_at": now()})
    return token(core, workspace_id)


def remove_token(core: Core, workspace_id: str) -> None:
    with transaction(core.db):
        delete_setting(core.db, _setting(workspace_id))


def allowed(core: Core, workspace_id: str, given: str) -> bool:
    held = token(core, workspace_id)["token"]
    return bool(held) and same_secret(given, str(held))


# ---- the tools -------------------------------------------------------------------


def _str(args: dict[str, Any], name: str, cap: int = 4000, *, required: bool = True) -> str:
    value = str(args.get(name) or "").strip()[:cap]
    if required and not value:
        raise ActionError(f"Give `{name}`.")
    return value


def _cards_list(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import kanban_board

    status = str(args.get("status") or "")
    member = str(args.get("member") or "")
    return [
        {"id": c["id"], "title": c["title"], "status": c["status"], "member": c["member"] or ""}
        for c in kanban_board.board(core, ws)["cards"]
        if (not status or c["status"] == status) and (not member or c["member"] == member)
    ][:200]


def _card_show(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import kanban_board

    card = kanban_board.card(core, ws, _str(args, "card", 64))
    return {
        k: card.get(k)
        for k in ("id", "title", "body", "status", "member", "summary", "comments", "children")
    }


def _card_create(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import kanban_board

    made = kanban_board.create(
        core,
        ws,
        _str(args, "title", 200),
        _str(args, "body", 20_000, required=False),
        str(args.get("member") or kanban_board.COFOUNDER),
    )
    return {"id": made}


def _card_comment(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import kanban_board

    kanban_board.comment(core, ws, _str(args, "card", 64), _str(args, "text"))
    return {"ok": True}


def _card_complete(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import kanban_board

    kanban_board.act(core, ws, _str(args, "card", 64), "done", _str(args, "summary"))
    return {"ok": True}


def _goals_status(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import goals

    del args
    return goals.status_text(core, ws) or "No Vision or goals yet."


def _inbox_list(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import inbox

    del args
    return [
        {
            "key": i["key"],
            "type": i["type"],
            "title": i["title"],
            "card": i["card"],
            "from": i["memberName"],
            "at": i["createdAt"],
        }
        for i in inbox.items(core, ws)
    ][:100]


def _inbox_answer(core: Core, ws: str, args: dict[str, Any]) -> Any:
    """A proposal (approve / revise / reject, with a note) or a question (answer)."""
    from agos_core.actions import inbox, proposals, questions

    key = _str(args, "key", 80)
    item = next((i for i in inbox.items(core, ws) if i["key"] == key), None)
    if item is None:
        raise ActionError("That Inbox item isn't waiting any more.")
    ask_id = int(key.split(":", 1)[1]) if key.startswith("ask:") else 0
    if item["type"] == "proposal":
        choice = _str(args, "choice", 20)
        proposals.decide(core, ws, ask_id, choice, _str(args, "note", required=False))
        return {"ok": True, "decided": choice}
    if item["type"] == "question":
        questions.answer(core, ws, ask_id, args.get("answer"))
        return {"ok": True}
    raise ActionError("Only proposals and questions are answered here; open AGOS for the rest.")


def _search(core: Core, ws: str, args: dict[str, Any]) -> Any:
    from agos_core.actions import search

    return search.for_agent(core, ws, _str(args, "query", 200), None)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


_S = {"type": "string"}
TOOLS: dict[str, tuple[str, dict[str, Any], Callable[[Core, str, dict[str, Any]], Any]]] = {
    "cards_list": (
        "The workspace's Kanban cards (id, title, status, member); filter by status or member.",
        _schema({"status": _S, "member": _S}, []),
        _cards_list,
    ),
    "card_show": (
        "One card: its text, status, member, result and comments.",
        _schema({"card": _S}, ["card"]),
        _card_show,
    ),
    "card_create": (
        "A new card. member: a team member's name (default: the Co-Founder), who starts it.",
        _schema({"title": _S, "body": _S, "member": _S}, ["title"]),
        _card_create,
    ),
    "card_comment": (
        "A comment on a card (its worker reads it).",
        _schema({"card": _S, "text": _S}, ["card", "text"]),
        _card_comment,
    ),
    "card_complete": (
        "Mark a card done, with what was done.",
        _schema({"card": _S, "summary": _S}, ["card", "summary"]),
        _card_complete,
    ),
    "goals_status": (
        "The Vision, its goals and projects with their progress and key results.",
        _schema({}, []),
        _goals_status,
    ),
    "inbox_list": (
        "What waits for the owner (proposals, questions, reviews, blocked cards).",
        _schema({}, []),
        _inbox_list,
    ),
    "inbox_answer": (
        "Answer an Inbox item by its key: a proposal with choice approve / revise / reject "
        "(and a note), a question with its answer.",
        _schema(
            {
                "key": _S,
                "choice": {"type": "string", "enum": ["approve", "revise", "reject"]},
                "note": _S,
                "answer": {},
            },
            ["key"],
        ),
        _inbox_answer,
    ),
    "search": (
        "Search the workspace: cards, comments, documents, agents, goals, skills, chats.",
        _schema({"query": _S}, ["query"]),
        _search,
    ),
}


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _result(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _call(core: Core, workspace_id: str, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name") or "")
    args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    found = TOOLS.get(name)
    if found is None:
        return {"content": [{"type": "text", "text": f"Unknown tool {name}."}], "isError": True}
    try:
        value = found[2](core, workspace_id, args or {})
    except ActionError as error:
        return {"content": [{"type": "text", "text": error.message}], "isError": True}
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle(core: Core, workspace_id: str, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message: its answer, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request")
    rid, method = message.get("id"), str(message.get("method") or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if rid is None:
        return None  # notifications/initialized and friends: nothing to answer
    if method == "initialize":
        asked = str((params or {}).get("protocolVersion") or "")
        return _result(
            rid,
            {
                "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"agos-{workspace_id}", "version": SERVER_VERSION},
                "instructions": "AGOS workspace tools: this workspace's Kanban, goals, Inbox "
                "and search. Cards you create are worked by the team.",
            },
        )
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(
            rid,
            {
                "tools": [
                    {"name": n, "description": d, "inputSchema": s}
                    for n, (d, s, _) in TOOLS.items()
                ]
            },
        )
    if method == "tools/call":
        return _result(rid, _call(core, workspace_id, params or {}))
    return _error(rid, -32601, f"Method not found: {method}")
