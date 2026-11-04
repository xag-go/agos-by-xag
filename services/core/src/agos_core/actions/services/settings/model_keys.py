"""Settings → Models: the providers' API keys (General Settings' own), saved in Hermes
after Hermes tested them, copied into every workspace's root, and each key's state
as Hermes's credential pools last saw it.

Owns those steps (test, save, test again, remove) and the providers' rows the page
shows. Must not: keep a key or its end in AGOS (Hermes's .env holds them), or pick
HTTP statuses (an ActionError carries its status).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agos_core.actions import general_sync, hermes_all_settings
from agos_core.actions.errors import ActionError
from agos_core.actions.services.settings import model_catalog
from agos_core.context import Core
from agos_core.engine import key_status
from agos_core.engine.provider_keys import CALL_FAILED, KeyProblem, ProviderKeys, clean_key

__all__ = ["providers", "remove_key", "save_key", "test_key", "to_every_root"]

log = logging.getLogger("agos.models")

_SAVE_FAILED: tuple[type[Exception], ...] = (KeyProblem, *CALL_FAILED)


def _key_envs(p: dict[str, Any]) -> list[str]:
    """Hermes's own key variables for the provider (its registry), in its order."""
    names = [str(n) for n in p.get("keyEnvs") or [] if n]
    return names or ([str(p["keyEnv"])] if p.get("keyEnv") else [])


def _held_env(p: dict[str, Any], env: dict[str, str]) -> str:
    """The variable his key is saved under: the one Hermes's .env has (an older save
    may have used Hermes's second name), else Hermes's first."""
    names = _key_envs(p)
    return next((n for n in names if env.get(n)), names[0] if names else "")


def _key_homes(core: Core) -> list[Path]:
    """Every home holding General Settings' keys: the shared one and each root."""
    assert core.engine is not None
    return [core.engine.settings.hermes_home, *(root for _, _, root in model_catalog.roots(core))]


def providers(core: Core) -> list[dict[str, Any]]:
    """Each provider's row: its sign-in, and its key's end and state when it has one
    (the key read from Hermes's .env, its state from each home's credential pool)."""
    data = model_catalog.load(core, False)
    env = general_sync.general_values(core)
    homes = _key_homes(core)
    pools: list[list[dict[str, Any]]] | None = None
    out = []
    for p in data["providers"]:
        name = _held_env(p, env)
        key = env.get(name, "") if name else ""
        if p.get("api") is not None and key:
            if pools is None:  # each home's pool, read by Hermes (once per request)
                pools = general_sync.pools(core, homes)
            found = key_status.status(pools, _key_envs(p))
            p = {
                **p,
                "keyEnv": p.get("keyEnv") or name,
                "api": {
                    "last4": key[-4:],
                    "status": found.status,
                    "statusAt": found.at,
                    "problem": found.problem,
                },
            }
        out.append({k: v for k, v in p.items() if k != "keyEnvs"})
    return out


def _keys(core: Core) -> ProviderKeys:
    if core.engine is None:
        raise ActionError(model_catalog.ENGINE_OFF, 503)
    return ProviderKeys(core.engine.settings)


def save_key(core: Core, provider: str, given: str) -> dict[str, Any]:
    """Hermes tests the key, then saves it for every workspace: {ok, message}."""
    keys = _keys(core)
    extra = _extra_key_env(core, provider)
    if extra:  # one of Hermes's other providers: Hermes's own probe when it has one
        try:
            key = clean_key(given)
            tested = keys.probe(extra, key)
            if tested is not None and not tested.ok:
                raise ActionError(tested.message, 422)
            keys.save_env(extra, key)
        except KeyProblem as error:
            raise ActionError(str(error), 422) from error
        except CALL_FAILED as error:
            raise ActionError("Hermes did not save the key.", 503) from error
        to_every_root(core, extra)
        data = model_catalog.load(core, True)
        works = any(p["id"] == provider for p in data["catalog"])
        return {
            "ok": True,
            "message": "Key saved. Every workspace can use it."
            if works
            else "Key saved in Hermes, but Hermes found no models with it yet. Check the key.",
        }
    name = _env_of(core, provider)
    try:
        key = clean_key(given)
        result = keys.check(name, key)
    except KeyProblem as error:
        raise ActionError(str(error), 422) from error
    except CALL_FAILED as error:
        raise ActionError("Hermes did not test the key.", 503) from error
    if not result.ok:
        raise ActionError(result.message, 422)
    try:
        keys.save_env(name, key)
    except _SAVE_FAILED as error:
        # The error's type only: its text could echo the key.
        log.warning("saving the %s key failed: %s", provider, type(error).__name__)
        raise ActionError("Hermes did not save the key.", 503) from error
    to_every_root(core, name)
    model_catalog.load(core, True)
    return {"ok": True, "message": "Key saved. Every workspace can use it."}


def to_every_root(core: Core, name: str | None = None) -> None:
    """General Settings' keys into every workspace's own Hermes root (ADR 0020)."""
    if name:
        general_sync.remember_name(core, name)
    general_sync.sync(core)
    hermes_all_settings.warm_after_write(core)  # every root's .env: Hermes settings' rows


def _env_of(core: Core, provider: str) -> str:
    """Hermes's own variable for one of the five providers' key (its registry)."""
    data = model_catalog.load(core, False)
    row = next((p for p in data["providers"] if p["id"] == provider), None)
    name = _held_env(row, general_sync.general_values(core)) if row and row.get("apiKey") else ""
    if not name:
        raise ActionError("This provider takes no API key here.", 422)
    return name


def _extra_key_env(core: Core, provider: str) -> str | None:
    """Hermes's key variable for one of its other providers (None for the five)."""
    data = model_catalog.load(core, False)
    row = next((p for p in data["providers"] if p["id"] == provider and p.get("more")), None)
    return str(row["keyEnv"]) if row and row.get("keyEnv") else None


def test_key(core: Core, provider: str) -> dict[str, Any]:
    """Hermes tests the saved key again: {ok, message}."""
    keys = _keys(core)
    if _extra_key_env(core, provider):
        data = model_catalog.load(core, True)
        works = any(p["id"] == provider for p in data["catalog"])
        return {
            "ok": works,
            "message": "Key works." if works else "Hermes found no models with this key.",
        }
    try:
        name = _env_of(core, provider)
        key = keys.stored(name)
        if not key:
            raise ActionError("No key is saved for this provider.", 404)
        result = keys.check(name, key)
    except KeyProblem as error:
        raise ActionError(str(error), 422) from error
    except CALL_FAILED as error:
        raise ActionError("Hermes did not answer.", 503) from error
    return {"ok": result.ok, "message": result.message}


def remove_key(core: Core, provider: str) -> None:
    """The key goes from Hermes, in the shared home and every root."""
    keys = _keys(core)
    name = _extra_key_env(core, provider) or _env_of(core, provider)
    # Its name stays General Settings' own, so every root's copy goes with it.
    general_sync.remember_name(core, name)
    try:
        keys.remove_env(name)
    except KeyProblem as error:
        raise ActionError(str(error), 422) from error
    except CALL_FAILED as error:
        raise ActionError("Hermes did not remove the key.", 503) from error
    to_every_root(core)
    model_catalog.load(core, True)
