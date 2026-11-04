"""Every timeout of Hermes in one place (General settings → Time limits): Hermes's
own settings, one value for every workspace.

AGOS keeps no copy. The limits live in Hermes's managed scope, read by every Hermes process AGOS runs (actions/hermes_managed.py),
written with Hermes's own `hermes config set` (an UPPER_SNAKE name,
TERMINAL_MAX_FOREGROUND_TIMEOUT, goes through that same command to Hermes's .env
writer: hermes_cli/config.py set_config_value → save_env_setting, the scope's
.env). A new profile reads the same scope: nothing to copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine.hermes import EngineError
from agos_core.engine.time_limits import BY_KEY, HERMES_MAX_SECONDS, TIME_LIMITS, TimeLimit

log = logging.getLogger("agos.hermes_time_limits")


@dataclass(frozen=True)
class Profile:
    key: str  # the engine's key: "<ws>" (its Co-Founder) or "<ws>--<member>"
    label: str  # "Sales" or "Sales · a-writer"
    home: Path


@dataclass
class Seen:
    """One setting as the workspaces' Hermes have it."""

    value: Any  # the most common value (what the card shows)
    spread: list[tuple[Any, list[str]]] = field(default_factory=list)  # when they differ


def profiles(core: Core) -> list[Profile]:
    """Every profile on every workspace's own root (archived workspaces too: they
    keep running their automations)."""
    from agos_core.db.workspaces import list_workspaces

    engine = core.engine
    if engine is None:
        return []
    prefix = engine.settings.profile_prefix
    out: list[Profile] = []
    for ws in list_workspaces(core.db, include_archived=True):
        for name in engine.own_profiles(ws.id):
            key = name[len(prefix) :]
            home = engine.profile_home(key)
            if not (home / "config.yaml").is_file():
                continue
            member = engine.split(key)[1]
            out.append(Profile(key, f"{ws.name} · {member}" if member else ws.name, home))
    return out


def _number(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return round(float(str(raw).strip().strip("\"'")))
    except ValueError:
        return None


@dataclass(frozen=True)
class Files:
    """One home's config.yaml and .env, read once (Hermes wrote them)."""

    config: dict[str, Any]
    env: dict[str, str]

    @classmethod
    def of(cls, home: Path) -> Files:
        from agos_core.engine import config_file

        return cls(config_file.read(home), config_file.read_env(home))


def _raw(files: Files, key: str) -> Any:
    """The value as Hermes has it in this home (None: not set)."""
    from agos_core.engine import config_file

    if key.isupper():
        found: Any = files.env.get(key)
        return found if found not in (None, "") else None
    return config_file.get(files.config, key)


def defaults(core: Core) -> dict[str, int | None]:
    """Hermes's own default of each time limit: its settings list's (DEFAULT_CONFIG,
    engine.config_schema), else the literal in its code for a key DEFAULT_CONFIG
    lacks (engine/time_limits.py code_default); None: not known (Hermes's list
    unread, or a key Hermes doesn't read)."""
    fields: dict[str, Any] = {}
    if core.engine is not None:
        try:
            fields = {f.key: f for f in core.engine.config_schema()}
        except (EngineError, OSError) as error:
            log.info("Hermes's time-limit defaults not read: %s", error)
    out: dict[str, int | None] = {}
    for limit in TIME_LIMITS:
        if not limit.read:
            out[limit.key] = None
        elif limit.code_default is not None:
            out[limit.key] = limit.code_default
        else:
            field = fields.get(limit.key)
            out[limit.key] = _number(field.default) if field is not None else None
    return out


def value_in(files: Files, limit: TimeLimit, default: int | None = None) -> int | None:
    """What Hermes uses in this home: its value, else Hermes's own default."""
    found = _number(_raw(files, limit.key))
    return found if found is not None else default


def read(core: Core) -> dict[str, Any]:
    """Each timeout as Hermes has it (its managed scope: one value for all)."""
    managed = (
        Files.of(core.engine.settings.managed_home) if core.engine is not None else Files({}, {})
    )
    hermes = defaults(core)
    limits = {limit.key: Seen(value_in(managed, limit, hermes[limit.key])) for limit in TIME_LIMITS}
    return {"profiles": len(profiles(core)), "limits": limits, "defaults": hermes}


def check(values: dict[str, int]) -> None:
    for key, value in values.items():
        limit = BY_KEY.get(key)
        if limit is None:
            raise ActionError(f"{key} isn't one of Hermes's time limits here.")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ActionError(f"{limit.label}: use a whole number of seconds.")
        if value == 0 and not limit.zero_is_no_limit:
            raise ActionError(
                f"{limit.label}: Hermes doesn't read 0 as no limit here; turn on No limit."
            )
        if not 0 <= value <= HERMES_MAX_SECONDS:
            raise ActionError(f"{limit.label}: use between 1 second and a year.")


def _changes_in(files: Files, values: dict[str, int]) -> list[tuple[str, str]]:
    """Only what these files don't have yet (each `hermes config set` is a process)."""
    return [
        (key, str(value))
        for key, value in values.items()
        if _raw(files, key) is None or _number(_raw(files, key)) != value
    ]


def write(core: Core, values: dict[str, int]) -> dict[str, Any]:
    """Into Hermes's managed scope (every workspace). No gateway is stopped for it:
    most are read for each answer; the ones read at start (TimeLimit.restart) apply
    when that workspace's Hermes next starts."""
    from agos_core.actions import hermes_managed

    check(values)
    if core.engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    managed = Files.of(core.engine.settings.managed_home)
    try:
        hermes_managed.write(core, dict(_changes_in(managed, values)))
    except (EngineError, OSError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    return read(core)
