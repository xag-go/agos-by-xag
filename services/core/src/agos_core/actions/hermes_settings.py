"""Hermes's own settings, shown in AGOS (a window onto the workspace's Hermes).

AGOS keeps no copy: each value is read from the workspace's Hermes profile
(its config.yaml) and written back there (`hermes config set` / `unset`), so Hermes stays
the engine and the owner never has to open Hermes to change how it works.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.hermes_settings")


@dataclass(frozen=True)
class Setting:
    key: str  # Hermes's config key (its default is Hermes's own: `defaults`)
    low: int
    high: int


SETTINGS: dict[str, Setting] = {
    # /goal: how many turns Hermes may keep working on a goal before it stops.
    "goals.max_turns": Setting("goals.max_turns", 1, 1000),
}


def defaults(core: Core) -> dict[str, str]:
    """Hermes's own default of each setting, from Hermes's settings list
    (engine/hermes_schema.py); empty when that list can't be read."""
    if core.engine is None:
        return {}
    try:
        fields = {f.key: f for f in core.engine.config_schema()}
    except (EngineError, OSError) as error:
        log.info("Hermes's defaults not read (%s)", error)
        return {}
    return {
        key: str(fields[key].default)
        for key in SETTINGS
        if key in fields and fields[key].default is not None
    }


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): Hermes's settings list the
    card's defaults come from (one Hermes run, kept while Hermes's defaults file is
    unchanged), so the card's first view never starts Hermes."""
    defaults(core)


def _own(core: Core, workspace_id: str) -> dict[str, str]:
    """The values the workspace's Hermes profile itself sets (config.yaml), "" for
    one it leaves unset. Not `hermes config get`: that prints the resolved value,
    Hermes's default included (H: hermes_cli/config.py:3731 load_config), so an
    unset key would look set."""
    if core.engine is None:
        return dict.fromkeys(SETTINGS, "")
    cfg = config_file.read(core.engine.profile_home(workspace_id))
    out: dict[str, str] = {}
    for key in SETTINGS:
        value = config_file.get(cfg, key)
        out[key] = str(value).strip() if value is not None and not isinstance(value, bool) else ""
    return out


def read(core: Core, workspace_id: str) -> dict[str, str]:
    """Each setting as the workspace's Hermes profile sets it; "" when unset (Hermes
    uses its own default: `defaults`, shown as the field's placeholder)."""
    require_workspace(core, workspace_id)
    return {k: v if v.isdigit() else "" for k, v in _own(core, workspace_id).items()}


def write(core: Core, workspace_id: str, values: dict[str, str]) -> dict[str, str]:
    """Writes his values into the workspace's Hermes (only the settings shown here),
    and only what changes: a value the profile already has is not written again; an
    empty field, or Hermes's own default, means unset (`hermes config unset`), so
    Hermes's default is never frozen into the profile."""
    require_workspace(core, workspace_id)
    if core.engine is None:
        raise ActionError("This workspace isn't available.", status=503)
    wanted: dict[str, str] = {}
    for key, raw in values.items():
        setting = SETTINGS.get(key)
        if setting is None:
            raise ActionError(f"{key} isn't a setting AGOS shows.")
        value = str(raw).strip()
        if value and (not value.isdigit() or not setting.low <= int(value) <= setting.high):
            raise ActionError(f"Use a number between {setting.low} and {setting.high}.")
        wanted[key] = value
    have = _own(core, workspace_id)
    fallback = defaults(core) if any(wanted.values()) else {}
    wrote = False
    for key, value in wanted.items():
        if value and fallback.get(key) == value:
            value = ""  # Hermes's own default: leave it to Hermes
        if value == have.get(key, ""):
            continue
        try:
            if value:
                hermes_cli.cli(core.engine, workspace_id, "config", "set", key, value)
            else:
                hermes_cli.cli(core.engine, workspace_id, "config", "unset", key)
        except (EngineError, OSError) as error:
            raise ActionError(f"The engine didn't take it: {error}", status=502) from error
        wrote = True
    if wrote:
        from agos_core.actions import hermes_all_settings

        hermes_all_settings.warm_after_write(core)  # Settings → Hermes settings reads it
    # Hermes reads them for each agent it builds (its gateway keeps running).
    return read(core, workspace_id)
