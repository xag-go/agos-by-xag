"""The Co-Founder's work-hours kinds: the hours that hold, who stays on today, wake an agent
now (actions/workspace_admin_ops.py binds them to the page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class SetWorkHours(CofounderFields):
    pass


SET_WORK_HOURS: OperationSpec[SetWorkHours] = OperationSpec(
    name="set_work_hours",
    input_model=SetWorkHours,
    audit_title="Work hours: {on}",
    gate="undo",
    agent_tool=None,
    web_action="saveWorkHours",
    cofounder_domain=WORKSPACE,
    cofounder_fields="on (true = the hours hold; false = always on), days (an object mon..sun, each {from: HH:MM, to: HH:MM} on the owner's timezone, to before from = ends the next morning, null = OFF that day; leave out = keep the days)",
    cofounder_structured=("days",),
)


class StayOnToday(CofounderFields):
    pass


STAY_ON_TODAY: OperationSpec[StayOnToday] = OperationSpec(
    name="stay_on_today",
    input_model=StayOnToday,
    audit_title="Who stays on today",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="setStayOnToday",
    cofounder_domain=WORKSPACE,
    cofounder_fields="agents (a list of member names, cofounder = you; [] = nobody): they keep working until the next check-in, then it clears by itself",
    cofounder_structured=("agents",),
)


class WakeNow(CofounderFields):
    agent: Any


WAKE_NOW: OperationSpec[WakeNow] = OperationSpec(
    name="wake_now",
    input_model=WakeNow,
    audit_title="Wake {agent} now (on for today)",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="wakeNow",
    cofounder_domain=WORKSPACE,
    cofounder_fields="agent (a member's name, or cofounder): on until the next check-in",
)


SPECS: tuple[OperationSpec[Any], ...] = (
    SET_WORK_HOURS,
    STAY_ON_TODAY,
    WAKE_NOW,
)
