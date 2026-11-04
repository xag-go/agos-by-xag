"""What pages need from Hermes, asked once in the background after the core
starts, so the first page after an update or a restart is as fast as the next.

Each entry is "module:function" taking the core; they run one after the other on
the read cache's background threads (never two Hermes starts at once from here),
and a failing one is logged and skipped. Each function only fills a
`read_cache.ReadCache` the page itself reads: nothing is stored anywhere else.
"""

from __future__ import annotations

import importlib
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Filled by the modules that own a page's Hermes reads (one line each), in the
# order the owner meets them after a restart: the cheap reads (one Hermes run or
# none) and the pages he opens most (board, dashboard, chats) first, then the
# settings pages (Hermes settings: a few seconds, four Hermes runs at once); the
# long ones (a Hermes run per profile of every workspace, `hermes doctor`) last.
WARMERS: tuple[str, ...] = (
    # Settings → Models and every model picker: Hermes's model catalog.
    "agos_core.api.models:read_ahead",
    # Usage → account limits: what Hermes reads from each logged-in provider.
    "agos_core.engine.limits:read_ahead",
    # Settings → Channels and each workspace's bots: every bot's state.
    "agos_core.actions.channels:read_ahead",
    # The Board: Hermes's list of cards and its counters (each workspace with a board).
    "agos_core.actions.kanban_board:read_ahead",
    # The Dashboard: Hermes's usage analytics and its bots' lamps (each workspace).
    "agos_core.actions.services.system.dashboard:read_ahead",
    # A chat's page: Hermes's routing index, each chat's own Full access (each workspace).
    "agos_core.actions.access:read_ahead",
    # A chat's "/" menu: each root's Hermes command menu.
    "agos_core.actions.hermes_channel:read_ahead",
    # A workspace's Hermes settings card: Hermes's settings list (its defaults).
    "agos_core.actions.hermes_settings:read_ahead",
    # Settings → Helper models: Hermes's settings list, each profile as Hermes reads it.
    "agos_core.actions.hermes_helper_models:read_ahead",
    # Settings → Hermes settings: the page's Hermes asks (each profile's .env-vs-
    # config.yaml probe and the rest), at most four Hermes processes at once. Right
    # after the first pages: it was 17th and the first view after a start waited.
    "agos_core.actions.hermes_all_settings:read_ahead",
    # Workspace → Apps: Composio's app list for the picker (one fetch, a day).
    "agos_core.actions.composio:read_ahead",
    # Workspace → Apps: each workspace's Composio accounts (Composio's own list).
    "agos_core.actions.apps:read_ahead_composio_accounts",
    # Settings → Connectors and Workspace → Apps: Hermes's Nous apps state.
    "agos_core.actions.apps:read_ahead_nous",
    # Settings → Backups: the walk of AGOS's data folder for its size (no Hermes).
    "agos_core.actions.backups:read_ahead",
    # Settings → Models → several keys: each home's pool list and statuses.
    "agos_core.actions.key_pools:read_ahead",
    # Library → tools (each profile's tool services) and the GitHub token card;
    # Settings → Skills (Hermes's update check of the hub's skills).
    "agos_core.actions.library:read_ahead",
    # Held-back writes: Hermes's write-approval queue of every profile (each workspace).
    "agos_core.actions.held_writes:read_ahead",
    # Workspace → Capabilities: each workspace's tool check in its Hermes's runtime
    # (also in AT_START; here again it costs nothing while the answer is kept).
    "agos_core.actions.library:read_ahead_connectors",
    # Learned: Hermes's skill ledger of every profile (each workspace).
    "agos_core.actions.proactive:read_ahead",
    # Settings → Health: each root's first `hermes status` and `hermes doctor`, one
    # Hermes run at a time (doctor: 6-12 s a root, the longest of all). Last on
    # purpose: its page no longer waits for it (a root not checked yet shows as
    # checking and fills in as its run ends), while the page of every warmer above
    # still waits for its read when cold; earlier, it would hold all of them back.
    "agos_core.actions.hermes_health:read_ahead",
)

# Asked at once when the core starts, beside the start's sync instead of after it:
# the sync (sandbox checks, gateway hand-over of every workspace) takes minutes on
# a busy server, and the owner's first pages after a restart are the model pickers
# (Hermes's model catalog: ~3 s cold) and a workspace's Capabilities (its tool
# check: ~1 s cold). Both only read Hermes; they run again (kept: no Hermes start)
# with WARMERS after the sync.
AT_START: tuple[str, ...] = (
    "agos_core.api.models:read_ahead",
    "agos_core.actions.library:read_ahead_connectors",
)


def run(core: Any, warmers: tuple[str, ...] | None = None) -> dict[str, float]:
    """Runs every warmer in order on a low-priority thread of its own (what it
    starts never slows the owner's pages); returns seconds per warmer (failed
    ones too)."""
    import threading

    from agos_core.engine.read_cache import low_priority

    took: dict[str, float] = {}

    def go() -> None:
        low_priority()
        for spec in WARMERS if warmers is None else warmers:
            started = time.monotonic()
            try:
                module, _, name = spec.partition(":")
                getattr(importlib.import_module(module), name)(core)
            except Exception:
                log.warning("read-ahead %s failed", spec, exc_info=True)
            took[spec] = round(time.monotonic() - started, 3)

    thread = threading.Thread(target=go, name="agos-read-ahead-start", daemon=True)
    thread.start()
    thread.join()
    if took:
        log.info("read ahead from Hermes: %s", took)
    return took
