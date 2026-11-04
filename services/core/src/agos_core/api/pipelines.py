"""Settings → Pipelines (Step 59): the workspace's pipeline rules."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import pipelines
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["pipelines"])

Trigger = Literal["status", "review_approved", "plan_accepted"]
Action = Literal["follow_up", "comment", "assign", "run_automation", "notify"]


class PipelineRule(Record):
    id: int
    name: str
    trigger: Trigger
    status: str
    goal_id: int | None = None
    label: str
    action: Action
    member: str
    automation_id: int | None = None
    text: str
    enabled: bool
    last_fired_at: str | None = None
    last_outcome: str


class PipelineRuleBody(Body):
    name: str = Field(default="", max_length=120)
    trigger: Trigger
    status: str = Field(default="", max_length=40)
    goal_id: int | None = None
    label: str = Field(default="", max_length=41)
    action: Action
    member: str = Field(default="", max_length=64)
    automation_id: int | None = None
    text: str = Field(default="", max_length=4000)
    enabled: bool = True


def _data(body: PipelineRuleBody) -> dict[str, object]:
    return body.model_dump(by_alias=True)


@router.get("/workspaces/{workspace_id}/pipelines")
def list_rules(core: CoreDep, workspace_id: str) -> list[PipelineRule]:
    require_workspace(core, workspace_id)
    return [PipelineRule.model_validate(r) for r in pipelines.rules(core, workspace_id)]


@router.post("/workspaces/{workspace_id}/pipelines")
async def add_rule(core: CoreDep, workspace_id: str, body: PipelineRuleBody) -> PipelineRule:
    require_workspace(core, workspace_id)
    saved = await asyncio.to_thread(pipelines.save, core, workspace_id, None, _data(body))
    return PipelineRule.model_validate(saved)


@router.put("/workspaces/{workspace_id}/pipelines/{rule_id}")
async def save_rule(
    core: CoreDep, workspace_id: str, rule_id: int, body: PipelineRuleBody
) -> PipelineRule:
    require_workspace(core, workspace_id)
    saved = await asyncio.to_thread(pipelines.save, core, workspace_id, rule_id, _data(body))
    return PipelineRule.model_validate(saved)


@router.delete("/workspaces/{workspace_id}/pipelines/{rule_id}", status_code=204)
def delete_rule(core: CoreDep, workspace_id: str, rule_id: int) -> None:
    require_workspace(core, workspace_id)
    pipelines.delete(core, workspace_id, rule_id)
