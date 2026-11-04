"""The owner's answer to a capability request from the Co-Founder (a chat card)."""

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import capabilities as actions
from agos_core.actions.capabilities import Decision
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body

router = APIRouter(tags=["capabilities"])


class DecisionBody(Body):
    approve: bool
    redirect_uri: str | None = Field(default=None, min_length=10, max_length=300)


@router.post("/workspaces/{workspace_id}/capability-requests/{request_id}")
async def decide(core: CoreDep, workspace_id: str, request_id: int, body: DecisionBody) -> Decision:
    """Approve (turn it on/off; an app not connected yet gives its login page) or refuse."""
    return await asyncio.to_thread(
        actions.decide, core, workspace_id, request_id, body.approve, body.redirect_uri
    )
