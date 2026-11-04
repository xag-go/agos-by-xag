"""The time limit and the loop detector: Hermes's own settings, one value for every
workspace from AGOS's General settings.

AGOS keeps no copy, not even of Hermes's defaults. The values live in Hermes's
managed scope, the one config.yaml every Hermes process AGOS runs reads
(actions/hermes_managed.py), written with Hermes's own `hermes config set`; a
value left to Hermes is not written there (Hermes's own default applies, read from
its settings list for the card):
- the loop detector is Hermes's loop guard (`tool_loop_guardrails`): it always
  warns the agent, and when it's on it ends an answer that keeps failing the same
  way (after the counts below);
- the time limit is Hermes's run budget (`agent.run_budget_seconds`): at 80% Hermes
  tells the agent to wrap up, and the answer can't go past it;
- how many team members work at once is Hermes Kanban's own cap
  (`kanban.max_in_progress`). Unset, Hermes derives it from the machine's memory
  (hermes_cli/kanban_db_dispatch.py derive_default_max_in_progress): AGOS shows
  that and never writes a number he didn't choose.
A new workspace reads the same file: nothing to copy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hermes_limits")

LOOP = "tool_loop_guardrails"
TIME = "agent.run_budget_seconds"
AT_ONCE = "kanban.max_in_progress"
ON = (f"{LOOP}.hard_stop_enabled", f"{LOOP}.non_interactive_hard_stop_enabled")
WARN = f"{LOOP}.warnings_enabled"
COUNTS = {  # the card's field -> Hermes's key (its default comes from Hermes)
    "same_error": f"{LOOP}.hard_stop_after.exact_failure",
    "same_tool_failing": f"{LOOP}.hard_stop_after.same_tool_failure",
    "no_progress": f"{LOOP}.hard_stop_after.idempotent_no_progress",
}
KEYS = (WARN, *ON, *COUNTS.values(), TIME, AT_ONCE)


@dataclass(frozen=True)
class Limits:
    loop_on: bool = False  # off: nothing stops the team by itself (the owner's rule)
    # None: Hermes's own default (unknown when its settings list can't be read).
    same_error: int | None = None
    same_tool_failing: int | None = None
    no_progress: int | None = None
    time_limit_minutes: int | None = None  # None: no time limit
    # Kanban: members working at the same time; None = Hermes decides (by memory).
    members_at_once: int | None = None


@dataclass(frozen=True)
class Shown:
    """The card: the values, and what Hermes does when nothing is set."""

    limits: Limits
    defaults: dict[str, int]  # Hermes's default of each count (card field -> value)
    members_auto: int | None  # Hermes's own cap while members_at_once is unset


def _int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(str(value).strip()))
    except ValueError:
        return None
    return number if number > 0 else None


def hermes_defaults(core: Core) -> dict[str, int]:
    """Hermes's own default of each count (from its settings list; {} unread)."""
    if core.engine is None:
        return {}
    try:
        fields = {f.key: f for f in core.engine.config_schema()}
    except (EngineError, OSError) as error:
        log.info("Hermes's loop guard defaults not read (%s)", error)
        return {}
    out: dict[str, int] = {}
    for name, key in COUNTS.items():
        found = fields.get(key)
        value = _int(found.default) if found is not None else None
        if value is not None:
            out[name] = value
    return out


def _of(cfg: dict[str, object], defaults: dict[str, int]) -> Limits:
    def on(key: str) -> bool:
        value = config_file.get(cfg, key)
        return value is True or str(value).strip().lower() == "true"

    def count(name: str) -> int | None:
        return _int(config_file.get(cfg, COUNTS[name])) or defaults.get(name)

    seconds = config_file.get(cfg, TIME)
    try:
        minutes = (
            max(1, round(float(str(seconds)) / 60))
            if seconds is not None and float(str(seconds)) > 0
            else None
        )
    except ValueError:
        minutes = None
    return Limits(
        loop_on=any(on(k) for k in ON),
        same_error=count("same_error"),
        same_tool_failing=count("same_tool_failing"),
        no_progress=count("no_progress"),
        time_limit_minutes=minutes,
        members_at_once=_int(config_file.get(cfg, AT_ONCE)),
    )


def _managed(core: Core) -> dict[str, object]:
    from agos_core.actions import hermes_managed

    return hermes_managed.current(core)


def read(core: Core, defaults: dict[str, int] | None = None) -> Limits:
    """As Hermes has them (its managed scope: the same for every workspace;
    Hermes's own default where it sets none)."""
    return _of(_managed(core), hermes_defaults(core) if defaults is None else defaults)


def shown(core: Core) -> Shown:
    """The card: the values, Hermes's defaults and its own Kanban cap."""
    from agos_core.engine import hermes_schema

    defaults = hermes_defaults(core)  # reads Hermes's list: its auto cap comes with it
    return Shown(read(core, defaults), defaults, hermes_schema.kanban_auto_cap())


def _pairs(limits: Limits) -> list[tuple[str, str | None]]:
    """Every key this card owns and the value it gives it (None: left to Hermes)."""
    on = "true" if limits.loop_on else "false"
    return [
        (WARN, "true"),
        (ON[0], on),
        (ON[1], on),
        *(
            (key, str(v) if (v := getattr(limits, name)) is not None else None)
            for name, key in COUNTS.items()
        ),
        (TIME, str(limits.time_limit_minutes * 60) if limits.time_limit_minutes else None),
        (AT_ONCE, str(limits.members_at_once) if limits.members_at_once else None),
    ]


def _changes(
    cfg: dict[str, object], limits: Limits, defaults: dict[str, int]
) -> tuple[dict[str, str], list[str]]:
    """What the managed scope must set and unset to say `limits`: only what
    differs; a count equal to Hermes's default that isn't set stays unset."""
    sets: dict[str, str] = {}
    unsets: list[str] = []
    names = {key: name for name, key in COUNTS.items()}
    for key, value in _pairs(limits):
        have = config_file.get(cfg, key)
        if value is None:
            if have is not None:
                unsets.append(key)
            continue
        name = names.get(key)
        if name is not None and have is None and defaults.get(name) == int(value):
            continue
        if have is None or str(have).strip().lower() != value:
            sets[key] = value
    return sets, unsets


def write(core: Core, limits: Limits) -> Limits:
    """Into Hermes's managed scope (every workspace). Its gateways are never stopped
    for it: Hermes reads these for each agent it builds (each new conversation,
    cron run and Kanban card)."""
    from agos_core.actions import hermes_managed

    for value in (limits.same_error, limits.same_tool_failing, limits.no_progress):
        if value is not None and not 2 <= value <= 100:
            raise ActionError("Use a number of tries between 2 and 100.")
    if limits.members_at_once is not None and not 1 <= limits.members_at_once <= 20:
        raise ActionError("Use between 1 and 20 members at once.")
    if limits.time_limit_minutes is not None and not 1 <= limits.time_limit_minutes <= 525_600:
        raise ActionError("Use a time limit between 1 minute and a year.")
    if core.engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    defaults = hermes_defaults(core)
    sets, unsets = _changes(_managed(core), limits, defaults)
    if sets or unsets:
        try:
            hermes_managed.write(core, sets, unsets)
        except (EngineError, OSError) as error:
            raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    return read(core, defaults)
