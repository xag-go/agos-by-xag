"""An answer's steps, read back from Hermes's own session rows: its tool calls and
their results, the words it wrote between them, and the helpers a `delegate_task`
started (shown in the chat's live view and turn history; AGOS keeps no copy).

Split out of agos_core.db.hermes_chats (its `steps_between`): the read store stays a
repository, the titles and masking here are the Chat service's (engine/chat.py
tool_title, engine/hermes_redact.py mask_many, looked up when called).

Owns: the shape of an answer's steps. Must not: read Hermes's database itself (the
rows come from db/hermes_chats.py), or keep any step.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agos_core.db.hermes_chats import Row
from agos_core.engine import hermes_redact
from agos_core.engine.chat import tool_title

__all__ = ["steps_between"]


def steps_between(rows: list[Row]) -> list[dict[str, Any]]:
    """What an answer did, from Hermes's rows alone: its tool calls and their results,
    the words it wrote between them (a "Thought": the content of a tool-calling row,
    the text Hermes relays live as `reasoning.available` / `message.interim`, H:
    agent/turn_response_intake.py:103-115,158, agent/stream_delivery.py:197-215), and
    each helper a `delegate_task` call started and how it finished (its goal from the
    call, its summary from Hermes's result, H: tools/delegate_tool_dispatch.py:209).
    Hermes's private reasoning column (messages.reasoning) is not shown."""
    results = {
        r.tool_call_id: (r.content, r.ts) for r in rows if r.role == "tool" and r.tool_call_id
    }
    steps: list[dict[str, Any]] = []
    masked: list[int] = []  # the steps whose detail goes through Hermes's masking
    for r in rows:
        calls = _calls_of(r)
        if not calls:
            continue
        thought = _REASONING_TAGS.sub("", r.content).strip()
        if thought:
            steps.append({"kind": "thinking", "title": "Thought", "detail": thought[:_THOUGHT]})
        for call in calls:
            for item in _call_steps(r, call, results):
                masked.append(len(steps))
                steps.append(item)
    if masked:
        texts = hermes_redact.mask_many([steps[i]["detail"] for i in masked])
        for i, text in zip(masked, texts, strict=True):
            steps[i]["detail"] = text
    return steps


_PREVIEW = 400


def _calls_of(r: Row) -> list[dict[str, Any]]:
    """An assistant row's tool calls (none for a plain answer or unreadable ones)."""
    if r.role != "assistant" or not r.tool_calls:
        return []
    try:
        parsed = json.loads(r.tool_calls)
    except ValueError:
        return []
    return [c for c in parsed if isinstance(c, dict)] if isinstance(parsed, list) else []


def _call_steps(
    r: Row, call: dict[str, Any], results: dict[str, tuple[str, float]]
) -> list[dict[str, Any]]:
    """One tool call's step (its arguments and result), then its helpers' (a
    `delegate_task`): all of them go through Hermes's masking."""
    fn = call.get("function") or {}
    name = str(fn.get("name") or "tool")
    args = str(fn.get("arguments") or "")
    detail = args[:_PREVIEW]
    result, done_at = results.get(str(call.get("id") or call.get("call_id") or ""), ("", None))
    if result.strip():
        detail = (detail + "\n→ " + result.strip()[:_PREVIEW]).strip()
    duration = None
    if done_at is not None:
        duration = round(max(0.0, float(done_at) - float(r.ts)), 2)
    steps = [{"kind": "tool", "title": tool_title(name), "detail": detail, "duration": duration}]
    if name == "delegate_task":
        steps += _helpers(args, result, done_at is not None)
    return steps


_THOUGHT = 4_000
# The tags Hermes takes off before it relays the words (H: agent/turn_response_intake.py:23).
_REASONING_TAGS = re.compile(r"</?(?:REASONING_SCRATCHPAD|think|reasoning)>")
# H: tools/delegate_tool_progress.py:17 SUBAGENT_FAILURE_STATUSES.
_HELPER_FAILED = frozenset({"failed", "error", "timeout"})


def _helpers(args: str, result: str, done: bool) -> list[dict[str, Any]]:
    """A `delegate_task` call's helpers: each one started (its goal, H: tools/delegate_tool.py
    goal / tasks[].goal) and, once Hermes has the result, how it finished (its
    `results[].status` and `summary`, H: tools/delegate_tool_child_run.py:1025-1027)."""
    preview = 400
    try:
        given = json.loads(args) if args.strip() else {}
    except ValueError:
        given = {}
    tasks = given.get("tasks") if isinstance(given, dict) else None
    if isinstance(tasks, list) and tasks:
        goals = [str((t or {}).get("goal") or "") if isinstance(t, dict) else "" for t in tasks]
    else:
        goals = [str(given.get("goal") or "") if isinstance(given, dict) else ""]
    try:
        told = json.loads(result) if result.strip() else {}
    except ValueError:
        told = {}
    ended = told.get("results") if isinstance(told, dict) else None
    ended = [e for e in ended if isinstance(e, dict)] if isinstance(ended, list) else []
    out: list[dict[str, Any]] = [
        {"kind": "subagent", "title": "Started a helper", "detail": goal[:preview]}
        for goal in goals
    ]
    if not done:
        return out
    for e in ended:
        failed = str(e.get("status") or "") in _HELPER_FAILED
        out.append(
            {
                "kind": "subagent",
                "title": "A helper finished",
                "detail": str(e.get("summary") or e.get("error") or "")[:preview],
                "status": "failed" if failed else "done",
            }
        )
    return out


# ---- the store in use (set when the engine starts; none in tests without one) --------
