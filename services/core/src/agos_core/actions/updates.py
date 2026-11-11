"""Settings → General → Updates: one check and one run for both parts of an
install — AGOS itself (actions/agos_update) and the engine (actions/hermes_update).

The check runs both parts' own read-only checks and answers with one owner-facing
verdict: `ready` and a short `note` that never names which part is new. The run
starts AGOS's update first when it has one (its own backups, build and rollback;
it also brings the engine commit that release pins); only when AGOS is current
does it start the engine's update (its own backups, fit check and rollback). Each
part's existing endpoint stays; this module adds nothing to how either updates.

Owns: the combined verdict and the choice of which part runs. Must not: run git,
run the engine, or write either part's state (the two actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import agos_update, hermes_update
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting

__all__ = ["run_check", "start_update", "status"]

# Owner-facing words (one rule: never the engine's name).
READY = "An update is ready."
UP_TO_DATE = "You're up to date."
NO_ENGINE = "The engine isn't set up on this machine."
BUSY = "An update is already running."
CHECK_FIRST = "Check for an update first."


def status(core: Core) -> dict[str, Any]:
    """Both parts' progress, as the two old endpoints gave it."""
    return {"agos": agos_update.status(core), "engine": hermes_update.status(core)}


def _part_check(core: Core, check: Any) -> tuple[dict[str, Any] | None, str | None]:
    """One part's check record, or why it has none. A running update refuses the
    whole check (both parts' checks already refuse it with this wording)."""
    try:
        return check(core), None
    except ActionError as error:
        if "update is" in str(error) and "running" in str(error):
            raise ActionError(BUSY) from error
        return None, str(error)


def run_check(core: Core) -> dict[str, Any]:
    """The Check update button: both parts' read-only checks, one verdict."""
    agos_rec, agos_note = _part_check(core, agos_update.run_check)
    engine_rec: dict[str, Any] | None
    engine_note: str | None
    if core.engine is None:
        engine_rec, engine_note = None, NO_ENGINE
    else:
        engine_rec, engine_note = _part_check(core, hermes_update.run_check)
    if agos_rec is None and engine_rec is None:
        raise ActionError(f"The check didn't run: {agos_note} {engine_note}".strip())
    ready = bool((agos_rec or {}).get("target") or (engine_rec or {}).get("target"))
    return {
        "ready": ready,
        "note": READY if ready else UP_TO_DATE,
        "agos": agos_rec,
        "agos_note": agos_note,
        "engine": engine_rec,
        "engine_note": engine_note,
    }


def start_update(core: Core) -> dict[str, Any]:
    """The Update now button: AGOS's update when its check found one (the engine
    commit that release pins comes with it), else the engine's own update."""
    agos_check = get_setting(core.db, agos_update.KEY_CHECK, None)
    if isinstance(agos_check, dict) and agos_check.get("target"):
        return {"part": "agos", "state": agos_update.start_update(core)}
    engine_check = get_setting(core.db, hermes_update.KEY_CHECK, None)
    if isinstance(engine_check, dict) and engine_check.get("target"):
        return {"part": "engine", "state": hermes_update.start_update(core)}
    raise ActionError(CHECK_FIRST)
