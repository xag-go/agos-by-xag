"""Disconnecting an app from a workspace, and forgetting every login of a workspace that is deleted.
Must not: connect an app.

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
from typing import Any

from agos_core.actions import composio as composio_actions
from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.connector.app_catalog import (
    COMPOSIO,
    GOOGLE_MCP,
    _title,
    catalog,
    connectors_home,
    workspace_home,
)
from agos_core.actions.services.connector.composio import _end_key_session, _resync
from agos_core.actions.services.connector.connect_flow import LOGIN_PREFIX
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import workspace_app_logins as logins_repo
from agos_core.db.activity import add_activity
from agos_core.engine import apps as eng
from agos_core.engine import google as gg

__all__ = [
    "disconnect",
    "forget_workspace",
]


def disconnect(core: Core, workspace_id: str, name: str) -> None:
    """Forget THIS workspace's login to an app (other workspaces keep theirs)."""
    workspace = require_workspace(core, workspace_id)
    if catalog(core).get(name) is None:
        raise NotFoundError("This app")
    # Drive, Sheets and Docs share the workspace's one Google login: it goes for all
    # three (Google revokes it), never one left working on a cancelled login.
    names = list(GOOGLE_MCP) if name in GOOGLE_MCP else [name]
    home = workspace_home(core, workspace_id)
    if name in GOOGLE_MCP:
        gg.forget(home)
    _end_key_session(core, workspace_id, name)
    if name == COMPOSIO:
        composio_actions.forget(core, workspace_id)  # its project key goes too
    for each in names:
        eng.forget_login(home, each)
        logins_repo.delete(core.db, workspace_id, each)
    from agos_core.actions import hermes_config
    from agos_core.actions.library import change

    if hermes_config.has_root(core, workspace_id):
        # Off in its Hermes too (its entry goes): a new login turns it on again.
        def off(here: Any) -> None:
            here.apps = here.apps - set(names)

        change(core, workspace_id, off)
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"{_title(name)} disconnected from {workspace.name}",
    )
    _resync(core, name, [workspace_id])


def forget_workspace(core: Core, workspace_id: str) -> None:
    """A workspace is deleted for good: its logins go too (Google is revoked). Its
    Composio project stays as the owner made it (his apps there are his to remove)."""
    import shutil

    if not eng.APP_NAME.fullmatch(workspace_id):
        return
    _end_key_session(core, workspace_id, COMPOSIO)
    composio_actions.forget(core, workspace_id)
    home = connectors_home(core) / "w" / workspace_id
    if home.is_dir():
        with contextlib.suppress(OSError):
            gg.forget(home)
        shutil.rmtree(home, ignore_errors=True)
    if core.engine is not None:
        login = core.engine.settings.hermes_home / "profiles" / f"{LOGIN_PREFIX}w-{workspace_id}"
        if login.is_dir():
            shutil.rmtree(login, ignore_errors=True)
    logins_repo.delete_all(core.db, workspace_id)
