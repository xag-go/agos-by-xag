"""The owner's account pause (General settings → Usage, "pause at"): while any
logged-in account is at that share of its limit, everything new waits. Running
work is never killed.

The pause IS Hermes's own: `hermes pause --reason` writes the ESTOP sentinel at
the workspace root ($HERMES_HOME/ESTOP, agent/estop.py), and Hermes itself holds
its cron scheduler, its Kanban dispatcher and new gateway turns (chats answer
again after `hermes resume`). AGOS only runs the two commands and reads the
sentinel's reason, so it resumes nothing but its own pause: one the owner set by
hand (`hermes pause`, `touch ESTOP`) is left exactly as he made it.
At 100% Hermes also holds work by itself (cron `quota_hold`, the Kanban's
rate-limit cooldown); this holds it at the line the owner picks.

Before Step 33 AGOS paused by emptying `kanban.dispatch_profiles` and pausing
every cron job with PAUSE_REASON; `move_old_pause` (at start, idempotent) puts both
back once, so nothing stays held by the old way.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from pathlib import Path

from agos_core.context import Core
from agos_core.engine.cron import PAUSE_REASON, CronError
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger(__name__)

EVERY_SECONDS = 60
_last_check: float | None = None
# The old pause's mark in a root's config.yaml (only move_old_pause still reads it).
_LEGACY_PAUSED = re.compile(
    r"^kanban:[ \t]*\n(?:(?:[ \t]+.*)?\n)*?[ \t]+dispatch_profiles:[ \t]*\[\][ \t]*$", re.M
)


def reason(core: Core) -> str | None:
    """Why new work waits now ("Claude current week at 90%"), or None."""
    engine = core.engine
    if engine is None:
        return None
    from agos_core.actions.services.settings.account_prefs import usage_prefs
    from agos_core.engine import limits, models

    prefs = usage_prefs(core)
    if not prefs.enabled:
        return None
    try:
        accounts = limits.account_limits(engine.settings, models.hermes_python(engine.settings))
    except (RuntimeError, OSError):
        return None  # can't read the limits: never block work on a guess
    for account in accounts:
        for window in account.windows:
            if window.used_percent is not None and window.used_percent >= prefs.pause_at:
                return f"{account.label} {window.label.lower()} at {window.used_percent:.0f}%"
    return None


def _sentinel(core: Core, workspace_id: str) -> Path:
    assert core.engine is not None
    return core.engine.profile_home(workspace_id) / "ESTOP"


def held(core: Core, workspace_id: str) -> bool:
    """The root is paused (Hermes's ESTOP sentinel), whoever paused it."""
    if core.engine is None:
        return False
    return _sentinel(core, workspace_id).exists()


def paused_by_agos(core: Core, workspace_id: str) -> bool:
    """True only for AGOS's own pause: the sentinel exists and its reason is ours.
    A hand-made pause (no body, another reason, corrupt JSON) is the owner's."""
    if core.engine is None:
        return False
    try:
        body = json.loads(_sentinel(core, workspace_id).read_text() or "{}")
    except OSError:
        return False  # no sentinel: not paused
    except ValueError:
        return False  # not ours: `touch ESTOP` still pauses Hermes (fail safe)
    return isinstance(body, dict) and str(body.get("reason") or "").startswith(PAUSE_REASON)


def paused(core: Core, workspace_id: str) -> bool:
    """Is the workspace's Hermes paused at all (AGOS's pause or the owner's own)."""
    if core.engine is None:
        return False
    try:
        return _sentinel(core, workspace_id).exists()
    except OSError:
        return False


def apply(core: Core, why: str | None) -> list[str]:
    """Hermes's own pause follows `why` in every active workspace. Returns the
    workspaces whose state changed."""
    from agos_core.db.activity import add_activity

    if core.engine is None:
        return []
    changed: list[str] = []
    for row in core.db.execute(
        "SELECT id FROM workspaces WHERE deleted_at IS NULL AND archived_at IS NULL"
    ).fetchall():
        workspace_id = str(row["id"])
        if not (core.engine.profile_home(workspace_id) / "config.yaml").is_file():
            continue
        moved = False
        try:
            if why and not paused(core, workspace_id):
                hermes_cli.cli(
                    core.engine, workspace_id, "pause", "--reason", f"{PAUSE_REASON}: {why}"
                )
                moved = True
            elif not why and paused_by_agos(core, workspace_id):
                hermes_cli.cli(core.engine, workspace_id, "resume")
                moved = True
        except EngineError as error:
            log.warning("account pause: %s not switched: %s", workspace_id, error)
        if moved:
            changed.append(workspace_id)
            add_activity(
                core.db,
                workspace_id,
                kind="usage.paused" if why else "usage.resumed",
                text=(
                    f"Everything new waits: {why} (your pause level). Running work "
                    "finishes; chats answer again once usage is back under it."
                    if why
                    else "Your accounts are under the pause level again: new work starts."
                ),
            )
    return changed


def move_old_pause(core: Core) -> int:
    """The pre-Step-33 pause put back once, at start (idempotent): a root whose
    `kanban.dispatch_profiles` the old pause emptied gets its real list, and every
    cron job still held with PAUSE_REASON is resumed. Hermes's own pause (the
    ESTOP sentinel) takes over on the next `keep` tick if an account is still at
    the owner's level."""
    from agos_core.actions import agent_profiles
    from agos_core.actions import automations as actions

    if core.engine is None:
        return 0
    moved = 0
    bridge = actions.cron_bridge(core)
    for row in core.db.execute(
        "SELECT id FROM workspaces WHERE deleted_at IS NULL AND archived_at IS NULL"
    ).fetchall():
        workspace_id = str(row["id"])
        config = core.engine.profile_home(workspace_id) / "config.yaml"
        try:
            held = config.is_file() and bool(_LEGACY_PAUSED.search(config.read_text() + "\n"))
        except OSError:
            held = False
        wanted = agent_profiles.dispatch_list(core, workspace_id) if held else "[]"
        # Still [] when every agent is off-hours (actions/work_hours.py): nothing to put back.
        if held and wanted != "[]":
            try:
                hermes_cli.cli(
                    core.engine,
                    workspace_id,
                    "config",
                    "set",
                    "kanban.dispatch_profiles",
                    wanted,
                )
                moved += 1
            except EngineError as error:
                log.warning("legacy pause: board of %s not released: %s", workspace_id, error)
        jobs = actions.hermes_jobs(core, workspace_id) if bridge is not None else None
        for job in (jobs or {}).values():
            if bridge is None:
                break
            if not job.get("enabled") and job.get("paused_reason") == PAUSE_REASON:
                home = actions.home_of(core, workspace_id, job)
                with contextlib.suppress(CronError, OSError):
                    bridge.resume(home, str(job["id"]))
                    moved += 1
    if moved:
        log.info("legacy account pause moved to Hermes's own pause: %d put back", moved)
    return moved


def keep(core: Core, now: float | None = None) -> list[str]:
    """The automation loop's check, at most once a minute."""
    global _last_check
    at = time.monotonic() if now is None else now
    if _last_check is not None and at - _last_check < EVERY_SECONDS:
        return []
    _last_check = at
    return apply(core, reason(core))
