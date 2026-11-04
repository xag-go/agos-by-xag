"""Reading the Hermes settings page: the cached read, the read-ahead and the warm-up after a write.
Must not: write a setting.

Split out of agos_core.actions.hermes_all_settings (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from agos_core.actions.services.settings.hermes_policy import card_keys, choice_keys, forced_keys
from agos_core.actions.services.settings.hermes_rows import (
    _PROBES,
    _env_rows,
    _explain_member_toolsets,
    _note_no_checkpoints,
    _pair_models,
    _row,
    _seeded,
    _with_partner,
    shared_rows,
)
from agos_core.actions.services.settings.hermes_targets import (
    Target,
    _as_hermes_reads,
    _schema,
    _secrets,
    _uncovered,
    log,
    targets,
)
from agos_core.context import Core
from agos_core.engine import hermes_schema as hs
from agos_core.engine.hermes import EngineError

__all__ = [
    "read",
    "read_ahead",
    "warm_after_write",
]


def read(core: Core, only: str | None = None) -> dict[str, Any]:
    """Every Hermes setting with its value in each workspace (differences shown).
    `only`: just that config setting's row (and its model-picker partner), for a
    save: the other rows, the .env rows (each profile's .env probe) and the shared
    home's rows are not read."""
    fields = _schema(core)
    every = targets(core)
    if only is not None:
        return _read(core, fields, every, only, None)
    ahead = _ask_ahead(core, every)
    try:
        found = _read(core, fields, every, None, ahead[1])
    finally:
        ahead[0].shutdown(wait=False, cancel_futures=True)
    _read_once.add(core.engine)
    return found


# The engines whose page was read (by a view or the read-ahead): what a warm-up after
# a write refreshes. Before that nothing is kept, and the start's read-ahead fills it.
_read_once: weakref.WeakSet[Any] = weakref.WeakSet()
# The engines with a warm-up waiting to start (writes in a row ask for one).
_warm_waiting: weakref.WeakSet[Any] = weakref.WeakSet()
_warm_lock = threading.Lock()


def warm_after_write(core: Core) -> None:
    """After AGOS's own write that changes what the page reads (a managed-scope
    write, a row save, a workspace's Hermes settings card, a key save): the page's
    Hermes asks again right after it, in the background (the read cache's
    low-priority threads, read_ahead's at most four Hermes processes at once), so
    the next view is ready. Hermes stays the source: each ask is kept under the
    stamp of the files it read, so a change made outside AGOS is still asked at the
    next view. One waiting at a time; a write while one runs asks for one more."""
    from agos_core.engine import read_cache

    engine = core.engine
    if engine is None or engine not in _read_once:
        return
    with _warm_lock:
        if engine in _warm_waiting:
            return
        _warm_waiting.add(engine)

    def run() -> None:
        with _warm_lock:
            _warm_waiting.discard(engine)
        read_ahead(core)

    read_cache.submit(run)


def _ask_ahead(
    core: Core, every: list[Target]
) -> tuple[ThreadPoolExecutor, dict[str, Future[dict[str, Any]]]]:
    """The page's Hermes asks that don't depend on each other, started together:
    every profile as Hermes reads it (one run), the shared home's masker (one run)
    and each profile's .env probe (two runs each, themselves side by side). They used
    to run one after the other; now the page waits for the longest only. Each fills
    the engine's read cache, where the page's own ask finds it kept or joins the run
    (one Hermes start per ask either way); at most four Hermes processes at once, as
    before (the engine's SETTINGS_RUNS, whoever asks). Returns the pool and each
    profile's probe."""
    engine = core.engine
    assert engine is not None
    homes = [engine.profile_home(t.key) for t in every]
    pool = ThreadPoolExecutor(max_workers=_PROBES, thread_name_prefix="agos-hermes-settings")

    def quietly(ask: Callable[[], object]) -> None:
        try:
            ask()
        except (EngineError, OSError, ValueError) as error:  # the page's own ask says why
            log.info("Hermes's settings not asked ahead: %s", error)

    pool.submit(quietly, lambda: engine.as_hermes_reads(homes))
    shared = [engine.settings.hermes_home, engine.settings.managed_home]
    pool.submit(quietly, lambda: engine.hermes_secrets(shared))
    probes = {
        t.key: pool.submit(engine.env_in_use, home) for t, home in zip(every, homes, strict=True)
    }
    return pool, probes


def _read(
    core: Core,
    fields: list[hs.Field],
    every: list[Target],
    only: str | None,
    probes: dict[str, Future[dict[str, Any]]] | None,
) -> dict[str, Any]:
    from agos_core.actions import hermes_managed

    configs = _as_hermes_reads(core, every)
    engine = core.engine
    assert engine is not None
    secrets = _secrets(core, {t.key: engine.profile_home(t.key) for t in every})
    source = hs.source_path()
    if source is not None:
        # Keys Hermes's Telegram adapter reads that its lists don't hold (found in its
        # own source: engine/hermes_schema.py platform_extras).
        fields += hs.extra_fields(hs.hermes_root(source), {f.key for f in fields})
    known = {f.key for f in fields}
    forced = forced_keys(core)
    cards = card_keys()
    seeded = _seeded()
    choices = choice_keys()
    extras: dict[str, Any] = {}
    for key in sorted(forced | set(cards) | set(choices)):
        if key not in known and not key.isupper():
            extras.setdefault(key, None)
    for config in configs.values():
        for key, value in _uncovered(config, known | set(extras)).items():
            extras.setdefault(key, value)
    hidden = set().union(*secrets.values()) if secrets else set()
    fields += [hs.unlisted(k, v, secret=tuple(k.split(".")) in hidden) for k, v in extras.items()]
    rows = []
    wanted = None if only is None else _with_partner(only)
    for field in fields:
        if wanted is None or field.key in wanted:
            rows.append(_row(field, every, configs, forced, cards, seeded, choices, secrets))
    _pair_models(rows)
    _explain_member_toolsets(core, rows, every, configs)
    _note_no_checkpoints(rows)
    if only is None:
        rows += _env_rows(core, every, configs, rows, cards, probes)
    return {
        "profiles": len(every),
        "workspaces": len({t.workspace_id for t in every}),
        "groups": list(hs.GROUPS),
        "not_used_why": hs.NOT_USED_WHY,
        "settings": rows,
        "shared_home": str(core.engine.settings.hermes_home),  # type: ignore[union-attr]
        "shared": shared_rows(core, hermes_managed.current(core)) if only is None else [],
    }


def _one_row(core: Core, key: str) -> dict[str, Any] | None:
    """The page's row of one setting, as read() builds it: a config setting reads
    only its own row; a .env name (or a key read() alone finds) the whole page."""
    rows: list[dict[str, Any]] = []
    if not key.isupper():
        rows = [r for r in read(core, only=key)["settings"] if r["key"] == key]
    if not rows:
        rows = [r for r in read(core)["settings"] if r["key"] == key]
    return rows[0] if rows else None


def read_ahead(core: Core) -> None:
    """What the page asks Hermes, asked after the core starts (engine/read_ahead.py):
    Hermes's settings list, then every profile as Hermes reads it, the shared home's
    secret paths and each profile's .env probe side by side (at most four Hermes
    processes at once), each run to its end, then the page's own read (finding them
    all kept). The read-ahead's thread is low priority, and so is every thread and
    Hermes process it starts. Everything stays in the engine's memory under the
    files' stamps."""
    if core.engine is None:
        return
    _schema(core)
    pool, _probes = _ask_ahead(core, targets(core))
    pool.shutdown(wait=True)
    read(core)
