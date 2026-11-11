"""Settings → Models → Several keys per provider: Hermes's own credential pool.

Hermes rotates between several keys of one provider (agent/credential_pool.py). AGOS
keeps nothing of it and copies nothing into the homes:

- The extra keys are numbered lines of Hermes's managed `.env` (`<VAR>_2`,
  `<VAR>_3`…, written by Hermes's own `.env` writer: engine/hermes.py
  `managed_keys`). Hermes turns each into a pool entry in every home by itself
  (`_env_key_var_candidates` / `_seed_from_env`; the managed `.env` reaches every
  process through `_apply_managed_env` and every gateway turn's secret scope,
  agent/secret_scope.py `build_profile_secret_scope`), new workspaces included. A
  workspace's own line of the same name wins there (`get_env_prefer_dotenv`: the
  profile's `.env` first), as its own keys always did.
- How Hermes picks among them (`credential_pool_strategies.<provider>`, read through
  `load_config_readonly`, managed overlay included) is one line of the managed
  `config.yaml` (actions/hermes_managed.py).
- The list is the shared home's pool as Hermes has it (its dashboard's redacted
  list, after Hermes's own `.env` load); each entry's status is the newest Hermes
  recorded in any home's pool (read with Hermes's read_credential_pool:
  engine.hermes_logins; AGOS never opens auth.json).
- Under it, each workspace's own pool as its root's Hermes has it, read in that
  root (`per_workspace`: Hermes's load_pool there, what `hermes auth list` lists;
  a workspace's own keys and sign-ins included). Read only.

Keys AGOS once added to every home's auth.json by hand ("manual" rows) move into
the managed `.env` once (`move_once`, at each core start until done).

Every Hermes answer the page needs is kept in memory per home (`_LISTS`,
`_STATUSES`): one Hermes run per home and none while what Hermes reads holds. A
change of a home's .env/config.yaml or of the managed scope (a save anywhere in
AGOS) asks Hermes again before the page shows; Hermes rewrites a home's auth.json
itself as its keys are used (counts, statuses), and the page then shows the last
list at once while Hermes is asked again behind it (AGOS only hashes the file).
"""

from __future__ import annotations

import copy
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine import read_cache
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.key_pools")

STRATEGY_KEY = "credential_pool_strategies"  # Hermes's key: <provider> → strategy
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
_NUMBERED = re.compile(r"^([A-Z][A-Z0-9_]*)_([0-9]+)$")
# A home's pool as Hermes lists it (key: the home and what its settings files hold),
# and the statuses Hermes recorded in it (key: the home).
_LISTS: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache(
    "key_pool_lists", max_entries=256
)
_STATUSES: read_cache.ReadCache[list[dict[str, Any]]] = read_cache.ReadCache(
    "key_pool_statuses", max_entries=256
)
# Some entries come from outside the home (a sign-in Hermes borrows): asked again
# behind the page at least this often.
_RECHECK_S = 300


def _settings(core: Core, home: Path) -> str:
    """What the home's .env and config.yaml and the managed scope hold."""
    managed = core.engine.settings.managed_home if core.engine is not None else home
    return read_cache.content_stamp(
        home / ".env", home / "config.yaml", managed / ".env", managed / "config.yaml"
    )


def _used(home: Path) -> tuple[str, int]:
    """What Hermes rewrites as it uses the keys (and the time bucket above)."""
    return read_cache.content_stamp(home / "auth.json"), int(time.time() // _RECHECK_S)


def _listed(core: Core, home: Path, *, kept: bool) -> dict[str, Any]:
    """Hermes's redacted pool list of one home (`kept`: the page, which may get the
    last list at once when only auth.json moved)."""
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    return copy.deepcopy(
        _LISTS.get(
            (str(home), _settings(core, home)),
            _used(home),
            lambda: engine.credential_pool(home, {"do": "list"}),
            stale_ok=kept,
        )
    )


def _home_statuses(core: Core, home: Path, *, kept: bool) -> list[dict[str, Any]]:
    """The pool entries Hermes recorded in one home, with their statuses ([] when
    Hermes couldn't read them)."""
    from agos_core.actions import general_sync

    engine = core.engine
    if engine is None:
        return []

    def ask() -> list[dict[str, Any]]:
        found = general_sync.hermes_logins(engine, home)
        if found is None:
            raise EngineError(f"The engine's logins in {home} not read")
        return list(found.get("pool") or [])

    try:
        return _STATUSES.get(str(home), (_settings(core, home), _used(home)), ask, stale_ok=kept)
    except EngineError:
        return []


def homes(core: Core) -> list[Path]:
    from agos_core.actions import general_sync

    engine = core.engine
    if engine is None:
        return []
    return [engine.settings.hermes_home, *(home for _ws, home in general_sync.homes(core))]


def _statuses(
    core: Core, all_homes: list[Path], *, kept: bool = False
) -> dict[tuple[str, str], dict[str, Any]]:
    """(provider, label) → the newest status Hermes recorded in any home."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not all_homes:
        return out
    with ThreadPoolExecutor(max_workers=min(4, len(all_homes))) as pool:
        found = list(pool.map(lambda h: _home_statuses(core, h, kept=kept), all_homes))
    for entries in found:
        for e in entries:
            if not e.get("last_status"):
                continue
            key = (str(e.get("provider") or ""), str(e.get("label") or ""))
            at = str(e.get("last_status_at") or "")
            if key not in out or at > out[key]["at"]:
                problem = str(e.get("last_error_message") or e.get("last_error_reason") or "")
                out[key] = {
                    "status": str(e.get("last_status") or ""),
                    "at": at,
                    "problem": "" if e.get("last_status") == "ok" else problem[:300],
                }
    return out


def _managed_names(core: Core) -> set[str]:
    """The names the managed .env holds (never their values)."""
    from agos_core.engine import config_file

    if core.engine is None:
        return set()
    return set(config_file.read_env(core.engine.settings.managed_home))


def _ours(source: str, managed: set[str]) -> str | None:
    """The managed .env name behind an entry AGOS added here (`env:<VAR>_<n>`)."""
    name = source.split(":", 1)[1] if source.startswith("env:") else ""
    return name if name in managed and _NUMBERED.match(name) else None


def _view(core: Core, found: dict[str, Any], *, kept: bool = False) -> dict[str, Any]:
    status = _statuses(core, homes(core), kept=kept)
    managed = _managed_names(core)
    providers = []
    for p in (found.get("pool") or {}).get("providers") or []:
        provider = str(p.get("provider") or "")
        entries = []
        for e in p.get("entries") or []:
            label = str(e.get("label") or "")
            source = str(e.get("source") or "")
            if source.startswith("env:") and not e.get("token_preview"):
                # A row whose .env line is gone: Hermes leaves it out of rotation
                # (agent/credential_pool.py _available_entries: no key, never leased).
                continue
            seen = status.get((provider, label), {})
            ours = _ours(source, managed)
            entries.append(
                {
                    "label": label,
                    "authType": str(e.get("auth_type") or ""),
                    "source": "manual" if ours else source,
                    "priority": int(e.get("priority") or 0),
                    "preview": str(e.get("token_preview") or ""),
                    "requests": int(e.get("request_count") or 0),
                    "status": str(seen.get("status") or e.get("last_status") or ""),
                    "statusAt": str(seen.get("at") or ""),
                    "problem": str(seen.get("problem") or ""),
                    # AGOS changes only the keys added here (the managed .env's
                    # numbered lines, or an old hand-added copy); a key from General
                    # Settings or a sign-in is changed where it was made.
                    "removable": bool(ours)
                    or (source == "manual" and str(e.get("auth_type")) == "api_key"),
                    "movable": bool(ours),
                }
            )
        providers.append(
            {
                "provider": provider,
                "strategy": str((found.get("strategy") or {}).get(provider) or "fill_first"),
                "entries": entries,
            }
        )
    return {"providers": providers, "strategies": list(found.get("strategies") or [])}


def _pool(core: Core, job: dict[str, Any], *, kept: bool = False) -> dict[str, Any]:
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    try:
        if job == {"do": "list"}:
            return _listed(core, engine.settings.hermes_home, kept=kept)
        return engine.credential_pool(engine.settings.hermes_home, job)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine's key pool couldn't be read: {error}", status=502) from error


def _root_pool(core: Core, workspace_id: str, name: str, *, kept: bool = False) -> dict[str, Any]:
    """One workspace's pool as its root's Hermes has it (read in that root: Hermes's
    load_pool, the root's own .env keys and sign-ins included, the same list as
    `hermes auth list` there). Read only; a root that can't be read says why."""
    out: dict[str, Any] = {
        "workspace_id": workspace_id,
        "name": name,
        "providers": [],
        "problem": "",
    }
    engine = core.engine
    if engine is None:
        return out
    try:
        found = _listed(core, engine.profile_home(workspace_id), kept=kept)
    except (EngineError, OSError, ValueError) as error:
        out["problem"] = f"The engine's key pool couldn't be read here: {error}"[:300]
        return out
    for p in (found.get("pool") or {}).get("providers") or []:
        entries = [
            {
                "label": str(e.get("label") or ""),
                "auth_type": str(e.get("auth_type") or ""),
                "source": str(e.get("source") or ""),
                "priority": int(e.get("priority") or 0),
                "preview": str(e.get("token_preview") or ""),
                "status": str(e.get("last_status") or ""),
            }
            for e in p.get("entries") or []
            # A row whose .env line is gone is out of Hermes's rotation (as _view).
            if not (str(e.get("source") or "").startswith("env:") and not e.get("token_preview"))
        ]
        if entries:
            out["providers"].append({"provider": str(p.get("provider") or ""), "entries": entries})
    return out


def per_workspace(core: Core, *, kept: bool = False) -> list[dict[str, Any]]:
    """Every workspace's own pool, read in its root (in parallel: one Hermes runtime
    each, none while its files hold)."""
    from agos_core.db.workspaces import list_workspaces

    if core.engine is None:
        return []
    found = [(w.id, w.name) for w in list_workspaces(core.db)]
    if not found:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(found))) as pool:
        return list(pool.map(lambda w: _root_pool(core, *w, kept=kept), found))


def read(core: Core, *, kept: bool = False) -> dict[str, Any]:
    """The page. `kept`: the page itself (the last lists at once where only what
    Hermes rewrites as it uses the keys moved); after a save, never."""
    return {
        **_view(core, _pool(core, {"do": "list"}, kept=kept), kept=kept),
        "workspaces": per_workspace(core, kept=kept),
    }


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): each home's statuses and each
    list the page shows, one Hermes run at a time."""
    from agos_core.db.workspaces import list_workspaces

    engine = core.engine
    if engine is None:
        return
    for home in homes(core):
        _home_statuses(core, home, kept=False)
    roots = [engine.profile_home(w.id) for w in list_workspaces(core.db)]
    for home in [engine.settings.hermes_home, *roots]:
        try:
            _listed(core, home, kept=False)
        except (ActionError, EngineError, OSError, ValueError) as error:
            log.info("the key pool of %s not read ahead: %s", home, error)


def _keys(core: Core, job: dict[str, Any]) -> dict[str, Any]:
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    try:
        done = engine.managed_keys(job)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine didn't take it: {error}", status=502) from error
    from agos_core.actions import hermes_all_settings

    hermes_all_settings.warm_after_write(core)  # the managed .env: its .env rows
    return done


def _check(provider: str) -> str:
    provider = provider.strip().lower()
    if not _PROVIDER.match(provider):
        raise ActionError("Pick one of the engine's providers.")
    return provider


def _entry(
    found: dict[str, Any], provider: str, label: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    for p in found["providers"]:
        if p["provider"] == provider:
            for e in p["entries"]:
                if e["label"] == label:
                    return dict(e), list(p["entries"])
    raise ActionError("No such key in the engine's pool.", status=404)


def add(core: Core, provider: str, key: str, *, at: int | None = None) -> dict[str, Any]:
    """One more key for every workspace: the next numbered line of the managed .env
    (`at`: that number instead, the later ones move down one; an Undo of `remove`).
    The result's "label" is the line's name."""
    from agos_core.engine.provider_keys import KeyProblem, clean_key

    provider = _check(provider)
    try:
        key = clean_key(key)
    except KeyProblem as error:
        raise ActionError(str(error), status=422) from error
    base = (_pool(core, {"do": "list", "providers": [provider]}).get("bases") or {}).get(provider)
    if not base:
        raise ActionError(
            "The engine reads several keys only for providers that take an API key from "
            ".env; this one signs in or has its own endpoint settings.",
            status=422,
        )
    job: dict[str, Any] = {"do": "add", "base": base, "key": key}
    if at is not None:
        job["at"] = int(at)
    done = _keys(core, job)
    return {**read(core), "label": str(done.get("name") or "")}


def remove(
    core: Core, provider: str, label: str, *, kept: dict[str, Any] | None = None
) -> dict[str, Any]:
    """`kept`: filled with the removed key and its place, for an Undo (the caller
    seals the key at once)."""
    provider = _check(provider)
    entry, _entries = _entry(read(core), provider, label)
    if not entry["removable"]:
        raise ActionError(
            "This key comes from Settings → Models (or a sign-in): remove it there.", status=409
        )
    numbered = _NUMBERED.match(label)
    if numbered and label in _managed_names(core):
        if kept is not None:
            # The key and its number, for an Undo (the caller seals it at once).
            from agos_core.engine import config_file

            assert core.engine is not None
            value = config_file.read_env(core.engine.settings.managed_home).get(label)
            if value:
                kept.update({"key": value, "at": int(numbered[2])})
        # The later keys move up one number (Hermes reads <VAR>_2.. until a gap).
        _keys(core, {"do": "remove", "base": numbered[1], "n": int(numbered[2])})
        return read(core)
    return _everywhere(core, {"do": "remove", "provider": provider, "label": label})


def entry(core: Core, provider: str, label: str) -> dict[str, Any]:
    """One key of the pool as Hermes lists it (no secret)."""
    return _entry(read(core), _check(provider), label)[0]


def strategy_set(core: Core, provider: str) -> str | None:
    """The managed config.yaml's `credential_pool_strategies.<provider>` (None:
    unset, Hermes's default)."""
    from agos_core.actions import hermes_managed
    from agos_core.engine import config_file

    found = config_file.get(hermes_managed.current(core), f"{STRATEGY_KEY}.{_check(provider)}")
    return None if found in (None, "") else str(found)


def _everywhere(core: Core, job: dict[str, Any]) -> dict[str, Any]:
    """Only to take away an old hand-added copy (one of a provider Hermes reads no
    .env key for, which therefore could not move into the managed .env)."""
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    failed: list[str] = []

    def one(home: Path) -> None:
        try:
            engine.credential_pool(home, job)
        except (EngineError, OSError, ValueError) as error:
            log.warning("key pool not changed in %s: %s", home, error)
            failed.append(f"{home.name}: {error}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, homes(core)))
    if failed:
        raise ActionError(f"The engine didn't take it in {'; '.join(failed)}", status=502)
    return read(core)


def move(core: Core, provider: str, label: str, priority: int) -> dict[str, Any]:
    """Up/down among the keys added here: they swap numbers (Hermes tries <VAR>_2
    before <VAR>_3)."""
    provider = _check(provider)
    _found, entries = _entry(read(core), provider, label)
    if priority < 0 or priority >= len(entries):
        raise ActionError("Use a place in the list.")
    other = str(entries[priority]["label"])
    a, b = _NUMBERED.match(label), _NUMBERED.match(other)
    managed = _managed_names(core)
    if not (a and b) or a[1] != b[1] or not {label, other} <= managed:
        raise ActionError(
            "Only the keys added here change places, among themselves; the engine tries "
            "Settings → Models' key and sign-ins first.",
            status=409,
        )
    if label != other:
        _keys(core, {"do": "swap", "base": a[1], "n": [int(a[2]), int(b[2])]})
    return {**read(core), "swapped": [label, other]}


def swap(core: Core, provider: str, label: str, other: str) -> dict[str, Any]:
    """Two keys added here trade numbers (an Undo of `move`)."""
    _check(provider)
    a, b = _NUMBERED.match(label), _NUMBERED.match(other)
    if not (a and b) or a[1] != b[1] or not {label, other} <= _managed_names(core):
        raise ActionError("Those keys aren't both in the pool any more.", status=409)
    if label != other:
        _keys(core, {"do": "swap", "base": a[1], "n": [int(a[2]), int(b[2])]})
    return read(core)


def set_strategy(core: Core, provider: str, strategy: str | None) -> dict[str, Any]:
    """How Hermes picks among the keys (`credential_pool_strategies.<provider>`):
    one line of Hermes's managed config.yaml, for every workspace (None: Hermes's
    own `config unset`, back to its default)."""
    from agos_core.actions import hermes_managed

    provider = _check(provider)
    found = read(core)
    if strategy is not None and strategy not in found["strategies"]:
        raise ActionError(f"Choose one of: {', '.join(found['strategies'])}.")
    name = f"{STRATEGY_KEY}.{provider}"
    try:
        if strategy is None:
            hermes_managed.write(core, {}, [name])
        else:
            hermes_managed.write(core, {name: strategy})
    except (EngineError, OSError) as error:
        raise ActionError(f"The engine didn't take it: {error}", status=502) from error
    return read(core)


# ---- moving in, once ---------------------------------------------------------


def _manual_in(core: Core, home: Path) -> set[str]:
    """Providers whose pool in this home holds a hand-added API key (Hermes's
    read of its pool)."""
    from agos_core.actions import general_sync

    [entries] = general_sync.pools(core, [home]) or [[]]
    return {
        str(e.get("provider") or "")
        for e in entries
        if e.get("source") == "manual" and e.get("auth_type") == "api_key"
    }


def move_once(core: Core) -> int:
    """The keys AGOS once added by hand to every home's auth.json: into the managed
    .env (numbered lines), then out of each home whose root's gateway reads the
    managed scope; the shared home's copies go last (they are what the move reads).
    Keys of a provider Hermes reads no .env key for stay where they are. Safe to
    repeat; returns how many keys the managed .env holds from the move."""
    from agos_core.actions import general_sync

    engine = core.engine
    if engine is None:
        return 0
    shared = engine.settings.hermes_home
    if not _manual_in(core, shared):
        return 0
    found = engine.credential_pool(shared, {"do": "manual"})
    if found.get("error"):
        raise EngineError(str(found["error"])[:300])
    bases = found.get("bases") or {}
    moved: dict[str, list[str]] = {}
    for provider, keys in (found.get("manual") or {}).items():
        base = bases.get(provider)
        if not base or not keys:
            continue
        for item in keys:
            engine.managed_keys({"do": "add", "base": base, "key": item["key"]})
        moved[provider] = [str(item["fp"]) for item in keys]
    if not moved:
        return 0
    count = sum(len(fps) for fps in moved.values())
    log.info("several keys per provider: %d key(s) in Hermes's managed .env", count)
    done = True
    switched: dict[str, bool] = {}
    for key, home in general_sync.homes(core):
        root = engine.split(key)[0]
        if root not in switched:
            # A gateway started before AGOS gave it the scope keeps its copies until
            # its next start (hermes_managed.settle does the same).
            switched[root] = engine.gateway_managed(root) is not False
        providers = _manual_in(core, home) & set(moved)
        if not providers:
            continue
        if not switched[root]:
            done = False
            continue
        for provider in sorted(providers):
            try:
                engine.credential_pool(
                    home, {"do": "drop", "provider": provider, "fps": moved[provider]}
                )
            except (EngineError, OSError, ValueError) as error:
                log.warning("old key copies in %s not removed: %s", home, error)
                done = False
    if done:
        for provider in sorted(moved):
            engine.credential_pool(
                shared, {"do": "drop", "provider": provider, "fps": moved[provider]}
            )
    return count
