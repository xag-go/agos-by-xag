"""Hermes is never started on the core's event loop.

An `async def` route runs on the one event loop every page, every live chat and
every gateway call goes through: while it waits for a Hermes process (about 1 s,
far more when the machine is busy), all of them wait. Work that starts Hermes runs
in a thread (`def` routes run in FastAPI's threadpool; `asyncio.to_thread`).

`off_loop` is called where AGOS starts a Hermes process. Tests set
AGOS_STRICT_LOOP=1 so a route that breaks the rule fails; live it is logged once
per place.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading

log = logging.getLogger(__name__)

_told: set[str] = set()
_told_lock = threading.Lock()
# Strict mode: every place that broke the rule, kept even when a caller's broad
# `except` swallowed the error (the test suite fails a test that left one here).
broken: list[str] = []


def on_loop() -> bool:
    """True when this code runs on a running event loop's own thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def off_loop(what: str) -> None:
    """Fails (tests) or warns once (live) when Hermes is started on the event loop."""
    if not on_loop():
        return
    if os.environ.get("AGOS_STRICT_LOOP") == "1":
        with _told_lock:
            broken.append(what)
        raise RuntimeError(f"Hermes started on the core's event loop: {what}")
    with _told_lock:
        if what in _told:
            return
        _told.add(what)
    log.warning("Hermes started on the core's event loop (every page waits): %s", what)
