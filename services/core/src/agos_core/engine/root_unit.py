"""The name of a workspace root's gateway unit, as AGOS keeps it in the root's marker.

Owns: reading and writing the cached unit name in `<root>/.agos-root`, tied to the
folder it was asked for. Must not: ask Hermes (engine/hermes/gateway_unit.py does, through
Hermes's own service naming) or touch the unit itself.

Hermes names a root's unit after its home. A root copied elsewhere (the staging
copy, a restore to another folder) carries the original's marker, so a cached name
counts only when the marker says it was asked for this very folder; a marker from
an AGOS before that (no folder in it) is asked again once.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["MARKER", "cached", "remember"]

MARKER = ".agos-root"  # in a workspace's own Hermes root (ADR 0020): AGOS made it, and owns it


def _read(root: Path) -> dict[str, object] | None:
    try:
        data = json.loads((root / MARKER).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else None


def cached(root: Path) -> str | None:
    """The unit name asked for this folder, or None (ask Hermes)."""
    data = _read(root) or {}
    unit = str(data.get("unit") or "")
    if unit.endswith(".service") and data.get("home") == str(root.resolve()):
        return unit
    return None


def remember(root: Path, unit: str) -> None:
    """Keeps Hermes's answer for this folder (the marker's other fields stay)."""
    data = _read(root)
    if data is not None and root.is_dir():
        marker = root / MARKER
        marker.write_text(
            json.dumps({**data, "unit": unit, "home": str(root.resolve())}, sort_keys=True)
        )
