"""A workspace's apps: which are connected and on, the Apps page rows, switching one, what its profiles get.
Must not: run a login flow (connect_flow does).

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Literal

from agos_core.actions import composio as composio_actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.connector import (
    nous_apps,  # nous_status: looked up there (tests patch it)
)
from agos_core.actions.services.connector.app_catalog import (
    _GOOGLE_START,
    COMPOSIO,
    GOOGLE_MCP,
    GOOGLE_SERVER,
    NOUS_APP,
    WORKSPACE_MCP,
    AppTool,
    WorkspaceApp,
    _title,
    catalog,
    connectors_home,
    google_mcp_apps,
    log,
    workspace_home,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import workspace_app_logins as logins_repo
from agos_core.db.activity import add_activity
from agos_core.db.records import Record
from agos_core.db.rows import load_json
from agos_core.engine import apps as eng
from agos_core.engine import google as gg

__all__ = [
    "KEY_ENV",
    "CatalogRow",
    "catalog_rows",
    "enabled_apps",
    "google_server",
    "prepare_profile",
    "profile_secrets",
    "profile_servers",
    "set_workspace_app",
    "workspace_apps",
]


def google_server(
    core: Core, workspace_id: str, apps_on: set[str] | None = None
) -> tuple[str, str] | None:
    """(command, login) of this workspace's Google MCP server, or None when no Google
    app is on (or this workspace's login is gone). The login travels as one env value."""
    have = enabled_apps(core, workspace_id) if apps_on is None else sorted(apps_on)
    on = [n for n in have if n in GOOGLE_MCP]
    client = gg.load_client(connectors_home(core))
    token = gg.load_token(workspace_home(core, workspace_id))
    if not on or client is None or not token:
        return None
    if not any(
        _is_connected(core, workspace_id, a) for n, a in google_mcp_apps(core).items() if n in on
    ):
        return None
    import hashlib
    import urllib.parse

    email = str(token.get("email") or "owner")
    login = {
        "email": email,
        "file": f"/tmp/agos-google/{urllib.parse.quote(email, safe='@')}.json",  # noqa: S108
        "creds": {
            "token": None,
            "refresh_token": token["refresh_token"],
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "scopes": str(token.get("scope") or "").split(),
            "expiry": None,
        },
        "client": {
            "web": {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
    }
    secret = json.dumps(login, separators=(",", ":"))
    stamp = hashlib.sha256(secret.encode()).hexdigest()[:16]  # a new login restarts it
    script = _GOOGLE_START.format(
        package=WORKSPACE_MCP, tools=" ".join(GOOGLE_MCP[n][0] for n in on), stamp=stamp
    )
    return shlex.join(["sh", "-c", script]), secret


# ---- rows -----------------------------------------------------------------------------


def _login_row(core: Core, workspace_id: str, name: str) -> Any:
    return logins_repo.get(core.db, workspace_id, name)


def enabled_apps(core: Core, workspace_id: str) -> list[str]:
    """The apps on in this workspace, as its Hermes config has them."""
    from agos_core.actions import hermes_config

    return sorted(hermes_config.here(core, workspace_id).apps)


def _is_connected(core: Core, workspace_id: str, app: eng.CatalogApp) -> bool:
    if app.auth == "none":
        return True
    row = _login_row(core, workspace_id, app.name)
    if not (row and row["status"] == "connected"):
        return False
    if row["via"] == "key":
        return bool(row["session"]) and composio_actions.key(core, workspace_id) is not None
    home = workspace_home(core, workspace_id)
    return gg.has_login(home) if app.source == "google" else eng.has_login(home, app.name)


def workspace_apps(core: Core, workspace_id: str) -> list[WorkspaceApp]:
    require_workspace(core, workspace_id)
    on = set(enabled_apps(core, workspace_id))
    available, why = nous_apps.nous_status(core)
    result = [
        WorkspaceApp(
            name=NOUS_APP,
            title="Nous apps (Gmail, Google Drive…)",
            description="Apps connected to your Nous account in Hermes.",
            kind="nous",
            login="oauth",
            connected=available,
            on=NOUS_APP in on,
            locked=why,
        )
    ]
    home = workspace_home(core, workspace_id)
    for app in catalog(core).values():
        row = _login_row(core, workspace_id, app.name)
        connected = _is_connected(core, workspace_id, app)
        result.append(
            WorkspaceApp(
                name=app.name,
                title=_title(app.name),
                description=app.description,
                kind="catalog",
                login="oauth" if app.auth == "oauth" else "none",
                connected=connected,
                on=app.name in on,
                account=(
                    gg.account(home)
                    if app.source == "google" and connected
                    else f"key ••••{composio_actions.last4(core, workspace_id) or ''}"
                    if row and row["via"] == "key" and connected
                    else None
                ),
                via=(str(row["via"]) if row else None) if connected else None,  # type: ignore[arg-type]
                connected_at=row["connected_at"] if row else None,
                error=row["error"] if row and row["error"] else None,
                tools=[AppTool(**t) for t in load_json(row["tools"])] if row else [],
                locked=app.locked,
            )
        )
    return result


class CatalogRow(Record):
    """One app of the shared list (Settings → Connectors): what it is and which
    workspaces have it on. No login here: each workspace connects its own."""

    name: str
    title: str
    description: str
    login: Literal["oauth", "none"]
    source: str  # "hermes" (Hermes's catalog), "agos" or "google"
    used_by: list[str]
    locked: str | None = None


def catalog_rows(core: Core) -> list[CatalogRow]:
    from agos_core.actions import hermes_config
    from agos_core.db.workspaces import list_workspaces

    on: dict[str, list[str]] = {}
    for w in list_workspaces(core.db, include_archived=True):
        if not hermes_config.has_root(core, w.id):
            continue
        for name in hermes_config.here(core, w.id).apps:
            on.setdefault(name, []).append(w.id)
    agos = {a.name for a in eng.AGOS_APPS}
    rows = [
        CatalogRow(
            name=NOUS_APP,
            title="Nous apps (Gmail, Google Drive…)",
            description="Apps connected to your Nous account in Hermes.",
            login="oauth",
            source="hermes",
            used_by=sorted(on.get(NOUS_APP, [])),
            locked=nous_apps.nous_status(core)[1],
        )
    ]
    for app in catalog(core).values():
        rows.append(
            CatalogRow(
                name=app.name,
                title=_title(app.name),
                description=app.description,
                login="oauth" if app.auth == "oauth" else "none",
                source="google"
                if app.source == "google"
                else "agos"
                if app.name in agos
                else "hermes",
                used_by=sorted(on.get(app.name, [])),
                locked=app.locked,
            )
        )
    return rows


def set_workspace_app(core: Core, workspace_id: str, name: str, *, on: bool) -> None:
    from agos_core.actions.library import change

    workspace = require_workspace(core, workspace_id)
    if name == NOUS_APP:
        title = "Nous apps"
        if on:
            available, why = nous_apps.nous_status(core, fresh=True)
            if not available:
                raise ActionError(why or "Not available.", 409)
    else:
        app = catalog(core).get(name)
        if app is None:
            raise NotFoundError("This app")
        title = _title(name)
        if on and app.locked:
            raise ActionError(app.locked, 409)
        if on and not _is_connected(core, workspace_id, app):
            raise ActionError(f"Connect {title} in this workspace first.", 409)
    change(core, workspace_id, lambda here: _switch(here, name, on))
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"{title} (app) turned {'on' if on else 'off'} for {workspace.name}",
    )


def _switch(here: Any, name: str, on: bool) -> None:
    here.apps = (here.apps | {name}) if on else (here.apps - {name})


def _turn_on(core: Core, workspace_id: str, name: str, *, strict: bool = False) -> None:
    """Connected from this workspace = wanted here: on in its Hermes at once."""
    from agos_core.actions import hermes_config
    from agos_core.actions.library import change

    if not hermes_config.has_root(core, workspace_id):
        return  # set up later: the owner turns it on then
    try:
        change(core, workspace_id, lambda here: _switch(here, name, True))
    except ActionError as error:
        if strict:
            raise
        log.warning("app %s not turned on in %s: %s", name, workspace_id, error)


# ---- what a workspace profile gets --------------------------------------------------


def profile_servers(
    core: Core, workspace_id: str, apps_on: set[str], google_url: str | None = None
) -> dict[str, dict[str, Any]]:
    """`mcp_servers` entries of the apps ON here: Hermes's switch is on while the
    app's login is there (`enabled: false` until it is back). Google's apps are one
    server, in this workspace's MCP container (google_url)."""
    servers: dict[str, dict[str, Any]] = {}
    if not apps_on - {NOUS_APP}:
        return servers
    known = catalog(core)
    google = sorted(n for n in apps_on if n in GOOGLE_MCP and n in known)
    if google:
        servers[eng.server_name(GOOGLE_SERVER)] = {
            "url": google_url or "",
            "enabled": bool(google_url),
            "agos": {"apps": google},
        }
    for name in sorted(apps_on):
        app = known.get(name)
        if app is None or app.source == "google" or name == NOUS_APP:
            continue
        connected = not app.locked and _is_connected(core, workspace_id, app)
        session = _key_session(core, workspace_id, name) if connected else None
        if session is not None:
            # Composio by key: this workspace's session, the key from the profile's .env.
            entry: dict[str, Any] = {
                "url": session["url"],
                "headers": {"x-api-key": f"${{{KEY_ENV}}}"},
            }
        else:
            entry = eng.server_entry(app)
        entry["enabled"] = connected
        servers[eng.server_name(name)] = entry
    return servers


KEY_ENV = "AGOS_MCP_APP_COMPOSIO"  # = library.env_name("app-composio")


def _key_session(core: Core, workspace_id: str, name: str) -> dict[str, str] | None:
    row = _login_row(core, workspace_id, name)
    if not row or row["via"] != "key" or not row["session"]:
        return None
    data = load_json(row["session"])
    return data if isinstance(data, dict) and data.get("url") else None


def profile_secrets(core: Core, workspace_id: str, apps_on: set[str]) -> dict[str, str]:
    """Secrets this workspace's apps need in its profile's .env (as AGOS_MCP_*):
    the key of this workspace's OWN Composio project, while Composio is on here by
    key (that project holds only this workspace's accounts)."""
    if COMPOSIO not in apps_on:
        return {}
    if _key_session(core, workspace_id, COMPOSIO) is None:
        return {}
    value = composio_actions.key(core, workspace_id)
    return {eng.server_name(COMPOSIO): value} if value else {}


def prepare_profile(core: Core, workspace_id: str, profile_home: Path) -> None:
    """The profile's `mcp-tokens` is always this workspace's own login folder, so
    Hermes finds the workspace's app logins and its library MCP sign-ins in one
    place, whatever is on or off (only `mcp_servers` decides what the agent gets)."""
    eng.link_tokens(profile_home, workspace_home(core, workspace_id))
