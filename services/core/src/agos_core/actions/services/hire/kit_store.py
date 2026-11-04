"""Where a member's kit is kept (its Hermes profile fact) and the kits waiting for a hire to finish; the kit's keys.
Must not: decide what a kit holds or provision it.

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import NotFoundError
from agos_core.context import Core
from agos_core.engine import profile_meta

__all__ = [
    "CHOICE_WORDS",
    "FIX_KEY",
    "KIT_FACT",
    "ONBOARD_KEY",
    "OWNER_CHOICES",
    "READY_KEY",
    "expect",
    "forget_pending",
    "kit_members",
    "kit_of",
]

log = logging.getLogger("agos.hire_kit")

KIT_FACT = "kit"  # profile.yaml ui_meta.agos.kit
READY_KEY = "agos-ready:"  # + member + ":" + digest: the Co-Founder's 'Make it ready' card
ONBOARD_KEY = "agos-onboard:"  # + member + ":" + n: the member's onboarding test
FIX_KEY = "agos-onboard-fix:"  # + member + ":" + n: the Co-Founder's fix after a failed test
_CLOSED = frozenset({"done", "archived"})
OWNER_CHOICES = ("not_needed", "start_anyway", "skip_test")
CHOICE_WORDS = {
    "not_needed": "Not needed",
    "start_anyway": "Start anyway",
    "skip_test": "Skip test",
}

# A kit made before the member's profile exists (the approve): its SOUL.md is
# written while the profile is made, so the 'Your team' section reads it from here
# until profile.yaml has it.
_pending: dict[tuple[str, str], dict[str, Any]] = {}
_pending_lock = threading.Lock()
_advance_locks: dict[str, threading.Lock] = {}
_advance_guard = threading.Lock()


# ---- the kit ---------------------------------------------------------------------------


def _home(core: Core, workspace_id: str, member: str) -> Path | None:
    from agos_core.actions import team

    if core.engine is None:
        return None
    return team.home(core, workspace_id, member)


def kit_of(core: Core, workspace_id: str, member: str) -> dict[str, Any] | None:
    """The member's kit as its profile has it (None: hired without one)."""
    home = _home(core, workspace_id, member)
    if home is not None and (home / profile_meta.PROFILE_YAML).is_file():
        found = profile_meta.agos(profile_meta.read(home)).get(KIT_FACT)
        if isinstance(found, dict):
            return found
    with _pending_lock:
        pending = _pending.get((workspace_id, member))
    return dict(pending) if pending is not None else None


def _store(core: Core, workspace_id: str, member: str, kit: dict[str, Any]) -> None:
    home = _home(core, workspace_id, member)
    if home is None:
        raise NotFoundError("This member")
    with profile_meta.locked(home):
        facts = profile_meta.agos(profile_meta.read_fresh(home))
        facts[KIT_FACT] = kit
        profile_meta.write(home, agos_facts=facts)
    with _pending_lock:
        _pending.pop((workspace_id, member), None)


def expect(workspace_id: str, member: str, kit: dict[str, Any]) -> None:
    """The kit of a member about to be made (its SOUL.md is written meanwhile)."""
    with _pending_lock:
        _pending[(workspace_id, member)] = dict(kit)


def forget_pending(workspace_id: str, member: str) -> None:
    with _pending_lock:
        _pending.pop((workspace_id, member), None)


def _has_kit(core: Core, workspace_id: str, member: str) -> bool:
    home = _home(core, workspace_id, member)
    if home is None:
        return False
    return isinstance(profile_meta.agos(profile_meta.read(home)).get(KIT_FACT), dict)


def kit_members(core: Core, workspace_id: str) -> list[str]:
    """The members on the team that have a kit (profile reads only)."""
    from agos_core.actions import team

    if core.engine is None:
        return []
    return [n for n in team.names(core, workspace_id) if _has_kit(core, workspace_id, n)]
