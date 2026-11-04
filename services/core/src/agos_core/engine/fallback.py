"""Hermes's model fallback chain, read the way Hermes reads it.

`fallback_providers` (top-level list of provider + model, optional base_url) is
tried in order when a profile's main model fails (Hermes v0.22.2
user-guide/features/fallback-providers.md). Hermes merges the legacy single
`fallback_model` after it (hermes_cli/fallback_config.py:126
`get_fallback_chain`) and drops entries without both provider and model
(`_iter_fallback_entries`, :100). The switch itself is
agent/chat_completion_helpers.py:2055 `try_activate_fallback`, called when the
retries on the main model are spent or on an error no retry fixes
(agent/turn_api_error.py:341, :380).

AGOS keeps no copy: this module only reads a profile's config.yaml (as Hermes
wrote it) and builds the value given to Hermes's own `hermes config set`.
"""

from __future__ import annotations

import json
from typing import Any

KEY = "fallback_providers"
LEGACY = "fallback_model"  # Hermes still reads it; its own `hermes fallback` drops it on write


def entries(raw: Any) -> list[dict[str, Any]]:
    """Hermes's `_iter_fallback_entries`: a dict or a list of dicts; both fields set."""
    candidates = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        if not provider or not model:
            continue
        clean = {**entry, "provider": provider, "model": model}
        base_url = base_url_of(entry)
        if base_url:
            clean["base_url"] = base_url
        else:
            clean.pop("base_url", None)
        out.append(clean)
    return out


def base_url_of(entry: dict[str, Any]) -> str:
    value = entry.get("base_url")
    return value.strip().rstrip("/") if isinstance(value, str) else ""


def identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    """One route (Hermes's `_entry_identity`: provider, model, base_url)."""
    return (
        str(entry.get("provider") or "").strip().lower(),
        str(entry.get("model") or "").strip().lower(),
        base_url_of(entry).lower(),
    )


def chain_in(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The chain Hermes uses for this config.yaml (`get_fallback_chain`)."""
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for key in (KEY, LEGACY):
        for entry in entries(config.get(key)):
            if identity(entry) not in seen:
                seen.add(identity(entry))
                chain.append(entry)
    return chain


def is_set(config: dict[str, Any]) -> bool:
    """The profile has a chain of its own (even an empty `[]`: a choice)."""
    return config.get(KEY) is not None or config.get(LEGACY) is not None


def value_for(wanted: list[dict[str, str]], have: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The list written for one profile: each wanted route, with the profile's own
    extra keys for a route it already has (key_env, api_mode, ...), so a save
    never drops what was set in Hermes itself."""
    mine = {identity(e): e for e in have}
    out: list[dict[str, Any]] = []
    for entry in wanted:
        found = mine.get(identity(entry))
        if found is not None:
            out.append(found)
            continue
        plain: dict[str, Any] = {"provider": entry["provider"], "model": entry["model"]}
        if entry.get("base_url"):
            plain["base_url"] = entry["base_url"]
        out.append(plain)
    return out


def as_argument(chain: list[dict[str, Any]]) -> str:
    """`hermes config set fallback_providers <this>`: Hermes parses a JSON/YAML
    list literal into a real list (hermes_cli/config.py:3377
    `_coerce_config_set_value`)."""
    return json.dumps(chain)
