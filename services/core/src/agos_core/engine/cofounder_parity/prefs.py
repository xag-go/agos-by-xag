"""The owner's account-wide preferences as Co-Founder kinds (actions/cofounder_prefs.py
runs them): part of the Co-Founder's KINDS (cofounder_parity/catalog.py) and of
the web map's DO (cofounder_parity/web_actions.py).

Must not: run a kind (actions/cofounder_prefs.py) or merge the catalogue (catalog.py).
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import WORKSPACE, Kind

__all__ = [
    "PREFS_DO",
    "PREFS_KINDS",
]

PREFS_KINDS: dict[str, Kind] = {
    "set_timezone": Kind(WORKSPACE, ("timezone",), "Your timezone: {timezone}", "timezone"),
    "set_notifications": Kind(
        WORKSPACE,
        ("rules",),
        "Notifications",
        "rules (object: event -> delivery, as Settings → Notifications)",
        structured=("rules",),
    ),
    # ---- Settings → Errors (AGOS's own errors, actions/error_issues.py) -----------------
    "mark_error_fixed": Kind(
        WORKSPACE,
        ("error",),
        "Mark AGOS error #{error} fixed",
        "error (its number in Settings → Errors): it opens again by itself if it happens again",
    ),
    "reopen_error": Kind(
        WORKSPACE, ("error",), "Open AGOS error #{error} again", "error (its number)"
    ),
    # ---- Settings → General → Labs (actions/flags.py) -----------------------------------
    "set_flag": Kind(
        WORKSPACE,
        ("flag", "on"),
        "Labs switch {flag}: {on}",
        "flag (its name in Settings → General → Labs), on (true = on, false = off)",
    ),
    # ---- Settings → Autonomy → Trusted apps (read vs act: actions/trusted_apps.py) -----
    "set_trusted_apps": Kind(
        WORKSPACE,
        ("apps",),
        "Trusted apps: {apps}",
        "apps (list of app / MCP server names whose answers don't count as untrusted; "
        "[] = none). Only the owner says yes to it: it lets those apps' words reach "
        "power actions without asking him",
        gate="owner",
        structured=("apps",),
    ),
}


PREFS_DO: dict[str, str] = {
    "saveTimezone": "do:set_timezone",
    "saveNotifications": "do:set_notifications",
    "markErrorFixed": "do:mark_error_fixed",
    "reopenError": "do:reopen_error",
    "saveFlag": "do:set_flag",
    "saveTrustedApps": "do:set_trusted_apps",
}
