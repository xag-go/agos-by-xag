"""Which setting paths hold a secret, and masking them before anything leaves.
Must not: read Hermes.

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Any

__all__ = [
    "MASK",
    "Path_",
    "holds_secret",
    "masked",
    "secret_paths",
]

# --- secrets -----------------------------------------------------------------

MASK = "(set — hidden)"

Path_ = tuple[str | int, ...]


def secret_paths(found: Any) -> set[Path_]:
    """Hermes's answer of where a config holds secrets (engine.hermes_secrets: the
    paths its redact_config_value masks) as a set of paths."""
    out: set[Path_] = set()
    for path in found or ():
        if isinstance(path, list):
            out.add(tuple(p if isinstance(p, int) else str(p) for p in path))
    return out


def masked(value: Any, secrets: AbstractSet[Path_] | None = None, at: str | Path_ = ()) -> Any:
    """A value with every secret inside it hidden: each path Hermes's own masker
    hides (`secrets`, relative to the config's top; `at`: where `value` sits) shows
    AGOS's MASK (never Hermes's head...tail preview: an inline api_key in a provider
    entry never reaches the web)."""
    base: Path_ = tuple(at.split(".")) if isinstance(at, str) else tuple(at)
    if not secrets:
        return value
    if base in secrets and value not in (None, ""):
        return MASK
    if isinstance(value, dict):
        return {k: masked(v, secrets, (*base, str(k))) for k, v in value.items()}
    if isinstance(value, list):
        return [masked(v, secrets, (*base, i)) for i, v in enumerate(value)]
    return value


def holds_secret(secrets: AbstractSet[Path_], at: str) -> bool:
    """Some path Hermes masks lies at or inside this key."""
    base = tuple(at.split("."))
    return any(p[: len(base)] == base for p in secrets)
