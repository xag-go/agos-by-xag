"""Settings → Models: Hermes's model catalog (what the owner can pick, per provider and
way in), kept on the engine, and the Hermes roots it reads each workspace's own
logins from.

Owns reading the catalog (ModelCatalog, kept once per engine), its order for the
pickers (Hermes's own default model first) and Hermes's provider names per way in.
Must not: save keys or logins (model_keys.py, model_logins.py) or pick HTTP statuses
(an ActionError carries its status).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agos_core.actions import engine as engine_actions
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import workspaces as workspaces_repo
from agos_core.domain.models import ModelSelection
from agos_core.engine.hermes import ROOT_MARKER
from agos_core.engine.models import ModelCatalog, hermes_slug

__all__ = [
    "catalog_of",
    "default_model",
    "hermes_first",
    "hermes_providers",
    "load",
    "read_ahead",
    "roots",
    "shown",
]

log = logging.getLogger("agos.models")

ENGINE_OFF = "The agent engine is off."


def catalog_of(core: Core) -> ModelCatalog:
    """The engine's one ModelCatalog (made at the first read)."""
    if core.engine is None:
        raise ActionError(ENGINE_OFF, 503)
    cached: ModelCatalog | None = getattr(core.engine, "model_catalog", None)
    if cached is None:
        cached = ModelCatalog(core.engine.settings, roots=lambda: roots(core))
        core.engine.model_catalog = cached  # type: ignore[attr-defined]
    return cached


def roots(core: Core) -> list[tuple[str, str, Path]]:
    """(id, name, root) of every workspace living on a Hermes root of its own."""
    engine = core.engine
    if engine is None or engine.settings.roots_dir is None:
        return []
    out = []
    for workspace_id in workspaces_repo.ids(core.db, archived=False):
        root = engine.root(workspace_id)
        if (root / ROOT_MARKER).is_file():
            out.append((workspace_id, workspaces_repo.name_of(core.db, workspace_id), root))
    return sorted(out, key=lambda r: r[1])


def load(core: Core, refresh: bool) -> dict[str, list[dict[str, object]]]:
    """The catalog and the providers' rows, as Hermes lists them now."""
    catalog = catalog_of(core)
    try:
        return catalog.load(refresh=refresh)
    except (OSError, RuntimeError, ValueError) as error:
        log.warning("model catalog failed: %s", error)
        raise ActionError("Hermes did not list the models.", 503) from error


def hermes_first(catalog: list[dict[str, Any]], default: Any) -> list[dict[str, Any]]:
    """The catalog with Hermes's own default model (the shared home's model.default,
    actions/engine.py shared_model) first: its provider, then its model, then its
    mode. Every picker that starts on the catalog's first choice (the web's
    firstChoice) then starts on Hermes's model when Hermes has one; the order is
    otherwise unchanged. A default the catalog doesn't offer changes nothing."""
    if default is None:
        return catalog
    provider, model, mode = default.provider, default.model, default.mode
    for p in catalog:
        if p.get("id") != provider:
            continue
        found = next((m for m in p.get("models") or [] if m.get("id") == model), None)
        if found is None or mode not in (found.get("modes") or []):
            return catalog
        found = {**found, "modes": [mode, *[x for x in found["modes"] if x != mode]]}
        models = [found, *[m for m in p["models"] if m.get("id") != model]]
        return [{**p, "models": models}, *[x for x in catalog if x is not p]]
    return catalog


def shown(core: Core, refresh: bool) -> list[dict[str, Any]]:
    """The logged-in providers' models, Hermes's own default model first."""
    data = load(core, refresh)
    return hermes_first(list(data["catalog"]), engine_actions.shared_model(core))


def default_model(core: Core) -> ModelSelection | None:
    """The model a new workspace starts on: the shared Hermes home's own model
    (None when Hermes has none there)."""
    found: ModelSelection | None = engine_actions.shared_model(core)
    return found


def hermes_providers(provider: str, modes: set[str]) -> dict[str, str]:
    """Hermes's provider name for each way in (mode -> e.g. "openai-codex")."""
    return {m: hermes_slug(provider, m) for m in sorted(modes)}


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): Hermes's model catalog that
    Settings → Models and every model picker read (the pools beside it are read
    ahead by actions/key_pools.py)."""
    if core.engine is None:
        return
    try:
        catalog_of(core).load(refresh=False)
    except (OSError, RuntimeError, ValueError) as error:
        log.info("model catalog not read ahead: %s", error)
