"""A group's Hermes room (ADR 0020), over HTTP: the plugin in the workspace's gateway
takes the room's turns, holds them, reports them done, live and their approvals.

Owns: the room routes and how long a room ask waits.
Must not: run a room's turn (actions/rooms.py).

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.api.bridge_access import Auth, _checked
from agos_core.api.bridge_waits import waited
from agos_core.api.deps import CoreDep

__all__ = [
    "ROOM_ID",
    "ROOM_WAIT_MAX_S",
    "ROOM_WAIT_S",
    "RoomApproval",
    "RoomDone",
    "RoomEvents",
    "RoomHeld",
    "RoomHeldNow",
    "RoomLive",
    "RoomNext",
    "room_approval",
    "room_done",
    "room_events",
    "room_held",
    "room_live",
    "room_next",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


# How long /room-next waits for a job when the plugin doesn't say (an older one reads
# the room logs between asks), and the longest it may ask for (a newer one: 20 s).
ROOM_WAIT_S = 2.0
ROOM_WAIT_MAX_S = 25.0


ROOM_ID = r"^agos-c\d{1,12}-g\d{1,6}$"


class RoomHeld(BaseModel):
    """What one of the workspace's Hermes rooms holds now (the plugin reads it from
    Hermes's room service): the approvals its members wait on, and its members
    (None: Hermes has no such room now)."""

    pending: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    # H: gateway/hosted_rooms.py:30 MAX_MEMBERS
    members: list[dict[str, Any]] | None = Field(default=None, max_length=128)


class RoomNext(BaseModel):
    rooms: dict[str, RoomHeld] = Field(default_factory=dict, max_length=200)
    # How long to wait for a job: a newer plugin reads the room logs on its own thread,
    # so it waits long (0: answer now); an older one says nothing (ROOM_WAIT_S).
    wait: float | None = Field(default=None, ge=0, le=ROOM_WAIT_MAX_S)


class RoomHeldNow(BaseModel):
    """What Hermes's rooms hold now, told by a newer plugin on its own ask when it
    changed (`hash`: which report this is; room-next says which one AGOS has)."""

    rooms: dict[str, RoomHeld] = Field(default_factory=dict, max_length=200)
    hash: str = Field(default="", max_length=128)


def _rooms_of_workspace(held: dict[str, RoomHeld]) -> dict[str, dict[str, Any]]:
    return {
        room_id: info.model_dump()
        for room_id, info in held.items()
        if re.fullmatch(ROOM_ID, room_id)
    }


@router.post("/room-next")
async def room_next(
    core: CoreDep,
    workspace_id: str,
    authorization: Auth = None,
    body: RoomNext | None = None,
) -> dict[str, object]:
    """Room jobs for the workspace's gateway, and how far AGOS has read each room.
    Waits for a job as long as the plugin asks (an older plugin: 2 s, it reads the
    room logs between asks). `held`: which report of what Hermes's rooms hold AGOS
    has ("" none: a newer plugin tells it, room-held); an older plugin tells it with
    each ask (`rooms`)."""
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    if body is not None and "rooms" in body.model_fields_set:
        await asyncio.to_thread(rooms.told, core, ws, _rooms_of_workspace(body.rooms))
    wait = ROOM_WAIT_S if body is None or body.wait is None else body.wait
    got = await waited(ws, lambda: rooms.take(core, ws), wait, lambda found: bool(found["items"]))
    return {**got, "held": rooms.held_mark(core, ws)}


@router.post("/room-held")
async def room_held(
    core: CoreDep, workspace_id: str, body: RoomHeldNow, authorization: Auth = None
) -> dict[str, str]:
    """What Hermes's rooms hold now (members, waiting approvals): a newer plugin tells
    it here only when it changed, or when room-next's `held` isn't its report."""
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    await asyncio.to_thread(rooms.told, core, ws, _rooms_of_workspace(body.rooms), body.hash)
    return {"held": body.hash}


class RoomDone(BaseModel):
    id: int
    ok: bool = True
    error: str = Field(default="", max_length=2000)
    event: str = Field(default="", max_length=200)


@router.post("/room-done")
async def room_done(
    core: CoreDep, workspace_id: str, body: RoomDone, authorization: Auth = None
) -> dict[str, bool]:
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    await asyncio.to_thread(rooms.done, core, ws, body.id, body.ok, body.error, body.event)
    return {"ok": True}


class RoomEvents(BaseModel):
    room_id: str = Field(alias="roomId", pattern=ROOM_ID)
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


@router.post("/room-events")
async def room_events(
    core: CoreDep, workspace_id: str, body: RoomEvents, authorization: Auth = None
) -> dict[str, int]:
    """The room's new log events (each taken once). Returns AGOS's cursor."""
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    cursor = await asyncio.to_thread(rooms.events, core, ws, body.room_id, body.events)
    return {"cursor": cursor}


class RoomLive(BaseModel):
    room_id: str = Field(alias="roomId", pattern=ROOM_ID)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


@router.post("/room-live")
async def room_live(
    core: CoreDep, workspace_id: str, body: RoomLive, authorization: Auth = None
) -> dict[str, bool]:
    """A room member's work as it happens (Hermes's on_room_member_activity)."""
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    rooms.live(core, ws, body.room_id, body.items)
    return {"ok": True}


class RoomApproval(BaseModel):
    room_id: str = Field(alias="roomId", pattern=ROOM_ID)
    member_id: str = Field(alias="memberId", max_length=128)
    task_id: str = Field(alias="taskId", max_length=200)
    execution_generation: int = Field(alias="executionGeneration", ge=0)
    request_id: str = Field(alias="requestId", min_length=1, max_length=200)
    command: str = Field(default="", max_length=8000)
    description: str = Field(default="", max_length=2000)


@router.post("/room-approval")
async def room_approval(
    core: CoreDep, workspace_id: str, body: RoomApproval, authorization: Auth = None
) -> dict[str, int | None]:
    """A room member waits on the owner's Allow once / Deny (Hermes's request.opened)."""
    from agos_core.actions import rooms

    ws = _checked(core, workspace_id, authorization)
    asked = await asyncio.to_thread(
        rooms.approval, core, ws, body.room_id, body.model_dump(by_alias=False)
    )
    return {"id": asked}
