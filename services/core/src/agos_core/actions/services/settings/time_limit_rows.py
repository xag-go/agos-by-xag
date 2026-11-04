"""Hermes's timeouts as Settings → Limits shows them: each of Hermes's time limits
(engine/time_limits.py, Hermes's own keys and words) with the value the
workspaces' Hermes have now, read by actions/hermes_time_limits.py.

Must not: read or write a Hermes config itself, or know about HTTP.
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.time_limits import GROUPS, TIME_LIMITS

__all__ = ["time_limits_view"]


def time_limits_view(seen: dict[str, Any]) -> dict[str, Any]:
    """`seen` (hermes_time_limits.read / write) as the page's rows, in Hermes's order."""
    limits = []
    for limit in TIME_LIMITS:
        found = seen["limits"][limit.key]
        value = found.value
        limits.append(
            {
                "key": limit.key,
                "group": limit.group,
                "label": limit.label,
                "hint": limit.hint,
                "zero_is_no_limit": limit.zero_is_no_limit,
                "no_limit_value": limit.no_limit_value,
                "hermes_default": (seen.get("defaults") or {}).get(limit.key),
                "read_by_hermes": limit.read_by_hermes,
                "restart": limit.restart,
                "value": value,
                "no_limit": value is not None and limit.is_no_limit(value),
                "spread": [{"value": v, "profiles": p} for v, p in found.spread],
            }
        )
    return {"profiles": seen["profiles"], "groups": list(GROUPS), "limits": limits}
