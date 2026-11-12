"""The Vision service's Co-Founder kinds: the rhythm (daily plan, recap, weekly
review), the Vision notes and their Organize, today's plan ticks
(actions/vision_ops.py binds them to the Co-Founder's page actions).

Each kind was a hand-written row of engine/cofounder_parity; declared here once, it
becomes the Co-Founder's kind, its read-vs-act row and its do / undo through the
registry (permission, workspace scope, audit row). Inputs keep the Co-Founder's own
loose fields (`CofounderFields`: its page action reads them as before).

Owns: these declarations and their input models. Must not: hold the steps (the
service's own page actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = [
    "ORGANIZE_VISION_NOTES",
    "SAVE_VISION_NOTES",
    "SET_RHYTHM",
    "SPECS",
    "TICK_TODAY",
    "OrganizeVisionNotes",
    "SaveVisionNotes",
    "SetRhythm",
    "TickToday",
]


class SetRhythm(CofounderFields):
    which: Any
    on: Any = None
    time: Any = None
    day: Any = None


SET_RHYTHM: OperationSpec[SetRhythm] = OperationSpec(
    name="set_rhythm",
    input_model=SetRhythm,
    audit_title="Your {which} job: {on} {time}",
    gate="owner",
    agent_tool=None,
    web_action="setRhythm",
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "which (daily = his daily plan | recap = the evening recap | weekly = the "
        "weekly review), on (true/false), time (HH:MM, the owner's timezone), day"
    ),
    undo_after_yes=True,
)


class SaveVisionNotes(CofounderFields):
    text: Any


SAVE_VISION_NOTES: OperationSpec[SaveVisionNotes] = OperationSpec(
    name="save_vision_notes",
    input_model=SaveVisionNotes,
    audit_title="Vision notes",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="saveNotes",
    cofounder_domain=WORKSPACE,
    cofounder_fields="text (the whole notes)",
    undo_after_yes=True,
)


class OrganizeVisionNotes(CofounderFields):
    pass


ORGANIZE_VISION_NOTES: OperationSpec[OrganizeVisionNotes] = OperationSpec(
    name="organize_vision_notes",
    input_model=OrganizeVisionNotes,
    audit_title="Organize the Vision notes",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="organizeNotes",
    cofounder_domain=WORKSPACE,
    cofounder_fields="(no fields)",
)


class TickToday(CofounderFields):
    card: Any


TICK_TODAY: OperationSpec[TickToday] = OperationSpec(
    name="tick_today",
    input_model=TickToday,
    audit_title="Tick today's item {card}",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="tickToday",
    cofounder_domain=WORKSPACE,
    cofounder_fields="card",
)

SPECS: tuple[OperationSpec[Any], ...] = (
    SET_RHYTHM,
    SAVE_VISION_NOTES,
    ORGANIZE_VISION_NOTES,
    TICK_TODAY,
)
