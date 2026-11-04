"""The config.yaml key behind a Hermes `.env` name (pure rules; moved out of
actions/hermes_all_settings.py, which reads both files)."""

from __future__ import annotations

import json
from typing import Any


def _flat(config: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in config.items():
        path = f"{prefix}.{name}" if prefix else str(name)
        if isinstance(value, dict) and value:
            out.update(_flat(value, path))
        else:
            out[path] = value
    return out


def _as_env(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def yaml_key_for(name: str, yaml_value: str, config: dict[str, Any]) -> str | None:
    """The config.yaml key Hermes's bridge turned into this .env name: a key the
    profile sets to that value whose last part ends the name (telegram.reactions →
    TELEGRAM_REACTIONS, terminal.timeout → TERMINAL_TIMEOUT). Hermes keeps that map
    inside its bridge functions, so it's matched on the bridge's own output."""
    found = [
        key
        for key, value in _flat(config).items()
        if name.endswith(key.rsplit(".", 1)[-1].upper())
        and _as_env(value).strip().lower() == str(yaml_value).strip().lower()
    ]
    return min(found, key=len) if found else None
