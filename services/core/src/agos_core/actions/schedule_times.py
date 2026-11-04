"""A daily or weekly time the owner picks (HH:MM and a weekday), checked."""

from __future__ import annotations

import re

from agos_core.actions.errors import ActionError

TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def time_day(policy: str, time: str, day: int | None) -> tuple[str, int | None]:
    if not TIME.match(time):
        raise ActionError("A time is HH:MM, 00:00 to 23:59.")
    if policy == "weekly":
        if day is None or not 0 <= day <= 6:
            raise ActionError("The weekly update's day: 0 (Sunday) to 6 (Saturday).")
        return time, day
    return time, None
