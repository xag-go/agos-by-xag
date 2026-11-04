"""The watchdog's one tool, `agos_watchdog_observe` (Step 48, F44): the agent of a
"Watch this tree" cron job computed the subtree's stop fingerprint (the sorted open
leaf ids with their statuses) and asks AGOS what to do. AGOS keeps the last
fingerprint per watchdog (actions/watchdogs.py observe) and answers `seen` (the
same stop as last time: nothing to do), `act` (a new stop: continue or reopen the
leaves, or ask the owner) or `escalate` (three acts with no progress: AGOS blocked
the root card for the owner; write nothing more). The fingerprint rule stays in
AGOS; the tool only carries the question."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 60

OBSERVE_SCHEMA = {
    "name": "agos_watchdog_observe",
    "description": (
        "Watchdog of a card tree: report the tree's stop fingerprint (every OPEN leaf as "
        "<id>:<status>, sorted by id, joined with commas) for the watchdog id in your "
        "prompt. AGOS answers 'seen' (same stop as last time: stop here), 'act' (a new "
        "stop: continue or reopen the leaves, or ask the owner once) or 'escalate' (AGOS "
        "blocked the root card for the owner: stop here)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "watchdog_id": {"type": "integer"},
            "fingerprint": {
                "type": "string",
                "description": "id:status,id:status of the open leaves, sorted by id.",
            },
        },
        "required": ["watchdog_id", "fingerprint"],
    },
}

NEXT = {
    "seen": "The same stop as last time: answer `Watchdog: seen.` and stop.",
    "act": (
        "A new stop: for each open leaf, unblock what you can (a dependency that is done, "
        "a ready card nobody picked up) with a comment on what to do next; a card assigned "
        "to founder is the owner's own task: leave it. What only the owner can settle, ask "
        "once with agos_ask_owner. Then answer with one line."
    ),
    "escalate": (
        "AGOS blocked the root card for the owner (needs_input): answer `Watchdog: "
        "escalated.` and stop."
    ),
}


def observe_tool(args: dict[str, Any], *, post: Callable[..., dict[str, Any] | None]) -> str:
    try:
        watchdog_id = int(args.get("watchdog_id") or 0)
    except (TypeError, ValueError):
        watchdog_id = 0
    if watchdog_id <= 0:
        return json.dumps({"error": "watchdog_id is the number in your prompt."})
    body = {"watchdog_id": watchdog_id, "fingerprint": str(args.get("fingerprint") or "")[:4000]}
    answer = post("watchdog-observe", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; do nothing this time."})
    if answer.get("error"):
        return json.dumps(answer)
    verdict = str(answer.get("answer") or "seen")
    return json.dumps({**answer, "next": NEXT.get(verdict, NEXT["seen"])})


def register(ctx: Any, *, post: Callable[..., Any], guard: Any) -> None:
    def observe(args: dict[str, Any], **_: Any) -> str:
        return observe_tool(args, post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(OBSERVE_SCHEMA["name"]),
            toolset="agos",
            schema=OBSERVE_SCHEMA,
            handler=observe,
            description=str(OBSERVE_SCHEMA["description"]),
            emoji="🐕",
        )
