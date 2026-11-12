"""Voice notes (General settings → Voice notes): who hears the owner's voice notes,
Hermes's own speech-to-text choice (`stt.provider` and that provider's
`stt.<provider>.model`). One provider + model for every workspace.

AGOS keeps no copy. The choice lives in Hermes's managed scope, the one config.yaml
every Hermes process AGOS runs reads on top of each profile's own
(actions/hermes_managed.py), written with Hermes's own `hermes config set`. The
options are Hermes's providers and models from its own settings schema, and the
`gemini` one AGOS's plugin adds (engine/stt.py). Before the card each profile held its own copy (AGOS's start
values; Fuel Machine Hermes's legacy `local`): hermes_managed.move_once moves the
most common one in once and settle removes the copies.

"Off" (the first option) is Hermes's `stt.enabled: false` with no provider: where
a fresh install starts. Picking a provider removes the switch again (Hermes's
default: on).
"""

from __future__ import annotations

import re
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.hermes_time_limits import profiles
from agos_core.context import Core
from agos_core.engine import stt
from agos_core.engine.hermes import EngineError

_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")


def _managed(core: Core) -> dict[str, Any]:
    from agos_core.actions import hermes_managed

    return hermes_managed.current(core)


def _text(config: dict[str, Any], key: str) -> str:
    from agos_core.engine import config_file

    found = config_file.get(config, key)
    return "" if found is None or isinstance(found, dict | list) else str(found).strip()


def _fields(core: Core) -> list[Any]:
    """Hermes's settings list (its schema: the providers and their models)."""
    if core.engine is None:
        raise ActionError("The engine isn't available.", status=503)
    try:
        return list(core.engine.config_schema())
    except (EngineError, OSError) as error:
        raise ActionError(
            f"The engine's list of voice providers couldn't be read: {error}", 502
        ) from error


def _off(managed: dict[str, Any]) -> bool:
    """Hermes's `stt.enabled` is false (its own reading: a false-ish value)."""
    from agos_core.engine import config_file

    found = config_file.get(managed, stt.ENABLED_KEY)
    return found is False or str(found).strip().lower() in ("false", "0", "no", "off")


def read(core: Core) -> dict[str, Any]:
    """The provider and model Hermes uses (its managed scope: the same for all),
    or "off" when Hermes's speech-to-text is switched off."""
    fields = _fields(core)
    managed = _managed(core)
    options = (stt.OFF, *stt.providers(fields))
    base = {"profiles": len(profiles(core)), "options": options}
    if _off(managed):
        return {**base, "provider": stt.OFF_NAME, "model": ""}
    provider = _text(managed, stt.PROVIDER_KEY)
    key = stt.model_key(provider, fields)
    return {**base, "provider": provider, "model": _text(managed, key) if key else ""}


def check(provider: str, model: str, fields: list[Any]) -> tuple[str, str]:
    provider, model = provider.strip(), model.strip()
    if provider == stt.OFF_NAME:
        return provider, ""
    if provider not in stt.by_name(fields):
        raise ActionError("Pick one of the voice-note providers listed.")
    if model and not _MODEL.fullmatch(model):
        raise ActionError("The model is a model id (e.g. whisper-large-v3-turbo).")
    return provider, model


def write(core: Core, provider: str, model: str) -> dict[str, Any]:
    """Into Hermes's managed scope (every profile of every workspace): the provider,
    its model (none: Hermes's default for it), and no other provider's model; or
    "off" (`stt.enabled: false`, no provider, no model)."""
    from agos_core.actions import hermes_managed

    fields = _fields(core)
    provider, model = check(provider, model, fields)
    managed = _managed(core)
    if provider == stt.OFF_NAME:
        sets = {stt.ENABLED_KEY: "false"}
    else:
        key = stt.by_name(fields)[provider].model_key
        sets = {stt.PROVIDER_KEY: provider, **({key: model} if model else {})}
    unsets = [k for k in stt.card_keys(fields) if k not in sets and hermes_managed.has(managed, k)]
    try:
        hermes_managed.write(core, sets, unsets)
    except (EngineError, OSError) as error:
        raise ActionError(f"The engine didn't take it: {error}", status=502) from error
    return read(core)
