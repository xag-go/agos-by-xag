"""A workspace's agent identity (SOUL.md) and memory."""

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import identity as actions
from agos_core.actions.identity import IdentityView
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body

router = APIRouter(tags=["identity"])


class IdentityBody(Body):
    identity: str = Field(default="")


class MemoryBody(Body):
    entries: list[str] = Field(default_factory=list)


@router.get("/workspaces/{workspace_id}/identity")
def get_identity(core: CoreDep, workspace_id: str) -> IdentityView:
    return actions.get_identity(core, workspace_id)


@router.put("/workspaces/{workspace_id}/identity", status_code=204)
def save_identity(core: CoreDep, workspace_id: str, body: IdentityBody) -> None:
    actions.save_identity(core, workspace_id, body.identity)


@router.put("/workspaces/{workspace_id}/memory/{target}", status_code=204)
async def save_memory(
    core: CoreDep, workspace_id: str, target: Literal["memory", "user"], body: MemoryBody
) -> None:
    actions.save_memory(core, workspace_id, target, body.entries)
