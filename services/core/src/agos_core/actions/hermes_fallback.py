"""The fallback models (General settings → Fallback models): Hermes's own
`fallback_providers`, the provider + model list Hermes tries in order when a
profile's main model fails. One chain for every workspace.

AGOS keeps no copy. The chain lives in Hermes's managed scope, the one
config.yaml every Hermes process AGOS runs reads on top of each profile's own
(actions/hermes_managed.py), written with Hermes's own `hermes config set
fallback_providers <list>`. A profile's legacy `fallback_model` (which Hermes
merges after the chain) goes with the profiles' old copies (hermes_managed
settle), like Hermes's own `hermes fallback` drops it. (`hermes fallback
add/remove` are interactive pickers that need a terminal: not usable from AGOS.)
A new profile reads the same file: nothing to copy.

Before this card AGOS kept the chain in its own app_settings
(`models.fallback_providers`). That copy is moved into Hermes once at core start
(`move_old_setting`) and deleted.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.hermes_time_limits import profiles
from agos_core.context import Core
from agos_core.engine import fallback as fb
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hermes_fallback")

# AGOS's old copy (app_settings), moved into Hermes once and deleted.
OLD_SETTING = "models.fallback_providers"
MAX_ENTRIES = 20

_PROVIDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\] ]{0,299}$")
_URL = re.compile(r"^https?://[^\s]{1,500}$")


@dataclass
class Seen:
    """The chain as the workspaces' Hermes have it."""

    chain: list[dict[str, str]]  # the most common chain (what the card shows)
    spread: list[tuple[list[dict[str, str]], list[str]]] = field(default_factory=list)


def keyed(entry: dict[str, Any]) -> bool:
    """The route carries its own API key: an inline `api_key`, or `key_env` /
    `api_key_env` naming one (Hermes's resolve_entry_api_key,
    H: hermes_cli/fallback_config.py:38-53). Only this yes/no leaves the file."""
    return any(str(entry.get(k) or "").strip() for k in ("api_key", "key_env", "api_key_env"))


def _shown(chain: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Only provider, model, base_url and whether it has its own key leave Hermes's
    file (an entry may hold an inline api_key)."""
    return [
        {
            "provider": str(e["provider"]),
            "model": str(e["model"]),
            "base_url": fb.base_url_of(e),
            **({"keyed": "1"} if keyed(e) else {}),
        }
        for e in chain
    ]


def _managed(core: Core) -> dict[str, Any]:
    from agos_core.actions import hermes_managed

    return hermes_managed.current(core)


def read(core: Core) -> dict[str, Any]:
    """The chain Hermes uses (its managed scope: the same for every profile)."""
    return {"profiles": len(profiles(core)), "seen": Seen(_shown(fb.chain_in(_managed(core))))}


def check(chain: list[dict[str, str]]) -> list[dict[str, str]]:
    """The chain as written: each route once, in the owner's order."""
    if len(chain) > MAX_ENTRIES:
        raise ActionError(f"Use at most {MAX_ENTRIES} fallback models.")
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for n, entry in enumerate(chain, 1):
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        base_url = str(entry.get("base_url") or "").strip().rstrip("/")
        if not _PROVIDER.fullmatch(provider):
            raise ActionError(f"Fallback {n}: pick a provider Hermes knows (e.g. openrouter).")
        if not _MODEL.fullmatch(model):
            raise ActionError(f"Fallback {n}: pick a model (e.g. anthropic/claude-sonnet-4).")
        if base_url and not _URL.fullmatch(base_url):
            raise ActionError(f"Fallback {n}: the endpoint is an http(s) address.")
        clean = {
            "provider": provider,
            "model": model,
            **({"base_url": base_url} if base_url else {}),
        }
        if fb.identity(clean) in seen:
            continue
        seen.add(fb.identity(clean))
        out.append(clean)
    return out


def _set(core: Core, chain: list[dict[str, Any]]) -> None:
    from agos_core.actions import hermes_managed

    hermes_managed.write(core, {fb.KEY: fb.as_argument(chain)}, (fb.LEGACY,))


def write(core: Core, chain: list[dict[str, str]]) -> dict[str, Any]:
    """Into Hermes's managed scope (every profile of every workspace). Hermes reads
    the chain again at each turn (a running chat applies it from its next message)."""
    wanted = check(chain)
    if core.engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    # A route the chain already has keeps Hermes's extras on it (key_env, api_mode).
    value = fb.value_for(wanted, fb.chain_in(_managed(core)))
    try:
        _set(core, [{k: v for k, v in e.items() if k != "api_key"} for e in value])
    except (EngineError, OSError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    return read(core)


def move_old_setting(core: Core) -> bool:
    """AGOS's old copy (app_settings `models.fallback_providers`) → Hermes, once:
    into the managed scope when it has no chain yet, then deleted. Kept for the
    next start when Hermes didn't take it. True when it moved."""
    from agos_core.db.app_settings import delete_setting, get_setting

    old = get_setting(core.db, OLD_SETTING, None)
    if old is None:
        return False
    if core.engine is None:
        return False
    chain = [{"provider": str(e["provider"]), "model": str(e["model"])} for e in fb.entries(old)]
    try:
        wanted = check(chain)
    except ActionError as error:
        log.warning("old fallback setting not moved (%s): deleted", error.message)
        wanted = None
    if wanted is not None and not fb.is_set(_managed(core)):
        try:
            _set(core, wanted)
        except (EngineError, OSError) as error:
            log.warning("old fallback setting kept for the next start: %s", error)
            return False
    delete_setting(core.db, OLD_SETTING)
    log.info("fallback models moved from AGOS's settings into Hermes")
    return True
