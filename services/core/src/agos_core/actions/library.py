"""The library (Settings: tools, plugins, MCP templates) and each workspace's own
items and connectors, as Hermes has them.

What a workspace has on is its own root's Hermes config (actions/hermes_config.py),
read there and changed there; AGOS keeps no copy of it:
- skills  → the workspace's own, in ONE folder of its root that its Co-Founder and
            every member read (actions/workspace_skills.py); off in a workspace =
            its profiles' `skills.disabled`
- MCP     → `mcp_servers` in the root's config (+ the credential in its .env); the
            library row of an MCP server is only its id and name in AGOS
- plugins → `plugins.enabled` of the profile (installed disabled by Hermes)
- tools   → `platform_toolsets` (on) and `agent.disabled_toolsets` (off)
- agents  → the team: the root's member profiles, the one source (actions/team.py)
The members' profiles get the root's settings copied in (no inheritance in Hermes).
Changes apply from the next session or run (Hermes reads them at session start).

This module is a compatibility facade: the code lives in actions/services/library/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.library.records import log as log
from agos_core.actions.services.library.records import OWNED as OWNED
from agos_core.actions.services.library.records import TEMPLATE as TEMPLATE
from agos_core.actions.services.library.records import is_template as is_template
from agos_core.actions.services.library.records import tool_service as tool_service
from agos_core.actions.services.library.records import locked_tool as locked_tool
from agos_core.actions.services.library.records import LibraryItem as LibraryItem
from agos_core.actions.services.library.records import Connector as Connector
from agos_core.actions.services.library.records import library_home as library_home
from agos_core.actions.services.library.records import used_by as used_by
from agos_core.actions.services.library.tool_rows import ensure_tools as ensure_tools
from agos_core.actions.services.library.workspace_state import (
    workspace_lock as workspace_lock,
    notes as notes,
    Switch as Switch,
    switches as switches,
    enabled as enabled,
    SPILL_KEY as SPILL_KEY,
    SPILL_MOVED as SPILL_MOVED,
    move_spill_cap as move_spill_cap,
    profile_settings as profile_settings,
    BASE_TOOLSETS as BASE_TOOLSETS,
    oauth_signed_in as oauth_signed_in,
)
from agos_core.actions.services.library.apply import (
    resync_users as resync_users,
    change as change,
    adopt_servers as adopt_servers,
    refresh_tools as refresh_tools,
    FORMAT as FORMAT,
    apply_workspace as apply_workspace,
    _mcp_edited as _mcp_edited,
    _write as _write,
    reload_gateway as reload_gateway,
    agent_text as agent_text,
)
from agos_core.actions.services.library.sharing import (
    _shareable as _shareable,
    share_servers as share_servers,
)
from agos_core.actions.services.library.catalog import (
    _stored as _stored,
    summary_of as summary_of,
    title_of as title_of,
    list_items as list_items,
    save_item as save_item,
    _checked as _checked,
)
from agos_core.actions.services.library.connectors import (
    list_connectors as list_connectors,
    set_connector as set_connector,
    set_secret as set_secret,
)
from agos_core.actions.services.library.lifecycle import (
    add_template as add_template,
    rename_item as rename_item,
    delete_item as delete_item,
    delete_mcp as delete_mcp,
    duplicate_item as duplicate_item,
    copyable_agents as copyable_agents,
    copy_agent as copy_agent,
)
from agos_core.actions.services.library.mcp_test import (
    McpTool as McpTool,
    McpTest as McpTest,
    test_mcp as test_mcp,
)
from agos_core.actions.services.library.github_token import (
    GithubTokenState as GithubTokenState,
    _token_status as _token_status,
    github_token_status as github_token_status,
    save_github_token as save_github_token,
    remove_github_token as remove_github_token,
    read_ahead_connectors as read_ahead_connectors,
    read_ahead as read_ahead,
    _with_github_limit as _with_github_limit,
    check_agent as check_agent,
)
from agos_core.actions.services.library.sources import (
    FoundItem as FoundItem,
    Inspected as Inspected,
    _sources as _sources,
    _found as _found,
    on_this_machine as on_this_machine,
    import_from_machine as import_from_machine,
    search_web as search_web,
    inspect_web as inspect_web,
)
# isort: on
