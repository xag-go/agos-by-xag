"""The agents' skill tools (Step 63).

- `agos_skill_request` (every agent): `search` this workspace's skills and Hermes's
  skills hub (AGOS runs `hermes skills search` in the workspace's root: the sandbox
  has no Hermes CLI), `request` a hub skill with its tests (AGOS installs it through
  Hermes's hub and scan, tests it in Skill Studio, asks the owner when it carries
  scripts or the scan warns), `status` of your requests. The find-skills skill says
  when and how.
- `agos_skill_candidate` (the Co-Founder's weekly skill review only): a new version
  of a skill from the week's evidence, tested before it lands.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 120

REQUEST_SCHEMA = {
    "name": "agos_skill_request",
    "description": (
        "Find and ask for a skill you lack (the find-skills skill says when). action "
        "'search' (query): this workspace's skills, on and off, and Hermes's skills hub "
        "(it includes skills.sh). action 'request': source (the hub identifier as search "
        "printed it), reason (the task you need it for), tests (1-2 of {input, expected}: "
        "inputs from your real task and what a good answer says), criteria (optional "
        "checklist). AGOS installs it through Hermes's hub and security scan, tests it on "
        "your inputs and asks the owner when it carries scripts or the scan warns; it is "
        "not usable until it lands. Requests are limited per day. action 'status': your "
        "requests and where each stands."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "request", "status"]},
            "query": {"type": "string"},
            "source": {"type": "string"},
            "reason": {"type": "string"},
            "tests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"input": {"type": "string"}, "expected": {"type": "string"}},
                },
            },
            "criteria": {"type": "string"},
        },
        "required": ["action"],
    },
}

CANDIDATE_SCHEMA = {
    "name": "agos_skill_candidate",
    "description": (
        "Your weekly skill review only (the Co-Founder): propose a new version of one of "
        "this workspace's skills from the week's evidence. skill (its name), text (the "
        "whole new SKILL.md: targeted edits, same name), why (one line), evidence (the "
        "refs you used, e.g. session:..., vote:12, card:t_ab, run:7), tests (only when the "
        "skill has none yet: 1-2 of {input, expected} from the evidence). AGOS tests it on "
        "the skill's tests against the current version; it becomes the new version only "
        "when it passes all and scores at least as well. Never write the skill yourself."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill": {"type": "string"},
            "text": {"type": "string"},
            "why": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "tests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"input": {"type": "string"}, "expected": {"type": "string"}},
                },
            },
        },
        "required": ["skill", "text", "why"],
    },
}


def _tests(raw: Any) -> list[dict[str, str]]:
    out = []
    for t in raw if isinstance(raw, list) else []:
        if isinstance(t, dict):
            out.append(
                {
                    "input": str(t.get("input") or "")[:4000],
                    "expected": str(t.get("expected") or "")[:4000],
                }
            )
    return out[:2]


def request_tool(
    args: dict[str, Any],
    *,
    member: str,
    post: Callable[..., dict[str, Any] | None],
    where: dict[str, str] | None = None,
) -> str:
    """`where`: the chat, session and the owner's one-time yes (read vs act, gate.py)."""
    action = str(args.get("action") or "status")
    body = {
        "member": member,
        "action": action if action in ("search", "request", "status") else "status",
        "query": str(args.get("query") or "")[:200],
        "source": str(args.get("source") or "")[:300],
        "reason": str(args.get("reason") or "")[:1000],
        "tests": _tests(args.get("tests")),
        "criteria": str(args.get("criteria") or "")[:4000],
        **(where or {}),
    }
    answer = post("skill-request", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    return json.dumps(answer, ensure_ascii=False)


def candidate_tool(
    args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    if member:
        return json.dumps({"error": "Only the Co-Founder's weekly skill review proposes these."})
    body = {
        "action": "candidate",
        "skill": str(args.get("skill") or "")[:64],
        "text": str(args.get("text") or "")[:60_000],
        "why": str(args.get("why") or "")[:300],
        "evidence": [str(e)[:120] for e in (args.get("evidence") or []) if isinstance(e, str)][:30],
        "tests": _tests(args.get("tests")),
    }
    answer = post("skill-review", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    return json.dumps(answer, ensure_ascii=False)


def register(
    ctx: Any,
    *,
    member_of: Callable[[], str],
    post: Callable[..., Any],
    guard: Any,
    gate: Callable[[str, str, dict[str, Any]], dict[str, str]] | None = None,
) -> None:
    def request(args: dict[str, Any], session_id: str = "", **_: Any) -> str:
        where = gate(str(session_id or ""), str(REQUEST_SCHEMA["name"]), args) if gate else None
        return request_tool(args, member=member_of(), post=post, where=where)

    def candidate(args: dict[str, Any], **_: Any) -> str:
        return candidate_tool(args, member=member_of(), post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(REQUEST_SCHEMA["name"]),
            toolset="agos",
            schema=REQUEST_SCHEMA,
            handler=request,
            description=str(REQUEST_SCHEMA["description"]),
            emoji="🧩",
        )
        ctx.register_tool(
            name=str(CANDIDATE_SCHEMA["name"]),
            toolset="agos",
            schema=CANDIDATE_SCHEMA,
            handler=candidate,
            description=str(CANDIDATE_SCHEMA["description"]),
            emoji="🌱",
        )
