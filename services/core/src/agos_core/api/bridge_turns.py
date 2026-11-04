"""The plugin's turn calls: a Hermes turn's start, finish, stop and end, its live
events, and the items of the workspace's inbox it takes (for the bot, a member,
AGOS's own platform) and marks done.

Owns: the turn and inbox routes (actions/services/chat/gateway_turns.py, actions/services/channel/gateway_inbox.py).
Must not: hold turn logic (the actions do).

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.api.bridge_access import ADDRESS, Auth, Taker, _checked
from agos_core.api.bridge_waits import waited
from agos_core.api.deps import CoreDep

__all__ = [
    "MEMBER_HOLD_S",
    "WAIT_S",
    "Done",
    "LiveEvents",
    "PlatformSaid",
    "TurnEnd",
    "TurnFinish",
    "TurnStart",
    "TurnStop",
    "done",
    "events",
    "next_items",
    "platform_next",
    "platform_send",
    "turn_end",
    "turn_finish",
    "turn_start",
    "turn_stop",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


class TurnStart(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    session_id: str = Field(default="", alias="sessionId", max_length=200)
    # What Hermes read, when AGOS hasn't got it as written: "replace" (a voice note's
    # transcript) or "store" (a /command that became a request).
    said: str = Field(default="", max_length=200_000)
    how: str = Field(default="", pattern=r"^(|store|replace)$")
    sender: str = Field(default="", max_length=40)  # who wrote (read vs act)


class TurnFinish(BaseModel):
    """Only that the answer ended: how it ended, its model and its tokens are
    Hermes's own (agent.log, its sessions, session_model_usage)."""

    turn_id: int = Field(alias="turnId")
    text: str = Field(default="", max_length=2_000_000)


class TurnStop(BaseModel):
    """Hermes interrupted the answer (its agent_loop_stopped): no answer comes."""

    turn_id: int = Field(alias="turnId")
    reason: str = Field(default="", max_length=500)


class TurnEnd(BaseModel):
    """How Hermes ended the turn (its on_session_end hook: turn_exit_reason)."""

    turn_id: int = Field(alias="turnId")
    reason: str = Field(default="", max_length=500)


@router.post("/turn-start")
def turn_start(
    core: CoreDep, workspace_id: str, b: TurnStart, authorization: Auth = None
) -> dict[str, object]:
    ws = _checked(core, workspace_id, authorization)
    return actions.turn_start(core, ws, b.chat, b.session_id, b.said, b.how, b.sender)


@router.post("/turn-finish")
async def turn_finish(
    core: CoreDep, workspace_id: str, body: TurnFinish, authorization: Auth = None
) -> dict[str, str]:
    ws = _checked(core, workspace_id, authorization)
    actions.turn_finish(core, ws, body.turn_id, body.text)
    # Hermes's own text, unchanged: a gateway still running the previous plugin
    # (until AGOS restarts it with this one) sends what it gets back here.
    return {"text": body.text}


@router.post("/turn-stop")
async def turn_stop(
    core: CoreDep, workspace_id: str, body: TurnStop, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    actions.turn_stopped(core, ws, body.turn_id, body.reason)
    return {"ok": True}


@router.post("/turn-end")
async def turn_end(
    core: CoreDep, workspace_id: str, body: TurnEnd, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    actions.turn_ended(core, ws, body.turn_id, body.reason)
    return {"ok": True}


class Done(BaseModel):
    id: int
    ok: bool = True


# How long /next and /platform-next wait for something (the plugin asks again at once).
WAIT_S = 20.0
# A member's /next is held this long (an older plugin's own wait is 40 s).
MEMBER_HOLD_S = 25.0


@router.post("/next")
async def next_items(
    core: CoreDep,
    workspace_id: str,
    authorization: Auth = None,
    body: Taker | None = None,
) -> dict[str, object]:
    """What he wrote in AGOS, for Hermes to take into the conversation. Waits up to
    20 s for something to come (the plugin asks again right away)."""
    ws = _checked(core, workspace_id, authorization)
    member = body.member if body else ""
    if member:
        # A team member's own copy of the plugin: nothing ever comes here for it (a
        # member has no Telegram; its AGOS conversations come by platform-next), and
        # the plugin no longer asks. One from before asks again at once: held, with
        # no query, so it waits instead of spinning.
        await asyncio.sleep(MEMBER_HOLD_S)
        return {"items": []}
    items = await waited(ws, lambda: actions.take_inbox(core, ws, member=member), WAIT_S, bool)
    return {"items": items}


@router.post("/platform-next")
async def platform_next(
    core: CoreDep,
    workspace_id: str,
    authorization: Auth = None,
    body: Taker | None = None,
) -> dict[str, object]:
    """What he wrote in AGOS's own conversations, for the plugin's agos platform.
    `members`: one ask for every profile of the gateway (a newer plugin), answered
    with whose each item is; an older plugin asks per profile (`member`)."""
    ws = _checked(core, workspace_id, authorization)
    if body is not None and body.members is not None:
        members = sorted({m for m in body.members if re.fullmatch(r"[a-z0-9-]{0,64}", m)})
        items = await waited(
            ws, lambda: actions.take_inbox(core, ws, agos=True, members=members), WAIT_S, bool
        )
        return {"items": items, "members": members}
    member = body.member if body else ""
    items = await waited(
        ws, lambda: actions.take_inbox(core, ws, agos=True, member=member), WAIT_S, bool
    )
    return {"items": items}


class PlatformSaid(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    text: str = Field(max_length=200_000)


@router.post("/platform-send")
async def platform_send(
    core: CoreDep, workspace_id: str, body: PlatformSaid, authorization: Auth = None
) -> dict[str, bool]:
    """What Hermes says in an AGOS conversation."""
    ws = _checked(core, workspace_id, authorization)
    shown = await asyncio.to_thread(actions.platform_said, core, ws, body.chat, body.text)
    return {"shown": shown}


@router.post("/done")
async def done(
    core: CoreDep, workspace_id: str, body: Done, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    actions.inbox_done(core, ws, body.id, body.ok)
    return {"ok": True}


class LiveEvents(BaseModel):
    turn_id: int = Field(alias="turnId")
    events: list[dict[str, object]] = Field(default_factory=list, max_length=500)


@router.post("/events")
async def events(
    core: CoreDep, workspace_id: str, body: LiveEvents, authorization: Auth = None
) -> dict[str, bool]:
    """The answer as Hermes writes it (text, tools), shown live in the AGOS chat."""
    ws = _checked(core, workspace_id, authorization)
    actions.live_events(core, ws, body.turn_id, body.events)
    return {"ok": True}
