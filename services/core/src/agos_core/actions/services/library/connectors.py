"""The Connectors page of a workspace: list connectors, switch them, set their secrets.
Must not: write a workspace's Hermes directly (it goes through apply.change).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib

from agos_core.actions import hermes_config as hc
from agos_core.actions import team
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.apply import _applied_or_raise, adopt_servers, change
from agos_core.actions.services.library.catalog import summary_of, title_of
from agos_core.actions.services.library.records import (
    Connector,
    hermes_tools_module,
    locked_tool,
    workspace_skills_module,
)
from agos_core.actions.services.library.tool_rows import ensure_tools
from agos_core.actions.services.library.workspace_state import (
    _entry,
    _set_notes,
    oauth_signed_in,
    switches,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.activity import add_activity

__all__ = [
    "list_connectors",
    "set_connector",
    "set_secret",
]


def list_connectors(core: Core, workspace_id: str) -> list[Connector]:
    require_workspace(core, workspace_id)
    ensure_tools(core)
    adopt_servers(core, workspace_id)
    mine = switches(core, workspace_id)
    signed_in = oauth_signed_in(core.engine.profile_home(workspace_id)) if core.engine else set()
    ready: dict[str, bool] = {}
    if core.engine is not None and any(c.on for c in mine.values()):
        with contextlib.suppress(Exception):
            ready = core.engine.tool_readiness(workspace_id)
    result = [
        Connector(
            item_id=a.id,
            kind="agent",
            name=a.name,
            title=a.title,
            summary=a.summary,
            on=a.on,
            allowed_tools=[],
            local=a.local,
            secret=None,
            needs_secret=False,
        )
        for a in team.members(core, workspace_id)
    ]
    for row in repo.list_items(core.db, None, workspace_id):
        if row["kind"] == "skill" and workspace_skills_module().hidden(row):
            continue  # AGOS's own, in the background: never switched by the owner
        c = mine.get(int(row["id"]))
        result.append(
            Connector(
                item_id=row["id"],
                kind=row["kind"],
                name=row["name"],
                title=title_of(core, row),
                summary=summary_of(core, row),
                on=bool(c and c.on),
                allowed_tools=list(c.allowed_tools) if c else [],
                local=c.local if c else "",
                secret=f"••••{c.secret_last4}"
                if c and c.secret_last4
                else ("signed in (OAuth)" if row["name"] in signed_in else None),
                needs_secret=row["kind"] == "mcp",
                locked=locked_tool(row["name"]) if row["kind"] == "tool" else None,
                always=row["kind"] == "tool" and row["name"] in hermes_tools_module().ALWAYS,
                works=ready.get(str(row["name"])) if row["kind"] == "tool" and c and c.on else None,
            )
        )
    return result


def set_connector(
    core: Core,
    workspace_id: str,
    item_id: int,
    *,
    on: bool,
    allowed_tools: list[str],
    local: str,
) -> None:
    workspace = require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None:
        raise NotFoundError("This item")
    kind, name = str(row["kind"]), str(row["name"])
    if kind == "agent" and row["workspace_id"] != workspace_id:
        raise NotFoundError("This agent")  # another workspace's team
    if kind == "mcp" and row["workspace_id"] != workspace_id:
        raise NotFoundError("This MCP server")  # another workspace's
    if kind == "skill" and (
        row["workspace_id"] != workspace_id or workspace_skills_module().hidden(row)
    ):
        raise NotFoundError("This skill")  # another workspace's, or AGOS's background one
    if on and kind == "tool" and locked_tool(name):
        raise ActionError(str(locked_tool(name)), 409)
    tools = sorted({t.strip()[:120] for t in allowed_tools if t.strip()})[:200]
    if kind == "agent":
        # On or off the team: Hermes's parked marker; his notes: its SOUL.md.
        team.set_on(core, workspace_id, name, on=on, local=local)
    else:
        _set_notes(core, workspace_id, row, local.strip())
    definition = repo.definition(row)

    def edit(here: hc.Here) -> None:
        if kind == "skill":
            here.skills = (here.skills | {name}) if on else (here.skills - {name})
        elif kind == "tool":
            here.tools = (here.tools | {name}) if on else (here.tools - {name})
        elif kind == "plugin":
            plugin = hc.plugin_name(name, definition)
            here.plugins = (here.plugins | {plugin}) if on else (here.plugins - {plugin})
        elif kind == "mcp":
            entry = here.mcp.get(name)
            if entry is None:
                raise NotFoundError("This MCP server")
            entry["enabled"] = bool(on)
            if tools:
                entry["tools"] = {**hc._mapping(entry.get("tools")), "include": tools}
            elif isinstance(entry.get("tools"), dict):
                entry["tools"].pop("include", None)
                if not entry["tools"]:
                    entry.pop("tools")

    if kind == "agent":
        _applied_or_raise(core, workspace_id)
    else:
        change(core, workspace_id, edit)
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"{team.title_of(core, workspace_id, name) if kind == 'agent' else row['title']} "
        f"({kind}) turned {'on' if on else 'off'} for {workspace.name}",
    )


def set_secret(core: Core, workspace_id: str, item_id: int, value: str | None) -> None:
    """A server's key: Hermes's own place for it, the root's .env (${AGOS_MCP_…})."""
    require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "mcp" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This MCP server")
    if value is not None:
        value = value.strip()
        if not value or len(value) > 4000 or "\n" in value:
            raise ActionError("Paste the credential on one line.")
    name = str(row["name"])

    def edit(here: hc.Here) -> None:
        entry = here.mcp.get(name)
        if entry is None:
            raise NotFoundError("This MCP server")
        if value:
            here.keys[name] = value
        else:
            here.keys.pop(name, None)
        here.mcp[name] = _entry(name, entry, has_key=bool(value))

    change(core, workspace_id, edit)
    add_activity(
        core.db,
        workspace_id,
        kind="connector.secret",
        text=f"Credential {'saved' if value else 'removed'} for {row['title']}",
    )
