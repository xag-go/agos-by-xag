"""Settings → General → Hermes update: Check Update, and the update itself.

The check is read-only and Hermes's own answer (engine/hermes_update.check):
what is installed, what the stable channel offers, whether AGOS still fits it
(the contract checker on the target's source), and the target's changes. Its
result sits in `hermes_update.check` for the card and the popup.

"Do the update" runs docs/hermes-upgrade.md section 2 in order, in a background
thread, its progress in `hermes_update.state` (the web polls it and shows the
maintenance card; the chats' gateways are stopped, so everything waits, and
Hermes resumes what a restart cut):

  backups → gateways off → `hermes update` → every home prepared → gateways on

A failure before any gateway ran the new code rolls the code back (the stores
haven't moved); after that it stops where it is and says so — restoring moved
stores is the owner's call with the backups just written (docs section 3).
AGOS's own code never changes here: what the release makes redundant in AGOS is
listed by the check for the owner to ask for in chat.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine import hermes_update as engine_update
from agos_core.engine.hermes import EngineError, HermesEngine

log = logging.getLogger("agos.hermes_update")


def require_engine(core: Core) -> HermesEngine:
    if core.engine is None:
        raise ActionError("The engine isn't set up on this machine.")
    return core.engine


KEY_CHECK = "hermes_update.check"  # the last Check Update's answer
KEY_STATE = "hermes_update.state"  # the running (or last) update's progress

CHECK_FRESH_S = 2 * 3600  # "Do the update" wants a check newer than this
_RUNNING = ("starting", "backups", "gateways-off", "install", "prepare", "gateways-on")
_LOCK = threading.Lock()  # one update at a time in this process


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def status(core: Core) -> dict[str, Any]:
    return {
        "check": get_setting(core.db, KEY_CHECK, None),
        "state": get_setting(core.db, KEY_STATE, None),
    }


def run_check(core: Core) -> dict[str, Any]:
    """The Check Update button (read-only; nothing installed, nothing restarted)."""
    engine = require_engine(core)
    state = get_setting(core.db, KEY_STATE, None)
    if isinstance(state, dict) and state.get("phase") in _RUNNING:
        raise ActionError("An update is running.")
    found = engine_update.check(engine)
    record = {
        "at": _now(),
        "current": {"version": found.current.version, "sha": found.current.sha},
        "target": (
            {"version": found.target.version, "sha": found.target.sha} if found.target else None
        ),
        "fits": found.fits,
        "report": found.report,
        "news": found.news,
    }
    set_setting(core.db, KEY_CHECK, record)
    return record


def start_update(core: Core) -> dict[str, Any]:
    """The popup's "do the update": checked, fitting and fresh, or it refuses."""
    require_engine(core)
    state = get_setting(core.db, KEY_STATE, None)
    if isinstance(state, dict) and state.get("phase") in _RUNNING:
        raise ActionError("An update is already running.")
    check = get_setting(core.db, KEY_CHECK, None)
    if not isinstance(check, dict) or not check.get("target"):
        raise ActionError("Check for an update first.")
    age = time.time() - datetime.fromisoformat(check["at"]).timestamp()
    if age > CHECK_FRESH_S:
        raise ActionError("The check is old — check again first.")
    if not check.get("fits"):
        raise ActionError("AGOS doesn't fit that release yet — it needs AGOS changes first.")
    if not _LOCK.acquire(blocking=False):
        raise ActionError("An update is already running.")
    state = {
        "phase": "starting",
        "started_at": _now(),
        "from": check["current"],
        "target": check["target"],
        "steps": [],
        "error": None,
    }
    set_setting(core.db, KEY_STATE, state)
    threading.Thread(target=_run, args=(core, state), name="hermes-update", daemon=True).start()
    return state


def _step(core: Core, state: dict[str, Any], phase: str, detail: str = "") -> None:
    state["phase"] = phase
    state["steps"].append({"name": phase, "at": _now(), "detail": detail})
    set_setting(core.db, KEY_STATE, state)
    log.info("Hermes update: %s%s", phase, f" — {detail}" if detail else "")


def _run(core: Core, state: dict[str, Any]) -> None:
    try:
        _update(core, state)
    except BaseException:
        log.exception("Hermes update failed")
    finally:
        _LOCK.release()


def _update(core: Core, state: dict[str, Any]) -> None:
    from agos_core.actions import backups as backups_actions

    engine = require_engine(core)
    target = engine_update.Release(**state["target"])
    before = engine_update.Release(**state["from"])
    rows = workspaces_repo.list_workspaces(core.db)
    ids = [row.id for row in rows]
    homes = [engine.root(ws) for ws in ids]
    installed = False
    started: list[str] = []
    try:
        # 1. Backups: Hermes's own, of the shared home and every root; and AGOS's
        # scheduled backup file too when a backup password is set.
        _step(core, state, "backups")
        stamp = time.strftime("%Y%m%dT%H%M", time.gmtime())
        into = backups_actions.backup_dir(core) / f"hermes-upgrade-{stamp}"
        engine_update.backup_roots(engine, homes, into)
        try:
            backups_actions.run_backup(core)
        except ActionError as error:  # no password set: the Hermes zips stand alone
            log.info("Hermes update: AGOS backup skipped (%s)", error)

        # 2. Nothing may run the old code during the swap.
        _step(core, state, "gateways-off")
        for ws in ids:
            engine.stop(ws)

        # 3. Hermes's own update, pinned to the checked release.
        _step(core, state, "install", f"→ v{target.version}")
        engine_update.install(engine, target)
        installed = True

        # 4. Every home ready on the new code before anyone talks to it; the memory
        # plugin where a profile names it (memory_plugin owns that install).
        from agos_core.actions import memory_plugin

        _step(core, state, "prepare")
        engine_update.prepare_home(engine, engine.settings.hermes_home)
        for ws, home in zip(ids, homes, strict=True):
            engine_update.prepare_home(engine, home)
            memory_plugin.ensure(core, ws)
            profiles = home / "profiles"
            if profiles.is_dir():
                for member in sorted(
                    p for p in profiles.iterdir() if (p / "config.yaml").is_file()
                ):
                    engine_update.prepare_home(engine, member)
                    memory_plugin.ensure(core, f"{ws}--{member.name}")

        # 5. The gateways back (Hermes's own services; from here its stores move).
        _step(core, state, "gateways-on")
        for ws in ids:
            engine.serve(ws)
            started.append(ws)

        state["phase"] = "done"
        state["finished_at"] = _now()
        state["report"] = {
            "from": before.version,
            "to": target.version,
            "backups": str(into),
            "workspaces": len(ids),
        }
        set_setting(core.db, KEY_STATE, state)
        set_setting(core.db, KEY_CHECK, None)
        log.info("Hermes update done: v%s → v%s", before.version, target.version)
    except (EngineError, OSError) as error:
        _failed(core, state, engine, before, ids, error, installed=installed, started=started)


def _failed(
    core: Core,
    state: dict[str, Any],
    engine: Any,
    before: engine_update.Release,
    ids: list[str],
    error: Exception,
    *,
    installed: bool,
    started: list[str],
) -> None:
    log.error("Hermes update failed at %s: %s", state.get("phase"), error)
    rolled_back = False
    if installed and not started:
        # No gateway ran the new code: its stores haven't moved, the old release
        # is safe to put back.
        try:
            engine_update.roll_back_code(engine, before)
            rolled_back = True
        except (EngineError, OSError) as rollback_error:
            log.error("Hermes update: rollback failed too: %s", rollback_error)
    for ws in ids:
        if ws in started:
            continue
        try:
            engine.serve(ws)
        except (EngineError, OSError) as serve_error:
            log.error("Hermes update: %s's gateway didn't come back: %s", ws, serve_error)
    state["phase"] = "failed"
    state["finished_at"] = _now()
    state["error"] = str(error)
    state["rolled_back"] = rolled_back
    set_setting(core.db, KEY_STATE, state)
