"""What an answer did (its steps under the reply): Hermes's, with AGOS's own items in place.

An answer's steps are Hermes's own (actions/services/chat/answer_steps.py steps_between): its session's
tool calls and their results, the words it wrote between them ("Thought"), and the
helpers its `delegate_task` calls started. AGOS keeps only what Hermes has no place
for: the approvals asked (Hermes holds an approval in memory only, H:
tools/approval.py:52,119 `_pending`, `_gateway_queues`; the transcript's tool row has
the command's result alone), each with its place
among Hermes's tool steps ("at": how many of Hermes's tool steps come before it).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agos_core.engine.chat import Activity


def kept(activity: Sequence[Activity]) -> list[dict[str, Any]]:
    """What AGOS keeps of a finished answer's live view: its approvals alone, each
    with its place ("at"). The rest (tools, thoughts, notes, helpers) is Hermes's,
    read back from its session (actions/services/chat/answer_steps.py steps_between)."""
    out: list[dict[str, Any]] = []
    tools = 0
    for item in activity:
        if item.kind == "tool":
            tools += 1
        elif item.kind == "approval":
            out.append({**item.as_json(), "at": tools})
    return out


def join(
    turn_id: int, hermes: list[dict[str, Any]], kept: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The answer's steps as the owner saw them: Hermes's, with AGOS's own in place."""
    out: list[dict[str, Any]] = []
    rest = sorted(kept, key=lambda k: int(k.get("at") or 0))
    tools = 0

    def place(upto: int) -> None:
        while rest and int(rest[0].get("at") or 0) <= upto:
            out.append({k: v for k, v in rest.pop(0).items() if k != "at"})

    for step in hermes:
        if step.get("kind") == "tool":
            place(tools)
            tools += 1
        out.append({"status": "done", "choices": [], "duration": None, **step})
    place(tools)
    out += [{k: v for k, v in r.items() if k != "at"} for r in rest]
    for i, item in enumerate(out, start=1):
        item["id"] = f"{turn_id}-{i}"
        item.setdefault("status", "done")
        item.setdefault("choices", [])
        item.setdefault("detail", "")
    return out
