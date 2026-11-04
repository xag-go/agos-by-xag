"""The .env probe's Hermes runs: how many settings reads run at once, Hermes's answer while
a new root is being set up, and the runs a refused one waits for before asking again.

Must not: run Hermes itself (env.py does, inside these limits).

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator

__all__ = [
    "HERMES_SETTING_UP",
    "SETTINGS_RUNS",
    "_ProbeRuns",
]


# Hermes processes the settings reads (each profile as Hermes reads it, the .env
# probe's runs) start at once: each holds 100-200 MB while it runs.
SETTINGS_RUNS = 4

# What Hermes's launcher says when it starts in a data root that has no dependency
# environment committed yet while another start is setting one up: the start that
# claims the update marker builds it (hermes_cli/venv_sync.py prepare_launch →
# _prepare_borrowed_launch: `uv sync`, seconds to minutes); a start made meanwhile
# waits at most 10 s for the install lock (hermes_cli/runtime_state.py
# INSTALL_LOCK_TIMEOUT_SECONDS), then is refused and exits 1 (hermes_bootstrap.py:613
# activate_dependencies → pm/environments.py:446 _require_own_dependencies, printed
# at hermes_bootstrap.py:619). Only a brand-new root (a new workspace root, a profile
# home outside ~/.hermes) is in that state: every root a gateway runs on is set up.
HERMES_SETTING_UP = "no dependency environment is committed for this install"


class _ProbeRuns:
    """The .env probe's Hermes runs running now, so a run Hermes refused while a
    root was being set up (HERMES_SETTING_UP) asks again only after every probe run
    that was running then has ended (the probe's other run, when that one sets the
    root up), and these second asks go one at a time: the first of two refused runs
    can set the root up and the other then finds it set up. One after the other, as
    the probe's two runs went before they started together. Nothing here waits for
    anything but Hermes processes already running, so it never waits on a read
    cache's ask (no deadlock)."""

    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._running: set[object] = set()
        self._again = threading.Lock()

    @contextlib.contextmanager
    def running(self) -> Iterator[None]:
        mark = object()
        with self._changed:
            self._running.add(mark)
        try:
            yield
        finally:
            with self._changed:
                self._running.discard(mark)
                self._changed.notify_all()

    @contextlib.contextmanager
    def after_the_others(self) -> Iterator[None]:
        with self._changed:
            others = set(self._running)
            self._changed.wait_for(lambda: not others & self._running)
        with self._again:
            yield
