"""The settings that are ONE value for every workspace live in Hermes's own Managed
Scope: one `config.yaml` that every Hermes process AGOS runs reads.

General settings' Fallback models, Loop detector & limits (loop guard, run budget,
Kanban's `max_in_progress`), Time limits (every config.yaml timeout) and Your
timezone are the owner's one choice for every
workspace. Hermes reads a managed `config.yaml` on top of each profile's own
(hermes_cli/managed_scope.py `apply_managed_overlay`, leaf by leaf), in every
behavioural read: `load_config` (hermes_cli/config.py `_load_config_impl`, its cache
keyed on the managed file's signature too, `_load_config_cache_sig`) and
`load_user_config_effective` (hermes_cli/config_effective.py, the gateway's and
hermes_time.py's reader). So a change is read at the next turn, cron tick or
Kanban dispatch, like a profile's own config.yaml (checked in v0.22.2 by editing
the managed file under one running process). The folder is per process
(`HERMES_MANAGED_DIR`, managed_scope.py `get_managed_dir`): AGOS gives it to every
Hermes process it runs (engine/hermes.py `_env`, `child_env`) and to each gateway's
systemd unit (its drop-in), like HERMES_RUNTIME_DIR; a gateway's Kanban workers,
cron runs and subagents inherit it.

Hermes's own `hermes config set/unset` writes the file (engine/hermes.py
`managed_write`). While the scope pins a key Hermes refuses to set it in a
profile (hermes_cli/config.py `_exit_if_key_managed`), so no per-workspace copy
can come back; the Hermes settings page shows these keys read-only (their card).

Moving in (`move_once`, at every core start, a no-op once done): each key the
managed file doesn't have yet takes the value the profiles have (they were all
written together; the most common one when they differ, the others logged), or
AGOS's default (Time limits; voice notes off), or stays Hermes's default. `settle` then keeps
or removes the profiles' copies: a gateway started before AGOS gave it the scope
still reads its profiles' own config.yaml, so its copies are kept equal to the
managed values until it next starts; every other copy is removed (Hermes's
`config unset`, run without the scope). The shared home's `timezone` too.

An UPPER_SNAKE key (the one .env time limit, TERMINAL_MAX_FOREGROUND_TIMEOUT) is the
scope's `.env` (Hermes's `config set` sends it to its .env writer); Hermes applies
the managed `.env` over each profile's, with override (hermes_cli/env_loader.py
`_apply_managed_env`, and per routed turn tools/environments/local.py
`restore_managed_env`). Hermes's own writer also mirrors `terminal.timeout` into
`TERMINAL_TIMEOUT` there (hermes_cli/config.py set_config_value), so the
env-driven terminal tool gets the managed value even where a profile's .env still
has an old line.

How Hermes picks among a provider's keys (`credential_pool_strategies`) is here
too, and the extra keys themselves are numbered lines of the scope's `.env`
(actions/key_pools.py). Not here, with their reason: the provider keys from
General Settings (.env copies, actions/general_sync.py: a workspace's own key must
win, and a managed name can't be set per profile) and tool services
(actions/tool_services.py: Hermes's selection is per home).
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.hermes_managed")

_MISSING = object()


@functools.cache
def by_card() -> dict[str, str]:
    """Every managed key → the General settings card that changes it."""
    from agos_core.actions import hermes_limits, key_pools, owner_time
    from agos_core.engine import fallback, stt, time_limits

    out: dict[str, str] = {}
    for key, _value in hermes_limits._pairs(hermes_limits.Limits()):
        out[key] = "limits"
    out[fallback.KEY] = "fallback"
    for limit in time_limits.TIME_LIMITS:
        out[limit.key] = "time-limits"  # an UPPER_SNAKE one is the scope's .env
    out[owner_time.CONFIG_KEY] = "timezone"
    out[key_pools.STRATEGY_KEY] = "pools"  # how Hermes picks among a provider's keys
    for key in stt.card_keys():  # who hears the voice notes: one provider + its model
        out[key] = "voice"
    return out


def _shared_too() -> tuple[str, ...]:
    """Managed keys General Settings also wrote into the shared home: its copy
    counts for the move and goes with the profiles' copies."""
    from agos_core.actions import key_pools
    from agos_core.actions.owner_time import CONFIG_KEY as ZONE

    return (ZONE, key_pools.STRATEGY_KEY)


def _legacy() -> tuple[str, ...]:
    """Keys a profile copy must lose with the managed ones: Hermes merges the legacy
    `fallback_model` after the chain (hermes_cli/fallback_config.py get_fallback_chain)."""
    from agos_core.engine import fallback

    return (fallback.LEGACY,)


def lookup(config: dict[str, Any], dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def view(home: Path) -> dict[str, Any]:
    """A Hermes home's managed keys as it holds them: its config.yaml, plus the
    UPPER_SNAKE ones from its .env (Hermes's `config set` sends those to the .env
    writer: hermes_cli/config.py set_config_value → save_env_setting)."""
    from agos_core.engine import config_file

    config = config_file.read(home)
    env = config_file.read_env(home)
    for key in by_card():
        if key.isupper() and env.get(key, "") != "":
            config[key] = env[key].strip().strip("\"'")
    return config


def has(config: dict[str, Any], dotted: str) -> bool:
    return lookup(config, dotted) is not _MISSING


def text(value: Any) -> str:
    """A value as `hermes config set` takes it (Hermes YAML-parses it back)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _same(have: Any, wanted: str) -> bool:
    """The managed file already holds this `hermes config set` text (Hermes parses
    it as YAML: hermes_cli/config.py _coerce_config_set_value)."""
    import yaml

    if have is _MISSING:
        return False
    try:
        parsed = yaml.safe_load(wanted) if wanted.strip() else wanted
    except yaml.YAMLError:
        parsed = wanted
    return _norm(have) == _norm(parsed) or (isinstance(have, str) and have == wanted)


def _norm(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def current(core: Core) -> dict[str, Any]:
    """The managed config.yaml ({} without Hermes)."""
    if core.engine is None:
        return {}
    return core.engine.managed_config()


def pinned(core: Core) -> dict[str, Any]:
    """Every managed key's value as the scope holds it (config.yaml and .env)."""
    if core.engine is None:
        return {}
    return view(core.engine.settings.managed_home)


def value(core: Core, key: str, default: Any = None) -> Any:
    found = lookup(current(core), key)
    return default if found is _MISSING else found


def write(core: Core, sets: dict[str, str], unsets: list[str] | tuple[str, ...] = ()) -> None:
    """Into the managed config.yaml (Hermes's own writer), then the profiles'
    copies follow (settle). Raises EngineError when Hermes didn't take it."""
    if core.engine is None:
        raise EngineError("Hermes isn't available")
    managed = pinned(core)
    changed = [(k, v) for k, v in sets.items() if not _same(lookup(managed, k), v)]
    gone = [k for k in unsets if has(managed, k)]
    if not changed and not unsets:
        return  # nothing changed: no profile copy can need settling either
    hermes_cli.managed_write(core.engine, changed, gone)
    settle(core, cleared=set(unsets))
    from agos_core.actions import hermes_all_settings

    hermes_all_settings.warm_after_write(core)  # Settings → Hermes settings reads it


# ---- moving in, once ---------------------------------------------------------


def _profile_value(config: dict[str, Any], key: str) -> Any:
    from agos_core.engine import fallback

    if key == fallback.KEY:
        if not fallback.is_set(config):
            return _MISSING
        # Hermes's merged chain (legacy fallback_model too); an inline api_key
        # stays in its own profile (it is never copied to another workspace).
        return [{k: v for k, v in e.items() if k != "api_key"} for e in fallback.chain_in(config)]
    return lookup(config, key)


def _defaults() -> dict[str, str]:
    from agos_core.engine import time_limits

    return time_limits.owner_defaults()


def _good_zone(value: Any) -> str:
    from agos_core.actions.owner_time import zone_of

    name = value.strip() if isinstance(value, str) else ""
    return name if zone_of(name) is not None else ""


def repair_zone(core: Core) -> list[str]:
    """A managed `timezone` Hermes rejects (an old move wrote the internal
    "missing" marker's repr, '<object object at 0x…>'; Hermes logs `Invalid
    timezone` and runs on the server's local time) becomes the shared home's zone,
    else is unset. Returns the keys written or unset. Safe to repeat."""
    from agos_core.actions.owner_time import CONFIG_KEY as ZONE
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return []
    have = lookup(view(engine.settings.managed_home), ZONE)
    if have is _MISSING or _good_zone(have):
        return []
    own = _good_zone(lookup(config_file.read(engine.settings.hermes_home), ZONE))
    log.warning("managed timezone %r isn't a zone Hermes reads: %s", have, own or "unset")
    if own:
        hermes_cli.managed_write(engine, [(ZONE, own)], [])
    else:
        hermes_cli.managed_write(engine, [], [ZONE])
        settle(core, cleared={ZONE})  # no profile copy keeps the bad value
    return [ZONE]


def _most_common(found: list[tuple[str, Any]], key: str) -> Any:
    """The value most profiles hold ({label: value} pairs), the others logged."""
    groups: dict[str, tuple[Any, list[str]]] = {}
    for label, value in found:
        groups.setdefault(_norm(value), (value, []))[1].append(label)
    if not groups:
        return _MISSING
    ordered = sorted(groups.values(), key=lambda g: -len(g[1]))
    if len(ordered) > 1:
        log.warning(
            "%s differed between workspaces; every one now uses %r (others: %s)",
            key,
            ordered[0][0],
            "; ".join(f"{g[0]!r} in {', '.join(g[1])}" for g in ordered[1:]),
        )
    return ordered[0][0]


def _voice_move(
    managed: dict[str, Any],
    every: list[tuple[str, dict[str, Any]]],
    fields: list[Any] | None = None,
) -> list[tuple[str, str]]:
    """Who hears the voice notes moves in as ONE provider + that provider's model
    (General settings → Voice notes): the provider most profiles chose, and the
    model most of them hold for it. None chose (a fresh install): voice notes stay
    off (`stt.enabled: false`) until the owner picks a provider. A scope that
    already holds a provider or the switch keeps it. Another provider's model
    never moves in (Fuel Machine's `stt.local.model`)."""
    from agos_core.engine import stt

    if has(managed, stt.PROVIDER_KEY) or has(managed, stt.ENABLED_KEY):
        return []
    chosen = [
        (label, str(value).strip())
        for label, config in every
        if isinstance(value := lookup(config, stt.PROVIDER_KEY), str)
        and str(value).strip() in stt.by_name(fields)
    ]
    provider = _most_common(chosen, stt.PROVIDER_KEY)
    if provider is _MISSING:
        return list(stt.DEFAULT_SETTINGS)
    out = [(stt.PROVIDER_KEY, str(provider))]
    key = stt.model_key(str(provider), fields)
    if key is None or has(managed, key):
        return out
    models = [
        (label, value.strip())
        for label, config in every
        if isinstance(value := lookup(config, key), str) and value.strip()
    ]
    model = _most_common(models, key)
    if model is not _MISSING:
        out.append((key, str(model)))
    return out


def move_once(core: Core) -> list[str]:
    """Each managed key the managed file doesn't hold yet gets the profiles' value
    (or AGOS's default). Returns the keys written. Safe to repeat."""
    from agos_core.actions.hermes_time_limits import profiles
    from agos_core.actions.owner_time import CONFIG_KEY as ZONE
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return []
    repaired = repair_zone(core)
    managed = view(engine.settings.managed_home)
    every = [(p.label, view(p.home)) for p in profiles(core)]
    shared = config_file.read(engine.settings.hermes_home)
    defaults = _defaults()
    from agos_core.engine import stt

    fields: list[Any] | None = None  # Hermes's voice providers and models (engine/stt.py)
    with contextlib.suppress(EngineError, OSError):
        fields = list(engine.config_schema())
    sets: list[tuple[str, str]] = _voice_move(managed, every, fields)
    voice = set(stt.card_keys(fields))
    for key in by_card():
        if has(managed, key) or key in repaired or key in voice:
            continue
        zone = _good_zone(lookup(shared, ZONE))
        if key == ZONE and zone:
            # General Settings kept the owner's zone in the shared home. (Never the
            # "missing" marker: its repr once landed in the managed file as a zone.)
            sets.append((key, zone))
            continue
        groups: dict[str, tuple[Any, list[str]]] = {}
        shared_copy = [("the shared home", shared)] if key in _shared_too() else []
        for label, config in [*every, *shared_copy]:
            found = _profile_value(config, key)
            if key == ZONE and found is not _MISSING and not _good_zone(found):
                continue  # a zone Hermes rejects is never moved in
            if found is not _MISSING and found != {}:  # an empty map holds nothing
                groups.setdefault(_norm(found), (found, []))[1].append(label)
        if groups:
            ordered = sorted(groups.values(), key=lambda g: -len(g[1]))
            if len(ordered) > 1:
                log.warning(
                    "%s differed between workspaces; every one now uses %r (others: %s)",
                    key,
                    ordered[0][0],
                    "; ".join(f"{g[0]!r} in {', '.join(g[1])}" for g in ordered[1:]),
                )
            sets.append((key, text(ordered[0][0])))
        elif key in defaults:
            sets.append((key, defaults[key]))
    if sets:
        hermes_cli.managed_write(engine, sets, [])
        log.info("one value for every workspace (Hermes's managed scope): %d setting(s)", len(sets))
    return [*repaired, *(k for k, _v in sets)]


# ---- the profiles' copies ----------------------------------------------------


def _commands(
    config: dict[str, Any], held: dict[str, Any], keep_copies: bool, cleared: set[str]
) -> list[list[str]]:
    """What one profile's copies need. A copy goes only when the managed file
    holds its key (or the owner just cleared it there): never the only value."""
    from agos_core.engine import fallback

    out: list[list[str]] = []
    for key in by_card():
        mine = lookup(config, key)
        if key in cleared:
            if mine is not _MISSING:
                out.append(["config", "unset", key])
        elif key not in held or (mine is _MISSING and not keep_copies):
            continue
        elif keep_copies:
            if mine is _MISSING or _norm(mine) != _norm(held[key]):
                out.append(["config", "set", "--force", key, text(held[key])])
        elif key == fallback.KEY and any("api_key" in e for e in fallback.entries(mine)):
            continue  # its own inline key stays in its file (the managed chain wins)
        else:
            out.append(["config", "unset", key])
    if fallback.KEY in held or fallback.KEY in cleared:
        for key in _legacy():
            if has(config, key):
                out.append(["config", "unset", key])
    return out


def settle(core: Core, cleared: set[str] | None = None) -> list[str]:
    """The profiles' copies of managed keys: kept equal to the managed values where
    the root's running gateway doesn't read the scope yet (started before AGOS gave
    it), removed everywhere else. Returns the profiles changed."""
    from agos_core.actions.hermes_time_limits import profiles
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return []
    managed = view(engine.settings.managed_home)
    pinned = {k: lookup(managed, k) for k in by_card() if has(managed, k)}
    every = profiles(core)
    roots = sorted({engine.split(p.key)[0] for p in every})
    for root in roots:
        engine.refresh_dropin(root)
    views = {p.key: view(p.home) for p in every}
    # Only a root with a profile whose copies would change asks whether its
    # gateway reads the scope (Hermes's gateway status: one runtime start per
    # root), and those roots are asked side by side.
    asked = sorted(
        {
            engine.split(p.key)[0]
            for p in every
            if any(
                _commands(views[p.key], pinned, keep, cleared or set()) for keep in (True, False)
            )
        }
    )
    switched: dict[str, bool] = {}

    def verdict(root: str) -> None:
        # None (not running): its next start carries the scope (drop-in / spawn env).
        switched[root] = engine.gateway_managed(root) is not False

    if asked:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(asked))) as pool:
            list(pool.map(verdict, asked))
    changed: list[str] = []
    for profile in every:
        root = engine.split(profile.key)[0]
        if root not in switched:
            continue
        commands = _commands(views[profile.key], pinned, not switched[root], cleared or set())
        if not commands:
            continue
        try:
            hermes_cli.unmanaged_writes(engine, profile.key, commands)
            changed.append(profile.key)
        except (EngineError, OSError) as error:
            log.warning("managed settings' copies in %s not settled: %s", profile.key, error)
    shared = engine.settings.hermes_home
    held = config_file.read(shared)
    for key in _shared_too():
        if has(held, key) and (key in pinned or key in (cleared or set())):
            try:
                hermes_cli.unmanaged_in(engine, shared, "config", "unset", key)
            except (EngineError, OSError) as error:
                log.warning("the shared home's %s copy not removed: %s", key, error)
    if changed:
        log.info("managed settings' copies settled in %d profile(s)", len(changed))
    return changed


# Done-mark of the one move below (app_settings).
HOOK_GUARD_MOVED = "moved.hook_guard"


def move_hook_guard(core: Core) -> bool:
    """`plugins.hook_callback_timeout` was 0 (925047d: no hang guard for any plugin
    hook) only because the owner's yes under Full access waited inside agos-guard's
    pre_tool_call hook. That yes is now asked in its tool_execution middleware,
    which Hermes runs with no timeout, so the 0 moves once to Hermes's cap; his own
    later choice (No limit included) then stays. True when it moved."""
    from agos_core.db.app_settings import get_setting, set_setting
    from agos_core.engine.time_limits import HOOK_GUARD_SECONDS

    key = "plugins.hook_callback_timeout"
    if core.engine is None or get_setting(core.db, HOOK_GUARD_MOVED, None) is not None:
        return False
    found = lookup(pinned(core), key)
    moved = found is not _MISSING and str(found).strip() in ("0", "0.0")
    if moved:
        hermes_cli.managed_write(core.engine, [(key, str(HOOK_GUARD_SECONDS))], [])
        log.info("%s: Hermes's hang guard back at its cap (%d s)", key, HOOK_GUARD_SECONDS)
    set_setting(core.db, HOOK_GUARD_MOVED, True)
    return moved


def at_start(core: Core) -> None:
    """Core start: move in once, then settle the copies."""
    try:
        move_hook_guard(core)
    except (EngineError, OSError) as error:
        log.warning("plugins.hook_callback_timeout not moved: %s", error)
    move_once(core)
    settle(core)
    from agos_core.actions import catch_up

    try:
        catch_up.pin_hermes(core)  # a missed run is AGOS's per automation, not Hermes's
    except (EngineError, OSError) as error:
        log.warning("cron.catch_up_missed not pinned: %s", error)
