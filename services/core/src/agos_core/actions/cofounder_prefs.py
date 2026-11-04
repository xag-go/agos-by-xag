"""The owner's account-wide preferences as Co-Founder chat actions (engine/
cofounder_parity/): his timezone, his notification rules and AGOS's Errors list
(Settings → General, Notifications, Errors), and the apps he trusts (Settings →
Autonomy). Each one calls the same AGOS action as
the owner's page and returns what its card's Undo needs (`before`);
actions/cofounder_more.py lists them with the other kinds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from agos_core.actions.errors import ActionError
from agos_core.context import Core

Fields = dict[str, Any]
Result = dict[str, Any]


def _number(value: Any) -> int:
    try:
        return int(str(value).strip().lstrip("#"))
    except (TypeError, ValueError) as error:
        raise ActionError("Give the error as a number.") from error


def _timezone(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import owner_time
    from agos_core.actions.owner_time import save_timezone

    before = owner_time.owner_zone(core)
    save_timezone(core, str(p.get("timezone") or "").strip())
    return {"before": before}


def _undo_timezone(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions.owner_time import save_timezone

    save_timezone(core, str(r["before"]))


def _notifications(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions.notification_rules import EVENTS, delivery_for, save_notifications

    before = {e: delivery_for(core, e) for e in EVENTS}
    save_notifications(core, {**before, **{str(k): str(v) for k, v in dict(p["rules"]).items()}})
    return {"before": before}


def _undo_notifications(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions.notification_rules import save_notifications

    save_notifications(core, dict(r["before"]))


def _error_status(core: Core, ws: str, p: Fields, status: Literal["open", "fixed"]) -> Result:
    """An error of this workspace or of AGOS itself (another workspace's stays its own)."""
    from agos_core.actions import error_issues

    issue = _number(p.get("error"))
    found = error_issues.get(core.db, issue)
    if found is None or found.workspace_id not in (None, ws):
        raise ActionError("There is no such error in this workspace or in AGOS itself.", 404)
    return {
        "error": issue,
        "before": error_issues.set_status(core.db, issue, status, workspace_id=ws),
    }


def _error_fixed(core: Core, ws: str, p: Fields) -> Result:
    return _error_status(core, ws, p, "fixed")


def _error_open(core: Core, ws: str, p: Fields) -> Result:
    return _error_status(core, ws, p, "open")


def _undo_error_status(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import error_issues

    before: Literal["open", "fixed"] = "fixed" if r.get("before") == "fixed" else "open"
    error_issues.set_status(core.db, int(r["error"]), before, workspace_id=ws)


def _set_flag(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import flags

    name = str(p.get("flag") or "").strip()
    value = flags.parse_on(p.get("on"))
    return {"flag": name, "before": flags.set_flag(core, name, value)}


def _undo_flag(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import flags

    before = r.get("before")
    flags.restore_flag(core, str(r["flag"]), None if before is None else bool(before))


def _trusted_apps(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import trusted_apps

    raw = p.get("apps")
    names = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    return {"before": trusted_apps.save(core, ws, [str(n) for n in names])}


def _undo_trusted_apps(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import trusted_apps

    trusted_apps.save(core, ws, [str(n) for n in r.get("before") or []])


DOES: dict[str, Callable[[Core, str, Fields], Result]] = {
    "set_timezone": _timezone,
    "set_notifications": _notifications,
    "mark_error_fixed": _error_fixed,
    "reopen_error": _error_open,
    "set_flag": _set_flag,
    "set_trusted_apps": _trusted_apps,
}
UNDOES: dict[str, Callable[[Core, str, Result], None]] = {
    "set_timezone": _undo_timezone,
    "set_notifications": _undo_notifications,
    "mark_error_fixed": _undo_error_status,
    "reopen_error": _undo_error_status,
    "set_flag": _undo_flag,
    "set_trusted_apps": _undo_trusted_apps,
}
