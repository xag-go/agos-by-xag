"""Learning and the owner's Autonomy rules (actions/proactive.py,
actions/autonomy.py)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import autonomy, proactive, trusted_apps
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["proactive"])


class RuleBody(BaseModel):
    agent: str = Field(max_length=64)
    action: str = Field(max_length=32)
    choice: Literal["do", "ask", "never"] | None


@router.get("/workspaces/{workspace_id}/learned")
async def get_learned(core: CoreDep, workspace_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(proactive.learned, core, workspace_id)


@router.post("/workspaces/{workspace_id}/learned/{entry_id}/undo", status_code=204)
async def undo_learned(core: CoreDep, workspace_id: str, entry_id: str) -> None:
    await asyncio.to_thread(proactive.undo_change, core, workspace_id, entry_id)


@router.get("/workspaces/{workspace_id}/autonomy")
def get_autonomy(core: CoreDep, workspace_id: str) -> dict[str, Any]:
    return autonomy.view(core, workspace_id)


@router.put("/workspaces/{workspace_id}/autonomy", status_code=204)
def put_autonomy(core: CoreDep, workspace_id: str, body: RuleBody) -> None:
    autonomy.set_rule(core, workspace_id, body.agent, body.action, body.choice)


class TrustedApps(BaseModel):
    apps: list[str] = Field(max_length=50)


@router.put("/workspaces/{workspace_id}/trusted-apps", status_code=204)
async def put_trusted_apps(core: CoreDep, workspace_id: str, body: TrustedApps) -> None:
    """The apps whose answers don't count as untrusted (read vs act). Empty = none."""
    await asyncio.to_thread(trusted_apps.save, core, workspace_id, body.apps)


# ---- the owner's rules for every workspace (actions/owner_rules.py) ---------------


class OwnerRule(BaseModel):
    id: int
    text: str
    from_workspace: str | None = Field(default=None, alias="fromWorkspace")
    created_at: str = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class OwnerRuleText(BaseModel):
    text: str = Field(min_length=1)


@router.get("/owner-rules")
def get_owner_rules(core: CoreDep) -> list[OwnerRule]:
    from agos_core.actions import owner_rules

    return [OwnerRule(**r) for r in owner_rules.list_rules(core)]


@router.post("/owner-rules", status_code=201)
async def add_owner_rule(core: CoreDep, body: OwnerRuleText) -> dict[str, int]:
    from agos_core.actions import owner_rules

    return {"id": await asyncio.to_thread(owner_rules.add, core, body.text)}


@router.put("/owner-rules/{rule_id}", status_code=204)
async def edit_owner_rule(core: CoreDep, rule_id: int, body: OwnerRuleText) -> None:
    from agos_core.actions import owner_rules

    await asyncio.to_thread(owner_rules.edit, core, rule_id, body.text)


@router.delete("/owner-rules/{rule_id}", status_code=204)
async def delete_owner_rule(core: CoreDep, rule_id: int) -> None:
    from agos_core.actions import owner_rules

    await asyncio.to_thread(owner_rules.delete, core, rule_id)


# ---- general check -------------------------------------------------------------------


# ---- the AGOS Brain: ways of working for every workspace (actions/brain.py) -------


class BrainMethod(BaseModel):
    id: int
    text: str
    from_workspace: str | None = Field(default=None, alias="fromWorkspace")
    created_at: str = Field(alias="createdAt")
    used_here: bool = Field(default=True, alias="usedHere")

    model_config = {"populate_by_name": True}


class BrainUse(BaseModel):
    used: bool


@router.get("/brain")
def get_brain(core: CoreDep) -> list[BrainMethod]:
    from agos_core.actions import brain

    return [BrainMethod(**m) for m in brain.list_methods(core)]


@router.post("/brain", status_code=201)
async def add_method(core: CoreDep, body: OwnerRuleText) -> dict[str, int]:
    from agos_core.actions import brain

    return {"id": await asyncio.to_thread(brain.add, core, body.text)}


@router.put("/brain/{method_id}", status_code=204)
async def edit_method(core: CoreDep, method_id: int, body: OwnerRuleText) -> None:
    from agos_core.actions import brain

    await asyncio.to_thread(brain.edit, core, method_id, body.text)


@router.delete("/brain/{method_id}", status_code=204)
async def delete_method(core: CoreDep, method_id: int) -> None:
    from agos_core.actions import brain

    await asyncio.to_thread(brain.delete, core, method_id)


@router.get("/workspaces/{workspace_id}/brain")
def get_workspace_brain(core: CoreDep, workspace_id: str) -> list[BrainMethod]:
    from agos_core.actions import brain
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return [BrainMethod(**m) for m in brain.list_methods(core, workspace_id)]


@router.put("/workspaces/{workspace_id}/brain/{method_id}", status_code=204)
async def use_method_here(core: CoreDep, workspace_id: str, method_id: int, body: BrainUse) -> None:
    """On / "Not here" for one method in one workspace."""
    from agos_core.actions import brain

    await asyncio.to_thread(brain.set_used_here, core, workspace_id, method_id, body.used)
