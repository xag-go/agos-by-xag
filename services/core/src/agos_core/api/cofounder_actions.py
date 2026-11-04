"""What the Co-Founder did (or asks to do) from a chat: approve, refuse, undo; and the mode."""

import asyncio
from typing import Literal

from fastapi import APIRouter

from agos_core.actions import cofounder_actions as actions
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import CofounderActionView

router = APIRouter(tags=["cofounder-actions"])


class ActionChoice(Body):
    choice: Literal["approve", "reject", "undo"]


class ActionsMode(Body):
    mode: Literal["direct", "ask"]


@router.post("/workspaces/{workspace_id}/cofounder-actions/{action_id}")
async def decide(
    core: CoreDep, workspace_id: str, action_id: int, body: ActionChoice
) -> CofounderActionView:
    return await asyncio.to_thread(actions.decide, core, workspace_id, action_id, body.choice)


@router.get("/cofounder-actions/mode")
def get_mode(core: CoreDep) -> ActionsMode:
    return ActionsMode(mode=actions.mode(core))


@router.put("/cofounder-actions/mode")
async def put_mode(core: CoreDep, body: ActionsMode) -> ActionsMode:
    """direct: the Co-Founder does what you ask at once (Undo on each card); ask: Approve first."""
    actions.set_mode(core, body.mode)
    return body
