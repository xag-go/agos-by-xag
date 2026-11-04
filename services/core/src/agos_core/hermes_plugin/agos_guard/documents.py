"""The agents' `agos_card_document` tool: a card's documents with the revision check.

A card's documents are files the agent already sees (/workspace/cards/<card>/
<key>.md); this tool is the way to WRITE one so that nobody's work is lost: the
write carries the revision the agent read (`base_revision`) and AGOS refuses it,
with the words that say how to go on, when the document moved since (actions/
card_docs.py STALE). `read` gives the text with its revision (and the owner's open
passage comments); `annotations` gives those comments alone, so the Co-Founder can
act on what the owner marked in a passage.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 60

SCHEMA = {
    "name": "agos_card_document",
    "description": (
        "A Kanban card's documents: markdown files at /workspace/cards/<card>/<key>.md, "
        "one revision kept per save. action 'write' (default): save `content` as a new "
        "revision — send base_revision=<the revision you read> (omit it only for a new "
        "document); if the document moved since you read it, the write is refused and the "
        "answer names the current revision: read it again and resend with that "
        "base_revision. action 'read': the text and its revision (no key: the card's "
        "document list). action 'annotations': the owner's open comments on passages of "
        "the document (quote + his words), so you can act on them. `card` defaults to the "
        "card you are working."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "card": {"type": "string", "description": "The card id (default: your card)."},
            "key": {
                "type": "string",
                "description": "The document's key (its file name without .md: letters, digits, - _).",
            },
            "action": {"type": "string", "enum": ["write", "read", "annotations"]},
            "content": {"type": "string", "description": "write: the whole new text."},
            "base_revision": {
                "type": "integer",
                "description": "write: the revision you read (from read, or the CHANGES.md).",
            },
            "why": {"type": "string", "description": "write: why it changed (one line)."},
        },
        "required": ["key"],
    },
}


def _card(args: dict[str, Any]) -> str:
    return str(args.get("card") or os.environ.get("HERMES_KANBAN_TASK", "") or "")


def document_tool(
    args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    card = _card(args)
    if not card:
        return json.dumps({"error": "Say which card (card=<id>): you are not working one now."})
    base = args.get("base_revision")
    body: dict[str, Any] = {
        "member": member,
        "card": card,
        "key": str(args.get("key") or "")[:70],
        "action": str(args.get("action") or "write"),
        "content": str(args.get("content") or ""),
        "base_revision": int(base)
        if isinstance(base, int | float) and not isinstance(base, bool)
        else None,
        "why": str(args.get("why") or "")[:300],
    }
    answer = post("card-document", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; nothing was written."})
    return json.dumps(answer, ensure_ascii=False)


def register(
    ctx: Any, *, member_of: Callable[[], str], post: Callable[..., Any], guard: Any
) -> None:
    def handler(args: dict[str, Any], **_: Any) -> str:
        return document_tool(args, member=member_of(), post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(SCHEMA["name"]),
            toolset="agos",
            schema=SCHEMA,
            handler=handler,
            description=str(SCHEMA["description"]),
            emoji="📄",
        )
