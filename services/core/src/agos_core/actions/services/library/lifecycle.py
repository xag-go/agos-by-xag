"""Changing items already in the library: add a template, rename, delete, duplicate, copy an agent.
Must not: write a workspace's Hermes directly (it goes through apply).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import hermes_config as hc
from agos_core.actions import team
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.apply import apply_workspace, change
from agos_core.actions.services.library.catalog import _definition, _workspace_name, save_item
from agos_core.actions.services.library.records import (
    OWNED,
    TEMPLATE,
    is_template,
    log,
    used_by,
    workspace_skills_module,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.connection import transaction
from agos_core.db.rows import load_json

__all__ = [
    "add_template",
    "copy_agent",
    "copyable_agents",
    "delete_item",
    "delete_mcp",
    "duplicate_item",
    "rename_item",
]


def add_template(core: Core, workspace_id: str, template_id: int) -> int:
    """The workspace's own copy of a shared definition, on in it at once; it then
    signs in or gets its key here, like any of its servers."""
    row = repo.get_item(core.db, template_id)
    if row is None or not is_template(row):
        raise NotFoundError("This MCP server")
    return save_item(
        core,
        None,
        kind="mcp",
        name=str(row["name"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        definition=repo.definition(row),
        source=f"{TEMPLATE}:{template_id}",
        workspace_id=workspace_id,
    )


def rename_item(core: Core, item_id: int, title: str, workspace_id: str | None = None) -> None:
    """Changes the name shown everywhere (its id stays, so nothing breaks)."""
    row = repo.get_item(core.db, item_id)
    if row is None or (
        workspace_id is not None and row["kind"] in OWNED and row["workspace_id"] != workspace_id
    ):
        raise NotFoundError("This item")
    title = title.strip()
    if not title:
        raise ActionError("Give it a name.")
    if row["kind"] == "agent":
        agent = team.by_id(core, item_id)
        if agent is None:
            raise NotFoundError("This agent")
        team.save(
            core,
            agent.workspace_id,
            agent.name,
            title=title,
            summary=agent.summary,
            definition=agent.definition,
            new=False,
        )
        return
    repo.update_item(
        core.db,
        item_id,
        title=title,
        summary=str(row["summary"]),
        definition=load_json(row["definition"]),
    )


def delete_item(core: Core, item_id: int, workspace_id: str | None = None) -> list[str]:
    """Deletes it and turns it off everywhere. Returns the workspaces that used it."""
    row = repo.get_item(core.db, item_id)
    if row is None or (
        workspace_id is not None and row["kind"] in OWNED and row["workspace_id"] != workspace_id
    ):
        raise NotFoundError("This item")
    if row["kind"] == "tool":
        raise ActionError("Hermes tools can't be deleted; turn them off per workspace.")
    users = used_by(core, row)
    if row["kind"] == "agent":
        if not row["workspace_id"]:
            repo.delete_item(core.db, item_id)  # an old one never given to a team
            return []
        ws = str(row["workspace_id"])
        team.delete(core, ws, str(row["name"]))
        apply_workspace(core, ws)  # off the Co-Founder's board dispatch
        return users
    if is_template(row):
        # Gone from the list = gone from every workspace that added it.
        failed = []
        for copy in repo.template_copies(core.db, item_id):
            ws = str(copy["workspace_id"])
            try:
                delete_item(core, int(copy["id"]), ws)
            except ActionError as error:
                log.warning("shared MCP copy %s not removed from %s: %s", copy["id"], ws, error)
                failed.append(_workspace_name(core, ws))
        if failed:
            raise ActionError(f"Not deleted: it couldn't be removed from {', '.join(failed)}.", 503)
        repo.delete_item(core.db, item_id)
        return users
    if row["kind"] == "skill":
        ws = str(row["workspace_id"] or "")
        if not ws:
            raise NotFoundError("This skill")
        workspace_skills_module().delete(core, ws, item_id)
        return users
    if row["kind"] == "mcp" and row["workspace_id"]:
        name, ws = str(row["name"]), str(row["workspace_id"])

        def edit(here: hc.Here) -> None:
            here.mcp.pop(name, None)
            here.keys.pop(name, None)

        if hc.has_root(core, ws):
            change(core, ws, edit)
        repo.delete_item(core.db, item_id)
        return users
    with transaction(core.db):
        repo.delete_item(core.db, item_id)
    for workspace_id in users:
        apply_workspace(core, workspace_id)
    return users


def delete_mcp(core: Core, item_id: int, workspace_id: str) -> list[str]:
    """A workspace's MCP server (Connectors → MCP): only an MCP row is deleted here."""
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "mcp":
        raise NotFoundError("This MCP server")
    return delete_item(core, item_id, workspace_id)


def duplicate_item(core: Core, item_id: int, new_name: str, workspace_id: str | None = None) -> int:
    """A copy under a new name. An agent can be copied into another workspace
    (`workspace_id`): the copy is that team's own, the original stays put."""
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] == "tool":
        raise NotFoundError("This item")
    if row["kind"] == "agent":
        return copy_agent(core, item_id, workspace_id or str(row["workspace_id"] or ""), new_name)
    if row["kind"] == "skill":
        ws = str(row["workspace_id"] or "")
        if workspace_id is not None and workspace_id != ws:
            raise NotFoundError("This skill")  # another workspace's: out of reach
        made: int = workspace_skills_module().duplicate(core, ws, item_id, new_name)
        return made
    definition = _definition(core, row)
    return save_item(
        core,
        None,
        kind=row["kind"],
        name=new_name,
        title=f"{row['title']} (copy)" if not workspace_id else str(row["title"]),
        summary=row["summary"],
        definition=definition,
        workspace_id=(workspace_id or row["workspace_id"]) if row["kind"] in OWNED else None,
    )


def copyable_agents(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The other projects' agents (read from their Hermes profiles), for the owner's
    "Copy from another project" only."""
    from agos_core.db.workspaces import list_workspaces

    require_workspace(core, workspace_id)
    out = []
    for w in sorted(list_workspaces(core.db, include_archived=True), key=lambda w: w.name):
        if w.id == workspace_id:
            continue
        for a in team.members(core, w.id):
            out.append({"id": a.id, "title": a.title, "name": a.name, "workspace": w.name})
    return out


def copy_agent(core: Core, item_id: int, workspace_id: str, name: str | None = None) -> int:
    """The owner copies an agent from another project into this one: a new member
    profile here with the same title, role text, rule files, model and skills."""
    source = team.by_id(core, item_id)
    if source is None:
        raise NotFoundError("This agent")
    require_workspace(core, workspace_id)
    new_name = (name or source.name).strip()
    if team.get(core, workspace_id, new_name) is not None:
        raise ActionError(f"This workspace already has an agent named {new_name}.", 409)
    return save_item(
        core,
        None,
        kind="agent",
        name=new_name,
        title=source.title,
        summary=source.summary,
        definition=source.definition,
        workspace_id=workspace_id,
    )
