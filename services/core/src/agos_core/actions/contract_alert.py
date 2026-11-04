"""Hermes contract broken: the owner hears it, not only a log file.

When a Hermes internal AGOS relies on (one entry of engine/hermes_contract.py)
fails — inside Hermes (the agos-guard plugin posts `contract-broken`) or in a
helper script AGOS runs in Hermes's runtime (`hermes_contract.ran`) — AGOS keeps
failing closed as before, and:

- an ERROR "Hermes contract broken: <name>" lands in the workspace Log
  (`agos.*` errors go to system_log);
- the owner gets the same, in the Co-Founder's chat in AGOS and on his phone (the
  path every alert takes: `owner_needs.tell_owner` + `owner_needs.push`, like a
  card's token warning);

at most once per name per gateway start (the plugin sends its gateway's id: its
pid and start time from Hermes's gateway_state.json) — kept in app_settings, so a
core restart doesn't tell him again for the same gateway.
"""

from __future__ import annotations

import logging
import threading

from agos_core.context import Core

log = logging.getLogger("agos.hermes_contract")

TOLD = "hermes_contract_told:"  # app_settings key + workspace id: ["<name>@<gateway>"]
KEEP = 300
_lock = threading.Lock()


def text_for(name: str) -> str:
    from agos_core.engine.hermes_contract import CONTRACT

    feature = next((u.feature for u in CONTRACT if u.key == name), "")
    what = f" — {feature} may not work" if feature else ""
    return (
        f"⚠️ Hermes contract broken: {name}{what}. AGOS is refusing or skipping it "
        "safely for now; the installed Hermes no longer has it as AGOS uses it "
        "(see Log)."
    )


def _first_time(core: Core, workspace_id: str, key: str) -> bool:
    from agos_core.db.app_settings import get_setting, set_setting
    from agos_core.db.connection import transaction

    with _lock, transaction(core.db):
        told = get_setting(core.db, TOLD + workspace_id, [])
        told = [str(t) for t in told] if isinstance(told, list) else []
        if key in told:
            return False
        set_setting(core.db, TOLD + workspace_id, [*told, key][-KEEP:])
        return True


def tell(core: Core, workspace_id: str, name: str, detail: str = "", gateway: str = "") -> bool:
    """One contract break in this workspace (its gateway `gateway`, "" = AGOS's
    core). True when it was told now (the first time for name + gateway)."""
    from agos_core.actions.services.channel import owner_needs

    key = f"{name}@{gateway or 'core'}"
    if not _first_time(core, workspace_id, key):
        return False
    if gateway:  # from inside Hermes (AGOS's core logged its own already: broken())
        log.error(
            "Hermes contract broken: %s (workspace %s, gateway %s): %s",
            name,
            workspace_id,
            gateway,
            (detail or "failed")[:500],
            extra={"agos_quiet": True},  # told just below (Settings → Errors counts it)
        )
    text = text_for(name)
    message_id = owner_needs.tell_owner(core, workspace_id, text)
    owner_needs.push(
        core,
        workspace_id,
        text,
        f"msg:{message_id}" if message_id else f"contract:{key}",
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )
    return True


def owner_workspace(core: Core) -> str | None:
    """Where a break with no workspace of its own is told: the owner's first
    workspace (one owner, one phone)."""
    row = core.db.execute(
        "SELECT id FROM workspaces ORDER BY created_at, id LIMIT 1",
    ).fetchone()
    return str(row[0]) if row else None


def install(core: Core) -> None:
    """AGOS's core reports its own breaks (helper scripts in Hermes's runtime) here."""
    from agos_core.engine import hermes_contract

    def notify(name: str, detail: str, workspace_id: str | None) -> None:
        ws = workspace_id or owner_workspace(core)
        if ws is not None:
            tell(core, ws, name, detail)

    notify.agos_core = core  # type: ignore[attr-defined]
    hermes_contract.notifiers[:] = [
        n for n in hermes_contract.notifiers if not hasattr(n, "agos_core")
    ]
    hermes_contract.notifiers.append(notify)


def uninstall() -> None:
    from agos_core.engine import hermes_contract

    hermes_contract.notifiers[:] = [
        n for n in hermes_contract.notifiers if not hasattr(n, "agos_core")
    ]
