"""The Founder's kinds: a task only the owner can do goes on the board for him, and his
"done" closes it (actions/founder.py).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import CHAT
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class AssignFounder(CofounderFields):
    title: Any


ASSIGN_FOUNDER: OperationSpec[AssignFounder] = OperationSpec(
    name="assign_founder",
    input_model=AssignFounder,
    audit_title="For you (Founder): “{title}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    cofounder_domain=CHAT,
)


class FounderDone(CofounderFields):
    card: Any


FOUNDER_DONE: OperationSpec[FounderDone] = OperationSpec(
    name="founder_done",
    input_model=FounderDone,
    audit_title="Your task {card} done",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="finishFounderTask",
    cofounder_domain=CHAT,
)


SPECS: tuple[OperationSpec[Any], ...] = (
    ASSIGN_FOUNDER,
    FOUNDER_DONE,
)
