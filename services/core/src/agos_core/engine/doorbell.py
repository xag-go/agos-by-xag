"""Doorbells for the long asks: the gateways' (api/hermes_bridge.py) and an open chat's
live view (`/live`, actions/chat.py wait_live).

A long ask (`/next`, `/platform-next`, `/room-next`, `/live`) waits on its bell
instead of asking SQLite again every 0.15-0.5 s; whatever queues something for it
(or changes what it shows) rings, from any thread (`def` routes and background work run in threads: the ring
reaches the waiting ask's loop with `call_soon_threadsafe`). A missed ring only
delays: a waiting ask looks again every FALLBACK_S anyway (the re-hand-out of an item
not confirmed within a minute, a row written by another process).
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator

INBOX = "inbox"  # hermes_inbox: what he wrote in AGOS, approvals, commands, room jobs
OUTBOX = "outbox"  # channel_outbox, channel_reactions, topics: what the bot sends for AGOS
# An agent's line or a turn's end in a chat (a reply to relay), a card answered (its
# buttons to close): the channels send round (actions/channels.py) looks now.
SEND = "send"
# What an open chat shows live: a turn opened in the chat ("chat:<id>"), the live
# answer moved or ended ("turn:<id>"; actions/chat.py live_key / turn_key).
LIVE = "live"
FALLBACK_S = 5.0

_lock = threading.Lock()
_waiting: dict[tuple[str, str], set[Wait]] = {}
_held = threading.local()  # together(): this thread's rings, until its block ends


class Wait:
    """One long ask's wait: its own loop and event (set from any thread)."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.event = asyncio.Event()
        self.keys: list[tuple[str, str]] = []

    def also(self, queue: str, key: str) -> None:
        """Hear this bell too (until the `listening` block ends): look again after,
        a ring that came before it was not heard."""
        entry = (queue, key)
        if entry in self.keys:
            return
        with _lock:
            _waiting.setdefault(entry, set()).add(self)
        self.keys.append(entry)

    def ring(self) -> None:
        with contextlib.suppress(RuntimeError):  # its loop already closed
            self.loop.call_soon_threadsafe(self.event.set)

    async def wait(self, timeout: float) -> bool:
        """True when rung; False when `timeout` passed first."""
        try:
            await asyncio.wait_for(self.event.wait(), timeout)
        except TimeoutError:
            return False
        finally:
            self.event.clear()
        return True


@contextlib.contextmanager
def listening(queue: str, workspace_id: str) -> Iterator[Wait]:
    """Listen first, then look: a ring that comes between the look and the wait
    still wakes it."""
    wait = Wait()
    wait.also(queue, workspace_id)
    try:
        yield wait
    finally:
        with _lock:
            for key in wait.keys:
                waits = _waiting.get(key)
                if waits is not None:
                    waits.discard(wait)
                    if not waits:
                        del _waiting[key]


@contextlib.contextmanager
def together() -> Iterator[None]:
    """This thread's rings wait until the block ends, then ring once each: what one
    step queues in several writes (a room's sync, then the message for it) wakes a
    waiting ask once, when all of it is in, so the ask takes it in one answer."""
    if getattr(_held, "rings", None) is not None:  # an outer block rings for us
        yield
        return
    rings: dict[tuple[str, str | None], None] = {}  # in order, once each
    _held.rings = rings
    try:
        yield
    finally:
        _held.rings = None
        for queue, workspace_id in rings:
            _ring_now(queue, workspace_id)


def ring(queue: str, workspace_id: str | None = None) -> None:
    """Something was queued for the workspace (None: for one whose id the writer
    doesn't have, e.g. by Telegram connection): its waiting asks look now. Any thread;
    nothing to do when nobody waits. Inside `together()`: when its block ends."""
    held: dict[tuple[str, str | None], None] | None = getattr(_held, "rings", None)
    if held is not None:
        held[(queue, workspace_id)] = None
        return
    _ring_now(queue, workspace_id)


def _ring_now(queue: str, workspace_id: str | None) -> None:
    with _lock:
        if workspace_id is None:
            waits = [w for (q, _ws), ws_waits in _waiting.items() if q == queue for w in ws_waits]
        else:
            waits = list(_waiting.get((queue, workspace_id), ()))
    for wait in waits:
        wait.ring()
