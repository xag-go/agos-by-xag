"""The agents' plan tool, `agos_goals` (Step 51, Step 53 Vision): `status` reads the
workspace's Vision, each goal with its key results (numbers) and its projects (their
cards done / open / blocked: AGOS's one read of Hermes's board), today's plan and
the last recap; `propose` puts a plan change in the owner's Inbox (a proposal card,
kind 'goal': Approve / Revise / Reject, Accept / Change / Skip for a daily plan);
`post` is the Co-Founder's recap or weekly review (Inbox + Telegram). The plan
itself is already in the agent's SOUL.md; this tool carries the live numbers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 60

GOALS_SCHEMA = {
    "name": "agos_goals",
    "description": (
        "The workspace plan: Vision -> goals (key results: numbers) -> projects -> today. "
        "action 'status': the Vision, each goal's key results and projects with their "
        "cards done / open / blocked, today's plan and the last recap. action 'propose' "
        "(kind goal | kr | project | kr_update | daily_plan | vision): ask the owner; "
        "payload per kind - goal: goal_id (to change), title, goal_why, owner (a member), "
        "due_on (YYYY-MM-DD), status (active | paused | done | dropped); kr: kr_id (to change) or goal_id (new), title, "
        "start, current, target, unit, due_on; project: project_id (to change) or goal_id "
        "(new), title, project_why, owner, project_kind (dated | recurring), starts_on, "
        "ends_on, rhythm; kr_update: kr_id, current, source (where the number comes "
        "from); daily_plan: date, summary, you [{title, why}], members [{member, title, "
        "body, project_id}]; vision: title, vision_why, strategy (only a suggestion: the "
        "Vision is the owner's); every kind but daily_plan has why: what it does for the "
        "goal. To delete a goal, key result or project for good (a goal goes with its key "
        "results and projects; dropped only marks it): the same kind with payload "
        "{goal_id | kr_id | project_id, delete: true, why}. revises: the card of the round the owner sent back. It waits in his Inbox; "
        "his answer comes back on the proposal card. action 'post' (the Co-Founder, kind "
        "recap | weekly, words): the evening recap or the weekly review to the owner."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "propose", "post"]},
            "kind": {
                "type": "string",
                "enum": [
                    "goal",
                    "kr",
                    "project",
                    "kr_update",
                    "daily_plan",
                    "vision",
                    "recap",
                    "weekly",
                ],
            },
            "payload": {"type": "object", "additionalProperties": True},
            "words": {"type": "string", "description": "Your own words to the owner."},
            "revises": {"type": "string", "description": "The card this round replaces."},
        },
        "required": ["action"],
    },
}


def goals_tool(
    args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    action = str(args.get("action") or "status")
    body: dict[str, Any] = {
        "member": member,
        "action": action if action in ("status", "propose", "post") else "status",
        "kind": str(args.get("kind") or "")[:20],
        "payload": args.get("payload") if isinstance(args.get("payload"), dict) else {},
        "words": str(args.get("words") or "")[:20_000],
        "revises": str(args.get("revises") or "")[:64],
    }
    answer = post("goals", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    return json.dumps(answer, ensure_ascii=False)


def register(
    ctx: Any, *, member_of: Callable[[], str], post: Callable[..., Any], guard: Any
) -> None:
    def goals(args: dict[str, Any], **_: Any) -> str:
        return goals_tool(args, member=member_of(), post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(GOALS_SCHEMA["name"]),
            toolset="agos",
            schema=GOALS_SCHEMA,
            handler=goals,
            description=str(GOALS_SCHEMA["description"]),
            emoji="🎯",
        )
