"""The workspace's screen (Hermes's Bot Desktop in its sandbox): what AGOS reads of it.

Owns: when Hermes stops an unused screen (the workspace's own
bot_desktop.idle_stop_minutes, else Hermes's default from its settings list).

Must not: start, stop or grab the screen (the engine asks Hermes for that).
"""

from __future__ import annotations

from agos_core.context import Core
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError

__all__ = ["IDLE_KEY", "idle_stop_minutes"]

IDLE_KEY = "bot_desktop.idle_stop_minutes"


def idle_stop_minutes(core: Core, workspace_id: str) -> float | None:
    """The workspace's own value, else Hermes's default (from its settings list)."""
    engine = core.engine
    if engine is None:
        return None
    value = config_file.get(config_file.read(engine.profile_home(workspace_id)), IDLE_KEY)
    if value is None:
        try:
            found = {f.key: f for f in engine.config_schema()}.get(IDLE_KEY)
        except (EngineError, OSError):
            found = None
        value = found.default if found is not None else None
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
