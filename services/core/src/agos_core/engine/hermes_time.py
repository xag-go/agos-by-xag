"""Hermes's times as AGOS stores them (pure)."""

from __future__ import annotations

from datetime import UTC, datetime


def iso_utc(text: str) -> str | None:
    """Hermes's ISO time (with its offset) as AGOS's UTC ISO."""
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
