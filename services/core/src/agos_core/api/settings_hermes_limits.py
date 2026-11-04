"""Settings → Limits: Hermes's loop detector, its time limit and the Kanban's members
at once (actions/hermes_limits.py), and every timeout of Hermes
(actions/hermes_time_limits.py). Hermes keeps the values; AGOS keeps no copy.

Must not: read or write a Hermes config itself (the actions do), or reach the engine.
"""

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import hermes_limits, hermes_time_limits
from agos_core.actions.services.settings.time_limit_rows import time_limits_view
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

__all__ = [
    "HermesLimitDefaults",
    "HermesLimits",
    "HermesLimitsOut",
    "HermesTimeLimits",
    "HermesTimeLimitsBody",
    "TimeLimitSpread",
    "TimeLimitView",
    "router",
]

router = APIRouter()


class HermesLimits(Body):
    """The loop detector and the time limit: Hermes's own settings (every workspace).
    A count left out (or null) is Hermes's own default; `membersAtOnce` null is
    Hermes's own cap (derived from the machine's memory)."""

    loop_on: bool = False
    same_error: int | None = Field(default=None, ge=2, le=100)
    same_tool_failing: int | None = Field(default=None, ge=2, le=100)
    no_progress: int | None = Field(default=None, ge=2, le=100)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=525_600)
    # Kanban: how many team members work at the same time (each workspace's board).
    members_at_once: int | None = Field(default=None, ge=1, le=20)


class HermesLimitDefaults(Record):
    """What Hermes does when a profile sets nothing (read from Hermes)."""

    same_error: int | None = None
    same_tool_failing: int | None = None
    no_progress: int | None = None
    members_at_once: int | None = None  # Hermes's memory-derived Kanban cap; null: no cap


class HermesLimitsOut(HermesLimits):
    hermes_defaults: HermesLimitDefaults


def _limits_body(shown: hermes_limits.Shown) -> HermesLimitsOut:
    return HermesLimitsOut(
        **asdict(shown.limits),
        hermes_defaults=HermesLimitDefaults(**shown.defaults, members_at_once=shown.members_auto),
    )


@router.get("/preferences/hermes-limits")
async def get_hermes_limits(core: CoreDep) -> HermesLimitsOut:
    return _limits_body(await asyncio.to_thread(hermes_limits.shown, core))


@router.put("/preferences/hermes-limits")
async def put_hermes_limits(core: CoreDep, body: HermesLimits) -> HermesLimitsOut:
    limits = hermes_limits.Limits(
        loop_on=body.loop_on,
        same_error=body.same_error,
        same_tool_failing=body.same_tool_failing,
        no_progress=body.no_progress,
        time_limit_minutes=body.time_limit_minutes,
        members_at_once=body.members_at_once,
    )
    await asyncio.to_thread(hermes_limits.write, core, limits)
    return _limits_body(await asyncio.to_thread(hermes_limits.shown, core))


class TimeLimitSpread(Record):
    """One value and the profiles that have it (shown when workspaces differ)."""

    value: int | None
    profiles: list[str]


class TimeLimitView(Record):
    key: str
    group: str
    label: str
    hint: str
    zero_is_no_limit: bool
    no_limit_value: int
    hermes_default: int | None
    read_by_hermes: bool
    restart: bool
    value: int | None
    no_limit: bool
    spread: list[TimeLimitSpread]


class HermesTimeLimits(Record):
    """Every timeout of Hermes, as the workspaces' Hermes have them (no copy in AGOS)."""

    profiles: int
    groups: list[str]
    limits: list[TimeLimitView]


class HermesTimeLimitsBody(Body):
    """Hermes key → seconds (only the keys sent are written)."""

    values: dict[str, int] = Field(default_factory=dict)


def _time_limits_view(seen: dict[str, Any]) -> HermesTimeLimits:
    return HermesTimeLimits.model_validate(time_limits_view(seen))


@router.get("/preferences/hermes-time-limits")
async def get_hermes_time_limits(core: CoreDep) -> HermesTimeLimits:
    return _time_limits_view(await asyncio.to_thread(hermes_time_limits.read, core))


@router.put("/preferences/hermes-time-limits")
async def put_hermes_time_limits(core: CoreDep, body: HermesTimeLimitsBody) -> HermesTimeLimits:
    seen = await asyncio.to_thread(hermes_time_limits.write, core, dict(body.values))
    return _time_limits_view(seen)
