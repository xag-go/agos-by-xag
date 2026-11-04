"""Settings → Work hours: the workspace's week, who stays on today, Wake now
(actions/work_hours.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import work_hours
from agos_core.api.deps import CoreDep
from agos_core.db.records import Record

router = APIRouter(tags=["work-hours"])


class DaySpan(Record):
    from_: str = Field(alias="from")
    to: str


class AgentShift(Record):
    agent: str  # "" = the Co-Founder
    state: Literal["on", "off", "staying", "finishing"] | None = None
    until: str | None = None
    until_text: str = ""


class WorkHoursView(Record):
    on: bool
    days: dict[str, DaySpan | None]
    zone: str
    stay: list[str] = Field(default_factory=list)
    stay_until: str | None = None
    next_check_in: str | None = None
    next_check_in_text: str = ""
    check_out: str | None = None
    check_out_text: str = ""
    agents: list[AgentShift] = Field(default_factory=list)


class WorkHoursBody(Record):
    on: bool
    days: dict[str, DaySpan | None]


class StayBody(Record):
    agents: list[str] = Field(default_factory=list, max_length=50)


class WakeBody(Record):
    agent: str = Field(default="", max_length=64)


def _days(body: WorkHoursBody) -> dict[str, dict[str, str] | None]:
    return {
        day: ({"from": span.from_, "to": span.to} if span is not None else None)
        for day, span in body.days.items()
    }


@router.get("/workspaces/{workspace_id}/work-hours")
def get_work_hours(core: CoreDep, workspace_id: str) -> WorkHoursView:
    """The week, who stays on today and each agent's state now (app settings only)."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return WorkHoursView.model_validate(work_hours.view(core, workspace_id))


@router.put("/workspaces/{workspace_id}/work-hours")
def save_work_hours(core: CoreDep, workspace_id: str, body: WorkHoursBody) -> WorkHoursView:
    """His week (each day a range or OFF); on = the hours hold from now."""
    return WorkHoursView.model_validate(
        work_hours.save(core, workspace_id, {"on": body.on, "days": _days(body)})
    )


@router.put("/workspaces/{workspace_id}/work-hours/stay")
def stay_on_today(core: CoreDep, workspace_id: str, body: StayBody) -> WorkHoursView:
    """Who stays on today (until the next check-in): the whole pick."""
    return WorkHoursView.model_validate(work_hours.set_stay(core, workspace_id, body.agents))


@router.post("/workspaces/{workspace_id}/work-hours/wake")
def wake_now(core: CoreDep, workspace_id: str, body: WakeBody) -> WorkHoursView:
    """Wake now (a chat's off line): this agent is on for today."""
    return WorkHoursView.model_validate(work_hours.wake(core, workspace_id, body.agent))
