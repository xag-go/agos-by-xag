"""A time-zone name as Hermes takes it (its `timezone` config key).

Owns: turning a name into a zone, or None when Python's zone database doesn't know it
(Hermes's hermes_time.py then falls back to local time, so AGOS never shows it).

Must not: read config or the clock (actions/owner_time.py owns the owner's zone).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = ["zone_of"]


def zone_of(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None
