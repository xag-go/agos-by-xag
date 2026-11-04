"""How the gateways' long asks wait: on a doorbell rung by the writer, with a slow
fallback look for rows written by another process. The shared wait of next,
platform-next and room-next, and the outbox ask (AGOS's messages for the bot) with
its done mark, which rings it again for a row that goes again.

Owns: the outbox long ask's routes; the waits themselves (the doorbells) are
actions/services/channel/bridge_waits.py's.
Must not: know what the other asks take, or ring a doorbell itself.

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from agos_core.actions import channels
from agos_core.actions import hermes_channel as actions
from agos_core.actions.services.channel import bridge_waits as waits
from agos_core.actions.services.channel.bridge_waits import OUTBOX_WAIT_S as OUTBOX_WAIT_S
from agos_core.actions.services.channel.bridge_waits import REACTION_LOOK_S as REACTION_LOOK_S
from agos_core.actions.services.channel.bridge_waits import T as T
from agos_core.actions.services.channel.bridge_waits import waited as waited
from agos_core.api.bridge_access import Auth, Taker, _checked
from agos_core.api.deps import CoreDep

__all__ = [
    "OUTBOX_WAIT_S",
    "REACTION_LOOK_S",
    "OutboxDone",
    "T",
    "outbox",
    "outbox_done",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


@router.post("/outbox")
async def outbox(
    core: CoreDep,
    workspace_id: str,
    request: Request,
    authorization: Auth = None,
    body: Taker | None = None,
) -> dict[str, Any]:
    """What the workspace's gateway sends for AGOS on its bot (waits up to 25 s).
    A team member's own gateway has no bot: nothing for it."""
    ws = _checked(core, workspace_id, authorization)
    if body is not None and body.member:
        await asyncio.sleep(25)
        return {"send": [], "close": [], "topics": [], "reactions": []}
    return await waits.wait_outbox(core, ws, request.is_disconnected)


class OutboxDone(BaseModel):
    id: int
    kind: str = Field(default="send", pattern="^(send|close|topic|reaction)$")
    message_id: str | None = Field(default=None, alias="messageId", max_length=40)
    error: str | None = Field(default=None, max_length=500)


@router.post("/outbox-done")
async def outbox_done(
    core: CoreDep, workspace_id: str, body: OutboxDone, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    if body.kind == "reaction":
        await asyncio.to_thread(actions.reaction_done, core, ws, body.id, body.error)
    else:
        await asyncio.to_thread(
            channels.hermes_outbox_done, core, ws, body.id, body.kind, body.message_id, body.error
        )
    if body.error:
        waits.ring_outbox(ws)  # it goes again (until its last attempt)
    return {"ok": True}
