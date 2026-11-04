"""Composio keys: each workspace pastes the key of ITS OWN Composio project.

One Composio project per workspace (plan 2): a project's key reaches only that
project, so a workspace's Hermes can never see another workspace's accounts. A
key is sealed with the core's master key, per workspace; only its last 4 are
ever shown. The same project can't be given to two workspaces (checked).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import weakref

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import delete_setting, get_setting, set_setting
from agos_core.db.records import Record
from agos_core.engine import composio as cz
from agos_core.engine import read_cache
from agos_core.security.secrets import decrypt_secret, encrypt_secret

log = logging.getLogger("agos.composio")

CATALOG_TTL_S = 24 * 3600


class ComposioToolkit(Record):
    slug: str
    name: str
    description: str
    logo: str
    categories: list[str]
    ready: bool


def _setting(workspace_id: str) -> str:
    return f"composio_key:{workspace_id}"


def _context(workspace_id: str) -> str:
    return f"composio-key:{workspace_id}"


def last4(core: Core, workspace_id: str) -> str | None:
    saved = get_setting(core.db, _setting(workspace_id), None)
    return str(saved.get("last4") or "") or None if isinstance(saved, dict) else None


def key(core: Core, workspace_id: str) -> str | None:
    saved = get_setting(core.db, _setting(workspace_id), None)
    if not isinstance(saved, dict) or not saved.get("sealed"):
        return None
    return decrypt_secret(core.master_key, str(saved["sealed"]), _context(workspace_id))


def store(core: Core, workspace_id: str, value: str) -> None:
    sealed = encrypt_secret(core.master_key, value, _context(workspace_id))
    set_setting(core.db, _setting(workspace_id), {"sealed": sealed, "last4": value[-4:]})


def forget(core: Core, workspace_id: str) -> None:
    delete_setting(core.db, _setting(workspace_id))


def clean(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 500 or any(c.isspace() for c in value):
        raise ActionError("Paste the key on one line.")
    return value


_catalog: dict[str, tuple[float, list[ComposioToolkit]]] = {}
_catalog_lock = threading.Lock()
_catalog_fetch = threading.Lock()  # one fetch of Composio's list at a time
fetch_toolkits = cz.toolkits  # tests replace this


fetch_auth_configs = cz.auth_config_toolkits  # tests replace this

# Each project's own logins (Composio → Auth Configs: the picker's ready marks), per
# core and key. Composio is asked over the network (0.3-2 s) and the owner sets a
# login up in Composio's dashboard: the picker gets the last answer at once and
# Composio is asked again behind it each half minute; AGOS's own Set up asks at once
# (`forget_own`). A new key is a new entry (never the old project's list).
_OWN: dict[int, read_cache.ReadCache[frozenset[str]]] = {}
_OWN_LOCK = threading.Lock()


def _own_cache(core: Core) -> read_cache.ReadCache[frozenset[str]]:
    with _OWN_LOCK:
        found = _OWN.get(id(core))
        if found is None:
            found = _OWN[id(core)] = read_cache.ReadCache("composio_auth_configs", max_entries=64)
            weakref.finalize(core, _OWN.pop, id(core), None)
        return found


def _own(core: Core, workspace_id: str, value: str) -> frozenset[str]:
    """The apps this workspace's project has its own login for ({} when Composio
    didn't answer and nothing was kept)."""

    def ask() -> frozenset[str]:
        return frozenset(fetch_auth_configs(value))

    key = (workspace_id, hashlib.sha256(value.encode()).hexdigest())
    try:
        return _own_cache(core).get(key, int(time.time() // 30), ask, stale_ok=True)
    except cz.ComposioError:
        return frozenset()


def forget_own(core: Core, workspace_id: str) -> None:
    """AGOS set a login up in this workspace's project: the next view asks Composio."""
    kept = _own_cache(core)
    for key in [k for k in kept._entries if isinstance(k, tuple) and k[0] == workspace_id]:
        kept.drop(key)


def catalog(core: Core, workspace_id: str) -> list[ComposioToolkit]:
    """Composio's app list (logos, names), read once a day (it is Composio's, the
    same for every project). An app this workspace's project has its own login for
    (Auth Configs in Composio) is ready here too."""
    value = key(core, workspace_id)
    if not value:
        raise ActionError("Add this workspace's Composio key first.", 409)
    own = _own(core, workspace_id, value)
    return [t.model_copy(update={"ready": True}) if t.slug in own else t for t in _all(value)]


def _all(value: str) -> list[ComposioToolkit]:
    """Composio's app list, kept a day. After that the page gets the last list at
    once and Composio is asked again behind it; only the very first ask waits (the
    read-ahead after start usually made it), and callers together share one fetch."""
    with _catalog_lock:
        cached = _catalog.get("all")
    if cached is not None:
        if time.monotonic() - cached[0] >= CATALOG_TTL_S and _catalog_fetch.acquire(blocking=False):
            read_cache.submit(lambda: _fetch_behind(value))
        return cached[1]
    with _catalog_fetch:
        with _catalog_lock:
            cached = _catalog.get("all")
        if cached is not None:
            return cached[1]  # fetched by the caller this one waited for
        return _fetch(value)


def _fetch_behind(value: str) -> None:
    """A day-old list fetched again (the fetch lock is held by the caller)."""
    try:
        _fetch(value)
    except ActionError as error:
        log.info("Composio's app list not read again: %s", error)
    finally:
        _catalog_fetch.release()


def _fetch(value: str) -> list[ComposioToolkit]:
    try:
        found = fetch_toolkits(value)
    except cz.ComposioError as error:
        raise ActionError(str(error), 502) from error
    items = [
        ComposioToolkit(
            slug=t.slug,
            name=t.name,
            description=t.description,
            logo=t.logo,
            categories=list(t.categories),
            ready=t.ready,
        )
        for t in found
    ]
    with _catalog_lock:
        _catalog["all"] = (time.monotonic(), items)
    return items


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): Composio's app list, with the
    first workspace's key that has one (it is the same list for every project), and
    each workspace's own logins (the picker's ready marks)."""
    from agos_core.db.workspaces import list_workspaces

    for w in list_workspaces(core.db):
        value = key(core, w.id)
        if not value:
            continue
        with _catalog_lock:
            listed = "all" in _catalog
        if not listed:
            try:
                _all(value)
            except ActionError as error:
                log.info("Composio's app list not read ahead: %s", error)
        _own(core, w.id, value)
