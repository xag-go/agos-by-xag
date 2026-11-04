"""The answer working now, in memory: the live turn registry the web long-polls, waiting on it, the loop turns run on.
Must not: keep anything Hermes keeps (what is said lives in Hermes).

Split out of agos_core.actions.chat (which re-exports it); behaviour unchanged.
"""

import asyncio
import contextvars
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.engine import doorbell
from agos_core.engine.chat import LiveTurn, live_key, turn_key

__all__ = [
    "AROUND_LOOK_S",
    "PENDING_LOOK_S",
    "in_thread",
    "live_moved",
    "live_snapshot",
    "pending",
    "wait_live",
]


@dataclass
class _Live:
    turn: LiveTurn
    stop: bool = False
    speaker: str | None = None
    # The task following this answer: when it is gone, nobody will close it.
    task: asyncio.Task[Any] | None = None


class _State:
    """Per-process chat state (Core is frozen, so it lives beside it)."""

    def __init__(self) -> None:
        self.live: dict[int, _Live] = {}
        self.tasks: set[asyncio.Task[None]] = set()


_STATES: dict[int, _State] = {}


def _state(core: Core) -> _State:
    return _STATES.setdefault(id(core.db), _State())


def _registry(core: Core) -> dict[int, _Live]:
    return _state(core).live


# ---- live view ---------------------------------------------------------------


def live_snapshot(core: Core, chat_id: int) -> dict[str, Any] | None:
    turn = repo.live_turn(core.db, chat_id)
    if turn is None:
        return None
    live = _registry(core).get(turn.id)
    snap = (live.turn if live else LiveTurn(turn_id=turn.id, status=turn.status)).snapshot()
    return {**snap, "speaker": turn.speaker}


# What an open chat shows beside the live answer (his message no answer started on
# yet, the Co-Founder chat's asks, questions and token warnings) is looked at while the
# view waits as often as the web asked before it waited here: every 4 s, every 0.4 s
# while his message waits for an answer to start.
AROUND_LOOK_S = 4.0
PENDING_LOOK_S = 0.4


def live_moved(snap: dict[str, Any] | None, after: int) -> bool:
    """The live answer is not the one the web shows (`after`: its version, -1 = none)."""
    return after != -1 if snap is None else snap["version"] != after


async def wait_live(
    core: Core,
    chat_id: int,
    after: int,
    timeout: float = 20,
    *,
    around: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Long-poll: returns as soon as the answer moved past `after` or ended, or (none
    live) one started; with `around` (what the view shows beside it, read in a thread)
    also as soon as that changed. Woken by the doorbell (doorbell.LIVE: a turn opened
    in the chat, the live answer moved or ended), it looks again every
    doorbell.FALLBACK_S anyway (a writer that doesn't ring). `held`: it waited, the
    web asks again at once."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    beside = await asyncio.to_thread(around) if around is not None else {}
    while True:
        look = PENDING_LOOK_S if beside.get("pending") else AROUND_LOOK_S
        left = deadline - loop.time()
        snap = await _wait_moved(core, chat_id, after, min(left, look) if around else left)
        if live_moved(snap, after) or deadline - loop.time() <= 0 or around is None:
            break
        now_beside = await asyncio.to_thread(around)
        if now_beside != beside:
            return {"live": snap, **now_beside, "held": True}
    if around is not None:
        beside = await asyncio.to_thread(around)  # as it is now, like the answer
    return {"live": snap, **beside, "held": True}


async def _wait_moved(core: Core, chat_id: int, after: int, timeout: float) -> Any:
    """The live answer once it moved past `after` (or `timeout` passed)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(timeout, 0.0)
    with doorbell.listening(doorbell.LIVE, live_key(chat_id)) as bell:  # listen, then look
        while True:
            snap = live_snapshot(core, chat_id)
            if snap is not None and (doorbell.LIVE, turn_key(snap["turnId"])) not in bell.keys:
                bell.also(doorbell.LIVE, turn_key(snap["turnId"]))
                snap = live_snapshot(core, chat_id)  # a change before it heard that bell
            left = deadline - loop.time()
            if live_moved(snap, after) or left <= 0:
                return snap
            await bell.wait(min(doorbell.FALLBACK_S, left))


def pending(core: Core, chat_id: int) -> bool:
    """He sent something no answer has started on yet."""
    if core.engine is None:
        return False
    row = repo.any_row(core.db, chat_id)
    if row is None:
        return False
    if repo.is_hermes(row):
        return repo.queued(core.db, row)
    return bool(repo.unanswered(core.db, chat_id))


def _background(core: Core) -> set[asyncio.Task[None]]:
    """Strong refs, so a running answer is never garbage-collected mid-way."""
    return _state(core).tasks


_T = TypeVar("_T")
# The app's event loop, for an owner action run in a worker thread: its reads may
# start Hermes (never on the loop), and what it starts (a room's answer) still
# starts on the loop at once. asyncio.to_thread hands this to the thread.
_LOOP: contextvars.ContextVar[asyncio.AbstractEventLoop | None] = contextvars.ContextVar(
    "agos_chat_loop", default=None
)


async def in_thread(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """An owner action off the event loop; an answer it starts begins on the loop."""
    _LOOP.set(asyncio.get_running_loop())
    return await asyncio.to_thread(fn, *args, **kwargs)


def _spawn(core: Core, coro: Any) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _LOOP.get()
        try:
            if loop is None:
                raise RuntimeError("no loop")
            loop.call_soon_threadsafe(_track, core, coro)
        except RuntimeError:  # no loop (sync callers, or it closed): the tick picks it up
            coro.close()
        return
    _track(core, coro)


def _track(core: Core, coro: Any) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    tasks = _background(core)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
