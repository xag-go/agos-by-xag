"""`CONTRACT`: every entry of engine/contract/uses_*.py, in the order the checker
reports them (guard, bridge, kanban, rooms / voice, engine).

Must not: define an entry (each lives in its uses_*.py).
"""

from __future__ import annotations

from agos_core.engine.contract import (
    uses_bridge,
    uses_engine,
    uses_engine_apps,
    uses_engine_cron,
    uses_engine_skills,
    uses_guard,
    uses_kanban,
    uses_rooms_voice,
)
from agos_core.engine.contract.base import Use

__all__ = [
    "CONTRACT",
]

CONTRACT: tuple[Use, ...] = (
    *uses_guard.USES,
    *uses_bridge.USES,
    *uses_kanban.USES,
    *uses_rooms_voice.USES,
    *uses_engine.USES,
    *uses_engine_skills.USES,
    *uses_engine_cron.USES,
    *uses_engine_apps.USES,
)
