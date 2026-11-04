"""Domain events: what happened in a service (a workspace made, a card moved, a
member hired), told to in-process subscribers, synchronously, after the change
committed.

A service never publishes from inside its transaction: it hands the event to its
Unit of Work (`UnitOfWork.publish`), which publishes once the commit landed, so a
rolled-back change tells nobody. Notifications, pipelines and watchdogs subscribe
here instead of being called inline by the service that changed something.

Owns: the subscriber table and the publishing rule (in order; a subscriber that
fails is logged to the System Log and never stops the others or the change).
Must not: send anything out of the process (the outbox does), hold any service's
rules, or be called by a service inside an open transaction.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "WORKSPACE_CREATED",
    "WORKSPACE_TRASHED",
    "Event",
    "Handler",
    "publish",
    "subscribe",
]

log = logging.getLogger("agos.events")

WORKSPACE_CREATED = "workspace.created"
WORKSPACE_TRASHED = "workspace.trashed"


@dataclass(frozen=True)
class Event:
    """One thing that happened. `data` holds plain JSON values only."""

    kind: str
    workspace_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


Handler = Callable[[Any, Event], None]

_lock = threading.Lock()
_subscribers: dict[str, list[Handler]] = {}


def subscribe(kind: str, handler: Handler) -> Callable[[], None]:
    """`handler(core, event)` for every event of `kind`; returns the unsubscribe."""
    with _lock:
        _subscribers.setdefault(kind, []).append(handler)

    def stop() -> None:
        with _lock:
            handlers = _subscribers.get(kind, [])
            if handler in handlers:
                handlers.remove(handler)

    return stop


def publish(core: Any, event: Event) -> None:
    """Runs every subscriber of the event's kind, in the order they subscribed."""
    with _lock:
        handlers = list(_subscribers.get(event.kind, []))
    for handler in handlers:
        try:
            handler(core, event)
        except Exception:
            log.exception(
                "a subscriber of %s failed",
                event.kind,
                extra={"agos_workspace": event.workspace_id} if event.workspace_id else None,
            )
