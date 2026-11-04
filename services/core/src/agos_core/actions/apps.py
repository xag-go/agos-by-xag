"""Connectors (apps with an account): each workspace connects its OWN accounts.

Nothing is shared between workspaces: Content Creation's Instagram or Notion is
never Rap Production's. A workspace connects an app in its own Apps page, then
can turn it off and on again without logging in again.

Two kinds:
- catalog apps (Hermes's approved list + AGOS's extra ones): Hermes does the
  login; its token files live in that workspace's own login folder
  (`connectors/w/<workspace>/mcp-tokens`, linked as the profile's `mcp-tokens`).
  An app is ON while its `mcp_servers.app-<name>` entry is in the workspace's
  Hermes config (Hermes's `enabled: false` while its login is missing); Google's
  apps are one entry, `app-google`, whose `agos.apps` lists them.
- Nous hosted apps (Gmail, Drive…): they belong to the owner's Nous account
  and Hermes shows them only when Nous enabled them for that account. A
  workspace turns them on with Hermes's `connections` toolset.
The login bookkeeping (workspace_app_logins: when, its tools, Composio's session)
is AGOS's own connect flow; Hermes has no such store.

This module is a compatibility facade: the code lives in actions/services/connector/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.connector.app_catalog import (
    log as log,
    NOUS_APP as NOUS_APP,
    COMPOSIO as COMPOSIO,
    FLOW_TTL_S as FLOW_TTL_S,
    AppTool as AppTool,
    WorkspaceApp as WorkspaceApp,
    ComposioAccount as ComposioAccount,
    Flow as Flow,
    _catalog_cache as _catalog_cache,
    catalog as catalog,
    GOOGLE_SERVER as GOOGLE_SERVER,
    WORKSPACE_MCP as WORKSPACE_MCP,
    GOOGLE_MCP as GOOGLE_MCP,
    google_mcp_apps as google_mcp_apps,
    core_url as core_url,
    connectors_home as connectors_home,
    workspace_home as workspace_home,
)
from agos_core.actions.services.connector.nous_apps import (
    _nous_kept as _nous_kept,
    nous_status as nous_status,
    read_ahead_nous as read_ahead_nous,
    _ask_nous as _ask_nous,
    nous_signed_in as nous_signed_in,
)
from agos_core.actions.services.connector.workspace_apps import (
    google_server as google_server,
    enabled_apps as enabled_apps,
    _is_connected as _is_connected,
    workspace_apps as workspace_apps,
    CatalogRow as CatalogRow,
    catalog_rows as catalog_rows,
    set_workspace_app as set_workspace_app,
    _switch as _switch,
    profile_servers as profile_servers,
    KEY_ENV as KEY_ENV,
    profile_secrets as profile_secrets,
    prepare_profile as prepare_profile,
)
from agos_core.actions.services.connector.connect_flow import (
    Process as Process,
    _spawn as _spawn,
    LOGIN_PREFIX as LOGIN_PREFIX,
    login_home as login_home,
    spawn as spawn,
    check_redirect as check_redirect,
    start_connect as start_connect,
    _read as _read,
    get_flow as get_flow,
    deliver_callback as deliver_callback,
    wait_flow as wait_flow,
)
from agos_core.actions.services.connector.composio import (
    composio_api as composio_api,
    set_composio_key as set_composio_key,
    _accounts_cache as _accounts_cache,
    read_ahead_composio_accounts as read_ahead_composio_accounts,
    composio_accounts as composio_accounts,
    composio_link as composio_link,
    composio_remove_account as composio_remove_account,
    FOLLOW_EVERY_S as FOLLOW_EVERY_S,
    _followed as _followed,
    follow_composio_users as follow_composio_users,
    AuthSetupField as AuthSetupField,
    ComposioAuthSetup as ComposioAuthSetup,
    composio_auth_setup as composio_auth_setup,
    composio_set_up as composio_set_up,
)
from agos_core.actions.services.connector.disconnect import (
    disconnect as disconnect,
    forget_workspace as forget_workspace,
)
# isort: on
