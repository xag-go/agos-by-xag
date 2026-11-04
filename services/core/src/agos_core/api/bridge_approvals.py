"""Hermes's approvals in a channel, over HTTP: asked (AGOS shows the card) and
answered (AGOS closes it).

Owns: the two approval routes.
Must not: answer an approval.

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.api.bridge_access import ADDRESS, Auth, _checked
from agos_core.api.deps import CoreDep

__all__ = [
    "Answered",
    "Approval",
    "approval",
    "approval_done",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


class Approval(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    command: str = Field(default="", max_length=20_000)
    description: str = Field(default="", max_length=20_000)
    pattern: str = Field(default="", max_length=500)


class Answered(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    choice: str = Field(max_length=40)


@router.post("/approval")
async def approval(
    core: CoreDep, workspace_id: str, body: Approval, authorization: Auth = None
) -> dict[str, Any]:
    """Hermes asks Allow / Deny. `phone`: where Hermes also shows its own Telegram
    card for it (an AGOS chat's Telegram place), or null."""
    ws = _checked(core, workspace_id, authorization)
    phone = actions.approval_asked(
        core, ws, body.chat, body.command, body.description, body.pattern
    )
    return {"ok": True, "phone": phone}


@router.post("/approval-done")
async def approval_done(
    core: CoreDep, workspace_id: str, body: Answered, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    actions.approval_answered(core, ws, body.chat, body.choice)
    return {"ok": True}
