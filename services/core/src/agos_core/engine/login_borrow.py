"""Whether a workspace's root has a model login of its own, as Hermes reads it.

Owns: one home's sign-ins read by Hermes's own functions (engine.hermes_logins), the
"a login of its own for this provider" rule, and whether the root must keep reading
Claude Code's file for a subscription it has no login of its own for yet.

Must not: write any Hermes setting (actions/general_sync.py does, through Hermes).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = ["borrowing_needed", "hermes_logins", "own_login"]

log = logging.getLogger("agos.general_sync")


def hermes_logins(engine: Any, home: Path, *, status: bool = False) -> dict[str, Any] | None:
    """What this home is signed in with, read by Hermes's own functions
    (engine.hermes_logins: its config's model provider, its persisted credential
    pool with each entry's source, its saved sign-ins, `hermes auth status`).
    None when Hermes couldn't answer."""
    from agos_core.engine.hermes import EngineError

    try:
        found: dict[str, Any] = engine.hermes_logins(home, status=status)
    except (EngineError, OSError, ValueError) as error:
        log.info("Hermes's logins in %s not read: %s", home, error)
        return None
    return found


def own_login(found: dict[str, Any], slug: str) -> bool:
    """The home holds a login of its own for this provider: a pool entry whose
    source Hermes doesn't call borrowed (is_borrowed_credential_source; a line of
    the home's own .env counts as its own), or a sign-in Hermes saved there."""
    return any(
        e.get("provider") == slug and not e.get("borrowed") for e in found.get("pool") or []
    ) or slug in (found.get("signed_in_state") or [])


def borrowing_needed(engine: Any, home: Path) -> bool:
    """The root's model runs on a subscription it has no login of its own for yet:
    it keeps reading Claude Code's file until the owner connects it. When Hermes
    can't say, the root keeps borrowing (its model stays reachable)."""
    from agos_core.engine.models import per_workspace

    found = hermes_logins(engine, home)
    if found is None:
        return True
    provider = str(found.get("provider") or "")
    # A subscription each workspace signs in to on its own (its Hermes auth type).
    return per_workspace(provider, str(found.get("auth_type") or "")) and not own_login(
        found, provider
    )
