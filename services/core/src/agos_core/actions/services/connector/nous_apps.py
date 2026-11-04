"""The owner's Nous hosted apps: whether Nous signed him in (asked of Hermes, kept a while).
Must not: switch an app in a workspace.

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import threading
import time
import weakref
from pathlib import Path

import agos_core.engine.hermes as _hermes_engine
from agos_core.context import Core
from agos_core.engine import hermes_contract, read_cache
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python, hermes_repo
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway import process as hermes_process

__all__ = [
    "nous_signed_in",
    "nous_status",
    "read_ahead_nous",
]

# ---- Nous hosted apps -----------------------------------------------------------------

_NOUS_PROBE = """
import json
from tools.connectors.gateway.config import connectors_available
from hermes_cli.nous_account import get_nous_portal_account_info
info = get_nous_portal_account_info()
print("AGOS-JSON " + json.dumps({"logged_in": bool(info.logged_in),
                                  "available": bool(connectors_available())}))
"""
# Hermes's answer per core, keyed on the files its probe reads in the shared home
# (auth.json: the Nous login; config.yaml / .env: the connectors switch), so a login
# or logout in Hermes is asked at once. Nous opens apps for an account on its side,
# so the answer is also asked again every five minutes, behind the page (it gets
# the last answer at once). Hermes runs the probe in about a second, and it may ask
# Nous's portal when the login's token is old.
_NOUS_KEPT_S = 300
_NOUS: dict[int, read_cache.ReadCache[tuple[bool, str | None]]] = {}
_NOUS_LOCK = threading.Lock()


def _nous_kept(core: Core) -> read_cache.ReadCache[tuple[bool, str | None]]:
    with _NOUS_LOCK:
        found = _NOUS.get(id(core))
        if found is None:
            found = _NOUS[id(core)] = read_cache.ReadCache("nous_status", max_entries=8)
            weakref.finalize(core, _NOUS.pop, id(core), None)
        return found


def nous_status(core: Core, *, fresh: bool = False) -> tuple[bool, str | None]:
    """(available, why not). Read-only: never logs in or refreshes. `fresh`: Hermes
    is asked now (a login flow, the Co-Founder's check)."""
    if core.engine is None:
        return False, "The engine is off."
    home = core.engine.settings.host_home / ".hermes"
    key = read_cache.file_stamp(home / "auth.json", home / "config.yaml", home / ".env")
    kept = _nous_kept(core)
    if fresh:
        kept.drop(key)
    return kept.get(
        key, int(time.time() // _NOUS_KEPT_S), lambda: _ask_nous(core), stale_ok=not fresh
    )


def read_ahead_nous(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): Hermes's Nous apps state for
    Settings → Connectors and each workspace's Apps page."""
    nous_status(core)


def _ask_nous(core: Core) -> tuple[bool, str | None]:
    """Hermes's own answer: its Nous login and whether Nous opened apps for it."""
    assert core.engine is not None
    try:
        python = hermes_python(core.engine.settings)
        off_loop("hermes nous status")
        done = hermes_process.run_process(
            [python, "-c", _NOUS_PROBE],
            timeout=hermes_wait(60),
            env=_hermes_engine.with_runtime(
                {"HOME": str(core.engine.settings.host_home), "PATH": "/usr/bin:/bin"}
            ),
            cwd=str(hermes_repo(core.engine.settings) or Path(python).parent),
        )
        hermes_contract.ran(done)
        lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")]
        data = json.loads(lines[-1][9:]) if lines else {}
    except (OSError, hermes_process.TimeoutExpired, ValueError):
        data = {}
    if not data:
        return False, "Hermes didn't answer."
    if not data.get("logged_in"):
        return False, "Sign in to Nous Portal first."
    if not data.get("available"):
        return False, "Your Nous account is logged in, but Nous hasn't opened apps for it yet."
    return True, None


def nous_signed_in(core: Core) -> bool:
    """Hermes has a Nous Portal login (apps may still be closed for the account)."""
    available, why = nous_status(core, fresh=True)
    return available or (why or "").startswith("Your Nous account is logged in")
