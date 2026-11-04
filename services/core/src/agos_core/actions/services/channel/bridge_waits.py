"""How the gateways' long asks wait: on a doorbell rung by the writer (engine/doorbell.py),
with a slow fallback look for rows written by another process. The shared wait of
next, platform-next and room-next, and the outbox wait (AGOS's messages for the bot).

Owns: those waits and the outbox's ring when a row goes again. The HTTP side (the
bridge key, the routes) is api/bridge_waits.py's.
Must not: know what the other asks take, or read a request.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from agos_core.actions import channels
from agos_core.actions import hermes_channel as actions
from agos_core.context import Core
from agos_core.engine import doorbell

__all__ = [
    "OUTBOX_WAIT_S",
    "REACTION_LOOK_S",
    "T",
    "outbox_look",
    "ring_outbox",
    "wait_outbox",
    "waited",
]

log = logging.getLogger("agos.hermes_bridge")

T = TypeVar("T")

# The outbox's wait (the gateway's own is 40 s), and how often it looks while one of
# his messages waits for its 👍 / 👎.
OUTBOX_WAIT_S = 25.0
REACTION_LOOK_S = 0.5
_NOTHING: dict[str, Any] = {"send": [], "close": [], "topics": [], "reactions": []}


async def waited(ws: str, take: Callable[[], T], wait_s: float, found: Callable[[T], bool]) -> T:
    """`take` now, then each time something is queued for the workspace (its
    doorbell) and every doorbell.FALLBACK_S, until it found something or `wait_s`
    passed. `take` runs in a thread: no statement on the loop, which every page and
    gateway shares."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    with doorbell.listening(doorbell.INBOX, ws) as bell:
        while True:
            got = await asyncio.to_thread(take)
            left = deadline - loop.time()
            if found(got) or left <= 0:
                return got
            await bell.wait(min(doorbell.FALLBACK_S, left))


async def wait_outbox(core: Core, ws: str, gone: Callable[[], Awaitable[bool]]) -> dict[str, Any]:
    """What the workspace's bot sends now, waiting up to OUTBOX_WAIT_S for something;
    nothing once `gone` says the gateway went."""
    loop = asyncio.get_running_loop()
    began = loop.time()
    deadline = began + OUTBOX_WAIT_S
    with doorbell.listening(doorbell.OUTBOX, ws) as bell:
        while True:
            if await gone():
                # The gateway went (a restart): rows claimed now would wait CLAIM_FOR_S
                # before the new one gets them.
                return dict(_NOTHING)
            got, waiting = await asyncio.to_thread(outbox_look, core, ws)
            if got["send"] and loop.time() - began > 35:
                # The gateway waits 40 s: an answer this late may never reach it (its
                # rows go out again after channels.CLAIM_FOR_S).
                log.warning("outbox of %s answered late (%.0fs)", ws, loop.time() - began)
            left = deadline - loop.time()
            if got["send"] or got["close"] or got["topics"] or got["reactions"] or left <= 0:
                return got
            # A 👀 waiting for its answer to settle is due at a time nothing rings for:
            # looked at as often as before; else the bell (and a look every FALLBACK_S).
            await bell.wait(min(REACTION_LOOK_S if waiting else doorbell.FALLBACK_S, left))


def outbox_look(core: Core, ws: str) -> tuple[dict[str, Any], bool]:
    """What the bot sends now, and whether a reaction is still waiting (one thread hop)."""
    got = channels.hermes_outbox(core, ws)
    # His messages whose answer (AGOS's) is out: Hermes's own 👍 / 👎 on them.
    got["reactions"] = actions.reactions_ready(core, ws)
    return got, actions.reactions_open(core, ws)


def ring_outbox(ws: str) -> None:
    """A row of the outbox goes again (until its last attempt): wake its wait."""
    doorbell.ring(doorbell.OUTBOX, ws)
