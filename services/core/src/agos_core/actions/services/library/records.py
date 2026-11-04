"""The library's vocabulary: kinds, templates, toolset locks, the item records, who uses an item.
Must not: read or write a workspace's Hermes config, or change library rows.

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from agos_core.actions import hermes_config as hc
from agos_core.actions import team
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.records import Record

__all__ = [
    "OWNED",
    "TEMPLATE",
    "Connector",
    "LibraryItem",
    "is_template",
    "library_home",
    "locked_tool",
    "used_by",
]

log = logging.getLogger("agos.library")

# Kinds that belong to ONE workspace (created and seen only inside it).
OWNED = repo.OWNED
# An MCP server the owner defines once in Settings → Connectors (definition only).
# A workspace that adds it gets its own copy (source "template:<id>"), its own key
# or sign-in, written into its own Hermes like any of its servers.
TEMPLATE = "template"


def is_template(row: Any) -> bool:
    return row["kind"] == "mcp" and not row["workspace_id"] and row["source"] == TEMPLATE


# Toolsets a workspace may turn on (they run inside its sandbox or only reach
# the internet through Hermes). Anything else stays locked until step 6b.
# Always on (sandbox-only or read-only): terminal, file, web, todo, memory,
# session_search, skills, clarify. The owner can turn these on per workspace:
def hermes_tools_module() -> Any:
    from agos_core.engine import hermes_tools

    return hermes_tools


def tool_service(
    core: Core, name: str, services: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The service a tool uses, as the workspaces' Hermes have it."""
    from agos_core.actions import tool_services

    if services is None:
        services = tool_services.chosen(core)
    found = services.get(name)
    return dict(found) if isinstance(found, dict) else None


def locked_tool(name: str) -> str | None:
    found = hermes_tools_module().LOCKED.get(name)
    return str(found) if found else None


class LibraryItem(Record):
    id: int
    kind: Literal["skill", "agent", "mcp", "plugin", "tool"]
    name: str
    title: str
    summary: str
    definition: dict[str, Any]
    source: str
    used_by: list[str]
    locked: str | None = None
    # A tool of Hermes's core: always on (no switch).
    always: bool = False
    # A tool that can use an outside service: Hermes's list of them, and the one
    # set up (its name and keys' last 4).
    services: list[dict[str, Any]] = Field(default_factory=list)
    service: dict[str, Any] | None = None
    # Agents: the workspace whose team it is in (None = not given to one yet).
    workspace_id: str | None = None


class Connector(Record):
    item_id: int
    kind: Literal["skill", "agent", "mcp", "plugin", "tool"]
    name: str
    title: str
    summary: str
    on: bool
    allowed_tools: list[str]
    local: str
    # Masked (••••last4) when a credential is saved; never the secret itself.
    secret: str | None
    needs_secret: bool
    locked: str | None = None
    always: bool = False
    # A tool that needs a service: does it really work here (its Hermes says)?
    # None: not one of those, off, or not known.
    works: bool | None = None


# ---- library ---------------------------------------------------------------------


def library_home(core: Core) -> Path:
    """AGOS's own Hermes home for the hub's GitHub token (Settings → Tools)."""
    return core.layout.global_dir


# A skill lives ONCE: its Hermes skill folder (actions/workspace_skills.py).
def workspace_skills_module() -> Any:
    from agos_core.actions import workspace_skills

    return workspace_skills


def used_by(core: Core, row: Any, heres: dict[str, hc.Here] | None = None) -> list[str]:
    """The workspaces that have it on (their Hermes says so)."""
    kind, name = str(row["kind"]), str(row["name"])
    if kind == "agent":
        ws = str(row["workspace_id"] or "")
        return [ws] if ws and name in team.names(core, ws) else []
    if kind == "mcp" and is_template(row):
        alive = set(heres) if heres is not None else set(every_here(core))
        return sorted(
            {str(c["workspace_id"]) for c in repo.template_copies(core.db, int(row["id"]))} & alive
        )
    if kind == "mcp":
        ws = str(row["workspace_id"] or "")
        entry = hc.here(core, ws).mcp.get(name) if ws else None
        return [ws] if entry is not None and hc.is_on(entry) else []
    if kind == "skill":
        ws = str(row["workspace_id"] or "")
        if not ws:
            return []
        here = heres.get(ws) if heres is not None else None
        here = here if here is not None else hc.here(core, ws)
        return [ws] if name in here.skills else []
    out = []
    for ws, here in (heres if heres is not None else all_here(core)).items():
        if (
            (kind == "skill" and name in here.skills)
            or (kind == "tool" and name in here.tools)
            or (kind == "plugin" and hc.plugin_name(name, repo.definition(row)) in here.plugins)
        ):
            out.append(ws)
    return sorted(out)


def all_here(core: Core) -> dict[str, hc.Here]:
    from agos_core.db.workspaces import list_workspaces

    return {w.id: hc.here(core, w.id) for w in list_workspaces(core.db)}


def every_here(core: Core) -> dict[str, hc.Here]:
    from agos_core.db.workspaces import list_workspaces

    return {
        w.id: hc.here(core, w.id)
        for w in list_workspaces(core.db, include_archived=True)
        if hc.has_root(core, w.id)
    }
