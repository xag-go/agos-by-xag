"""The agents' search and status-card tools (Step 55).

- `agos_search(query, types?)`: the same search as the owner's Search page, over
  this workspace only (cards, comments, documents, files, agents, goals, skills,
  chats): one short line per match with its excerpt.
- `agos_status_card(action, card, summary)`: the Co-Founder reads a status card's
  scope (its cards, what moved since the last summary, the key results, its last
  summary) and writes the new summary, kept as a revision. Its scheduled run is a
  Hermes monitor job: it wakes only when the scope changed or the owner asked.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 60
TYPES = ["card", "comment", "document", "artifact", "agent", "goal", "skill", "chat"]

SEARCH_SCHEMA = {
    "name": "agos_search",
    "description": (
        "Search this workspace: Kanban cards, their comments and files, documents "
        "(Documentation, cards' documents, status cards), agents, goals and projects, "
        'skills and past chats. Every word must match (any case; a "quoted phrase" '
        "counts as one word). Gives one line per match with a short excerpt and its "
        "id (a card id opens with hermes kanban show). types: only these kinds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The words to find."},
            "types": {"type": "array", "items": {"type": "string", "enum": TYPES}},
        },
        "required": ["query"],
    },
}

STATUS_SCHEMA = {
    "name": "agos_status_card",
    "description": (
        "The owner's status cards: a scope (the workspace, a goal, a project, a member, "
        "or cards with some words) and its short summary, which you (the Co-Founder) "
        "write. action 'list': the cards. action 'read' (card): the scope's cards, what "
        "moved since your last summary, the key results and that summary. action 'write' "
        "(card, summary, why): save the new summary (markdown, about 200 words) as a new "
        "revision."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "read", "write"]},
            "card": {"type": "integer", "description": "The status card's number."},
            "summary": {"type": "string", "description": "The new summary (write)."},
            "why": {"type": "string", "description": "What this revision is for."},
        },
        "required": ["action"],
    },
}


def search_tool(args: dict[str, Any], *, member: str, post: Callable[..., Any]) -> str:
    types = args.get("types")
    body = {
        "member": member,
        "query": str(args.get("query") or "")[:200],
        "types": [str(t) for t in types if str(t) in TYPES][:8] if isinstance(types, list) else [],
    }
    answer = post("search", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    return str(answer.get("found") or "") if "found" in answer else json.dumps(answer)


def status_tool(args: dict[str, Any], *, member: str, post: Callable[..., Any]) -> str:
    action = str(args.get("action") or "read")
    try:
        card = int(args.get("card") or 0)
    except (TypeError, ValueError):
        card = 0
    body = {
        "member": member,
        "action": action if action in ("list", "read", "write") else "read",
        "card": max(card, 0),
        "summary": str(args.get("summary") or "")[:20_000],
        "why": str(args.get("why") or "")[:300],
    }
    answer = post("status-card", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    if "read" in answer:
        return str(answer["read"])
    return json.dumps(answer, ensure_ascii=False)


def register(
    ctx: Any, *, member_of: Callable[[], str], post: Callable[..., Any], guard: Any
) -> None:
    def search(args: dict[str, Any], **_: Any) -> str:
        return search_tool(args, member=member_of(), post=post)

    def status(args: dict[str, Any], **_: Any) -> str:
        return status_tool(args, member=member_of(), post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(SEARCH_SCHEMA["name"]),
            toolset="agos",
            schema=SEARCH_SCHEMA,
            handler=search,
            description=str(SEARCH_SCHEMA["description"]),
            emoji="🔎",
        )
        ctx.register_tool(
            name=str(STATUS_SCHEMA["name"]),
            toolset="agos",
            schema=STATUS_SCHEMA,
            handler=status,
            description=str(STATUS_SCHEMA["description"]),
            emoji="🗂️",
        )
