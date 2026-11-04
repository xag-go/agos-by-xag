"""The apps a workspace can connect: Hermes's catalog, Google's MCP apps, the records, where each workspace's logins live.
Must not: connect, switch or forget an app.

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.records import Record
from agos_core.engine import apps as eng
from agos_core.engine import google as gg
from agos_core.engine.models import hermes_python, hermes_repo

__all__ = [
    "COMPOSIO",
    "FLOW_TTL_S",
    "GOOGLE_MCP",
    "GOOGLE_SERVER",
    "NOUS_APP",
    "WORKSPACE_MCP",
    "AppTool",
    "ComposioAccount",
    "Flow",
    "WorkspaceApp",
    "catalog",
    "connectors_home",
    "core_url",
    "google_mcp_apps",
    "workspace_home",
]

log = logging.getLogger("agos.apps")

NOUS_APP = "nous"  # the one row for Nous hosted apps (a toolset, not a server)
COMPOSIO = "composio"
FLOW_TTL_S = 900
_HELPER = Path(__file__).resolve().parents[3] / "engine" / "connect_helper.py"  # agos_core/engine


class AppTool(Record):
    name: str
    description: str


class WorkspaceApp(Record):
    """One app as one workspace sees it: its own login, its own ON/OFF."""

    name: str
    title: str
    description: str
    kind: Literal["catalog", "nous"]
    login: Literal["oauth", "none"]
    connected: bool
    on: bool
    # The account this workspace is signed in with, when the app says (Google).
    account: str | None = None
    # Composio: through a Composio login, or the owner's project key.
    via: Literal["login", "key"] | None = None
    connected_at: str | None = None
    error: str | None = None
    tools: list[AppTool] = Field(default_factory=list)
    locked: str | None = None


class ComposioAccount(Record):
    """One app account of a workspace's own Composio user."""

    id: str
    toolkit: str
    status: str
    label: str
    created_at: str
    # False: connected for another Composio user than the agent's (made in
    # Composio's dashboard while the agent already had apps): connect it from AGOS.
    for_agent: bool = True


class Flow(Record):
    id: str
    workspace_id: str
    app: str
    status: Literal["starting", "authorize", "connected", "error"]
    url: str | None = None
    error: str | None = None


# ---- the catalog (read once from Hermes) ----------------------------------------------

_catalog_cache: dict[str, Any] = {}
_catalog_lock = threading.Lock()


def catalog(core: Core) -> dict[str, eng.CatalogApp]:
    if core.engine is None:
        return {}
    with _catalog_lock:
        if "apps" not in _catalog_cache:
            python = hermes_python(core.engine.settings)
            repo = hermes_repo(core.engine.settings) or Path(python).parent
            _catalog_cache["apps"] = {a.name: a for a in eng.load_catalog(python, repo)}
        apps: dict[str, eng.CatalogApp] = dict(_catalog_cache["apps"])
    for extra in eng.AGOS_APPS:
        apps.setdefault(extra.name, extra)  # Hermes's own entry wins if it ships one
    apps.update(google_mcp_apps(core))
    return dict(sorted(apps.items()))


# Google (Drive, Sheets, Docs): one open-source MCP server, workspace-mcp
# (github.com/taylorwilsdon/google_workspace_mcp, MIT), run by each workspace's Hermes
# like any MCP server, in that workspace's own MCP container. It calls Google's normal
# APIs with the owner's one Google login, which stays in that container (never the
# agent's sandbox). Each app turns its part of the server on.
GOOGLE_SERVER = "google"  # the container, and `mcp_servers.app-google` in Hermes
WORKSPACE_MCP = "workspace-mcp==2.0.1"
# PySocks: Google's client (httplib2) only goes through the workspace's internet proxy
# with it; without it every call fails ("Unable to find the server").
GOOGLE_MCP: dict[str, tuple[str, str]] = {
    "google-drive": ("drive", "Google Drive: search, read, create, copy, move and trash files."),
    "google-sheets": ("sheets", "Google Sheets: read and write values, rows and tabs."),
    "google-docs": ("docs", "Google Docs: read, create and edit documents."),
}
# In the container: the login goes to a 0600 file in its /tmp (never /workspace),
# then the server starts on it.
_GOOGLE_START = (  # one line: it travels in a docker env file
    "python3 -c 'import json,os;"
    'd=json.loads(os.environ["AGOS_GOOGLE"]);'
    'os.makedirs("/tmp/agos-google",0o700,exist_ok=True);'
    '[open(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600),"w").write(json.dumps(b))'
    ' for p,b in ((d["file"],d["creds"]),("/tmp/agos-google-client.json",d["client"]))]'
    "' && export WORKSPACE_MCP_CREDENTIALS_DIR=/tmp/agos-google"
    " GOOGLE_CLIENT_SECRET_PATH=/tmp/agos-google-client.json"
    " USER_GOOGLE_EMAIL=\"$(python3 -c 'import json,os;"
    'print(json.loads(os.environ["AGOS_GOOGLE"])["email"])\')"'
    " && exec uvx --with PySocks==1.7.1 {package} --single-user --tools {tools} # login {stamp}"
)


def google_mcp_apps(core: Core) -> dict[str, eng.CatalogApp]:
    client = gg.load_client(connectors_home(core))
    return {
        name: eng.CatalogApp(
            name=name,
            description=about,
            url="",
            auth="oauth",
            source="google",  # AGOS's one Google login (engine/google.py)
            locked=None if client else "AGOS's Google app file is missing (Google Cloud client).",
        )
        for name, (_, about) in GOOGLE_MCP.items()
    }


def core_url() -> str:
    import os

    return os.environ.get("AGOS_CORE_URL", "http://127.0.0.1:8766").rstrip("/")


def connectors_home(core: Core) -> Path:
    """AGOS's connectors folder. Only app files shared by design live at its top
    (the owner's Google Cloud client); every login is under `w/<workspace>/`."""
    home = core.layout.system / "connectors"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def workspace_home(core: Core, workspace_id: str) -> Path:
    """This workspace's own logins (Hermes token files, its Google login)."""
    if not eng.APP_NAME.fullmatch(workspace_id):
        raise ActionError("Unknown workspace.", 404)
    home = connectors_home(core) / "w" / workspace_id
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def _title(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").title()
