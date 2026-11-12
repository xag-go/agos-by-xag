"""The library catalog: list, read and save skills, agents and MCP servers.
Must not: write a workspace's Hermes directly (it goes through apply).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import hermes_config as hc
from agos_core.actions import team
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.apply import (
    _applied_or_raise,
    adopt_servers,
    change,
    resync_users,
)
from agos_core.actions.services.library.records import (
    OWNED,
    TEMPLATE,
    LibraryItem,
    all_here,
    every_here,
    hermes_tools_module,
    is_template,
    locked_tool,
    log,
    tool_service,
    used_by,
    workspace_skills_module,
)
from agos_core.actions.services.library.sharing import share_servers
from agos_core.actions.services.library.tool_rows import ensure_tools
from agos_core.actions.services.library.workspace_state import _entry, workspace_lock
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.connection import transaction
from agos_core.engine import library as lib
from agos_core.engine.library import Kind, LibraryError

__all__ = [
    "list_items",
    "save_item",
    "summary_of",
    "title_of",
]


def _stored(kind: str, definition: dict[str, Any]) -> dict[str, Any]:
    return workspace_skills_module().stored(definition) if kind == "skill" else definition


def _skill_head(core: Core, row: Any) -> dict[str, str]:
    """A skill's SKILL.md frontmatter (read from its workspace's folder each time)."""
    found: dict[str, str] = workspace_skills_module().head(core, row)
    return found


def summary_of(core: Core, row: Any, head: dict[str, str] | None = None) -> str:
    """An item's one-line summary. A skill's is its SKILL.md description (Hermes's own
    frontmatter, read from the skill's folder each time: AGOS keeps no copy); a
    tool's is Hermes's own words for its toolset (its catalog, engine/hermes_tools)."""
    if row["kind"] == "tool":
        return str(hermes_tools_module().about(str(row["name"])))
    if row["kind"] != "skill":
        return str(row["summary"] or "")
    head = _skill_head(core, row) if head is None else head
    return str(head.get("description") or "")


def title_of(core: Core, row: Any, head: dict[str, str] | None = None) -> str:
    """An item's display name. A tool's is Hermes's label for its toolset; a skill's
    is its SKILL.md name, unless the owner gave it a display name of its own (Hermes
    has no field for one, so only that stays in AGOS's row)."""
    if row["kind"] == "tool":
        return str(hermes_tools_module().title(str(row["name"])))
    if row["kind"] != "skill":
        return str(row["title"] or "")
    if str(row["title"] or "").strip():
        return str(row["title"])
    head = _skill_head(core, row) if head is None else head
    return str(head.get("name") or row["name"])


def _definition(core: Core, row: Any) -> dict[str, Any]:
    stored = repo.definition(row)
    if row["kind"] == "tool":
        return {"toolset": str(row["name"])}  # its name is Hermes's toolset
    if row["kind"] == "skill":
        found: dict[str, Any] = workspace_skills_module().definition(core, row)
        return found
    if row["kind"] == "mcp" and row["workspace_id"]:
        entry = hc.here(core, str(row["workspace_id"])).mcp.get(str(row["name"]))
        return hc.definition_of(entry) if entry is not None else stored
    return stored


def _item(
    core: Core,
    row: Any,
    heres: dict[str, hc.Here] | None = None,
    services: dict[str, Any] | None = None,
) -> LibraryItem:
    kind = row["kind"]
    head = _skill_head(core, row) if kind == "skill" else None
    return LibraryItem(
        id=row["id"],
        kind=kind,
        name=row["name"],
        title=title_of(core, row, head),
        summary=summary_of(core, row, head),
        definition=_definition(core, row),
        source=row["source"],
        used_by=used_by(core, row, heres),
        locked=locked_tool(row["name"]) if kind == "tool" else None,
        always=kind == "tool" and row["name"] in hermes_tools_module().ALWAYS,
        services=hermes_tools_module().providers(row["name"]) if kind == "tool" else [],
        service=tool_service(core, row["name"], services) if kind == "tool" else None,
        workspace_id=row["workspace_id"],
    )


def _agent_item(agent: team.Agent) -> LibraryItem:
    """A member as the web shows it, from its Hermes profile."""
    return LibraryItem(
        id=agent.id,
        kind="agent",
        name=agent.name,
        title=agent.title,
        summary=agent.summary,
        definition=agent.definition,
        source="hermes",
        used_by=[agent.workspace_id] if agent.on else [],
        workspace_id=agent.workspace_id,
    )


def list_items(
    core: Core, kind: Kind | None = None, workspace_id: str | None = None
) -> list[LibraryItem]:
    ensure_tools(core)
    if workspace_id is not None:
        require_workspace(core, workspace_id)
        if kind == "agent":
            return [_agent_item(a) for a in team.members(core, workspace_id)]
        if kind == "mcp":
            adopt_servers(core, workspace_id)
    elif kind == "mcp":
        share_servers(core)
        alive = every_here(core)
        return [_item(core, r, alive) for r in repo.list_templates(core.db)]
    if kind == "skill":
        if workspace_id is None:
            return []  # every skill is a workspace's own (its Settings)
        here = {workspace_id: hc.here(core, workspace_id)}
        # AGOS's background skills (team-design) never reach the owner's lists.
        return [_item(core, r, here) for r in workspace_skills_module().shown(core, workspace_id)]
    heres = all_here(core) if kind not in ("agent", "mcp") else None
    services = None
    if kind in (None, "tool"):
        from agos_core.actions import tool_services

        services = tool_services.chosen(core)  # once for the whole list
    return [_item(core, r, heres, services) for r in repo.list_items(core.db, kind, workspace_id)]


def save_item(
    core: Core,
    item_id: int | None,
    *,
    kind: Kind,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
    source: str = "created",
    workspace_id: str | None = None,
) -> int:
    """Plugins are shared by every workspace. An agent, a skill or an MCP server
    belongs to ONE workspace (`workspace_id`): the same name can exist in two
    projects as two separate items, and no project sees another's."""
    if kind == "tool":
        raise ActionError("Tools come with the engine; turn them on per workspace.")
    if kind == "skill":
        if workspace_id is None:
            raise ActionError("A skill is made inside a workspace (its Settings → Skills).")
        if item_id is None:
            new_id: int = workspace_skills_module().create(
                core,
                workspace_id,
                name,
                title=title,
                given=definition,
                source=source,
            )
            return new_id
        saved: int = workspace_skills_module().save(
            core, workspace_id, item_id, name=name, title=title, given=definition
        )
        return saved
    if kind == "agent":
        return _save_agent(core, item_id, name, title, summary, definition, workspace_id)
    if kind == "mcp" and workspace_id is None:
        try:
            lib.check_name(name)
            clean, summary = _checked(kind, name, summary, definition)
        except LibraryError as error:
            raise ActionError(str(error)) from error
        return _save_template(
            core, item_id, name, title.strip() or lib.readable_title(name), summary, clean
        )
    if kind in OWNED and item_id is None:
        assert workspace_id is not None
        require_workspace(core, workspace_id)
    if kind not in OWNED:
        workspace_id = None
    try:
        lib.check_name(name)
        clean, summary = _checked(kind, name, summary, definition)
    except LibraryError as error:
        raise ActionError(str(error)) from error
    title = title.strip() or lib.readable_title(name)
    if kind == "mcp":
        return _save_mcp(core, item_id, name, title, summary, clean, source, workspace_id)
    if item_id is None:
        if repo.find_item(core.db, kind, name, workspace_id) is not None:
            where = " in this workspace" if kind in OWNED else ""
            raise ActionError(f"There is already a {kind} named {name}{where}.", 409)
        with transaction(core.db):
            new_id = repo.insert_item(
                core.db,
                kind=kind,
                name=name,
                title=title,
                summary=summary,
                definition=_stored(kind, clean),
                source=source,
                workspace_id=workspace_id,
            )
        return new_id
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != kind:
        raise NotFoundError("This item")
    if kind in OWNED and workspace_id is not None and row["workspace_id"] != workspace_id:
        raise NotFoundError(f"This {kind}")  # another workspace's: out of reach
    if row["name"] != name:
        raise ActionError("The name can't change; duplicate it instead.")
    repo.update_item(
        core.db, item_id, title=title, summary=summary, definition=_stored(kind, clean)
    )
    resync_users(core, item_id)
    return item_id


def _save_agent(
    core: Core,
    item_id: int | None,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
    workspace_id: str | None,
) -> int:
    """A member of a workspace's team: written into its Hermes profile only."""
    if item_id is None:
        if workspace_id is None:
            raise ActionError("An agent is created inside a workspace (its team).")
        require_workspace(core, workspace_id)
        new_id = team.save(
            core,
            workspace_id,
            name,
            title=title.strip() or lib.readable_title(name),
            summary=summary,
            definition=definition,
            new=True,
        )
        # A new member: its profile is set up, the Co-Founder's board dispatches to it.
        _applied_or_raise(core, workspace_id)
        return new_id
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "agent" or not row["workspace_id"]:
        raise NotFoundError("This agent")
    ws = str(row["workspace_id"])
    if workspace_id is not None and ws != workspace_id:
        raise NotFoundError("This agent")  # another workspace's: out of reach
    if row["name"] != name:
        raise ActionError("The name can't change; duplicate it instead.")
    return team.save(
        core,
        ws,
        name,
        title=title.strip() or lib.readable_title(name),
        summary=summary,
        definition=definition,
        new=False,
    )


def _save_mcp(
    core: Core,
    item_id: int | None,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
    source: str,
    workspace_id: str | None,
) -> int:
    """An MCP server is an entry of its workspace's Hermes `mcp_servers`; AGOS's row
    is only its id, name and how the owner calls it."""
    from agos_core.engine.apps import SERVER_PREFIX

    if item_id is None:
        assert workspace_id is not None
        if name.startswith(SERVER_PREFIX):
            raise ActionError(f"Names starting with {SERVER_PREFIX} are the apps' own.")
        adopt_servers(core, workspace_id)
        if repo.find_item(core.db, "mcp", name, workspace_id) is not None:
            raise ActionError(f"There is already a mcp named {name} in this workspace.", 409)
        if not hc.has_root(core, workspace_id):
            raise ActionError("This workspace's agent isn't set up yet.", 409)
        with workspace_lock(workspace_id):
            new_id = repo.insert_item(
                core.db,
                kind="mcp",
                name=name,
                title=title,
                summary=summary,
                definition={},
                source=source,
                workspace_id=workspace_id,
            )
            try:
                # Made for this workspace: on in it straight away.
                change(
                    core,
                    workspace_id,
                    lambda here: here.mcp.__setitem__(
                        name,
                        hc.entry_of(name, definition, on=True, allowed_tools=[], has_key=False),
                    ),
                )
            except BaseException:
                repo.delete_item(core.db, new_id)
                raise
        if not source.startswith(f"{TEMPLATE}:"):
            share_servers(core)
        return new_id
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "mcp":
        raise NotFoundError("This item")
    if workspace_id is not None and row["workspace_id"] != workspace_id:
        raise NotFoundError("This mcp")  # another workspace's: out of reach
    if row["name"] != name:
        raise ActionError("The name can't change; duplicate it instead.")
    shared_id = _template_id(row)
    if shared_id is not None:
        # One definition for every workspace that has it: changing it here
        # changes it everywhere (each keeps its own switch, key and sign-in).
        shared_row = repo.get_item(core.db, shared_id)
        if shared_row is not None and is_template(shared_row):
            _save_template(core, shared_id, str(shared_row["name"]), title, summary, definition)
            return item_id
    ws = str(row["workspace_id"])

    def edit(here: hc.Here) -> None:
        old = here.mcp.get(name)
        if old is None:
            raise NotFoundError("This MCP server")
        here.mcp[name] = _entry(name, old, has_key=name in here.keys, definition=definition)

    change(core, ws, edit)
    repo.update_item(core.db, item_id, title=title, summary=summary, definition={})
    return item_id


def _save_template(
    core: Core,
    item_id: int | None,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
) -> int:
    """A shared MCP definition (no workspace, no secret). Changing it changes every
    workspace's copy (its switch, allowed tools, key and sign-in stay)."""
    from agos_core.engine.apps import SERVER_PREFIX

    if item_id is None:
        if name.startswith(SERVER_PREFIX):
            raise ActionError(f"Names starting with {SERVER_PREFIX} are the apps' own.")
        if repo.find_item(core.db, "mcp", name, None) is not None:
            raise ActionError(f"There is already an MCP server named {name}.", 409)
        return repo.insert_item(
            core.db,
            kind="mcp",
            name=name,
            title=title,
            summary=summary,
            definition=definition,
            source=TEMPLATE,
        )
    row = repo.get_item(core.db, item_id)
    if row is None or not is_template(row):
        raise NotFoundError("This MCP server")
    if row["name"] != name:
        raise ActionError("The name can't change; duplicate it instead.")
    repo.update_item(core.db, item_id, title=title, summary=summary, definition=definition)
    failed = []
    for copy in repo.template_copies(core.db, item_id):
        ws, here_name = str(copy["workspace_id"]), str(copy["name"])

        def edit(here: hc.Here, n: str = here_name) -> None:
            old = here.mcp.get(n)
            if old is not None:
                here.mcp[n] = _entry(n, old, has_key=n in here.keys, definition=definition)

        try:
            change(core, ws, edit)
            repo.update_item(core.db, int(copy["id"]), title=title, summary=summary, definition={})
        except ActionError as error:
            log.warning("shared MCP %s not updated in %s: %s", name, ws, error)
            failed.append(_workspace_name(core, ws))
    if failed:
        raise ActionError(f"Saved, but not updated in: {', '.join(failed)}.", 503)
    return item_id


def _workspace_name(core: Core, workspace_id: str) -> str:
    from agos_core.db.workspaces import name_of

    return name_of(core.db, workspace_id)


def _template_id(row: Any) -> int | None:
    source = str(row["source"] or "")
    if not source.startswith(f"{TEMPLATE}:"):
        return None
    try:
        return int(source.split(":", 1)[1])
    except ValueError:
        return None


def _checked(
    kind: Kind, name: str, summary: str, definition: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    if kind == "skill":
        text = str(definition.get("text") or "")
        skill_name, description = lib.check_skill(text)
        if skill_name != name:
            raise LibraryError("The name in the frontmatter must match the skill's name.")
        extra: dict[str, Any] = {
            k: str(definition[k])[:300] for k in ("identifier",) if definition.get(k)
        }
        from agos_core.actions.team_files import clean_files

        if "files" in definition:  # references, scripts… (exactly these)
            extra["files"] = clean_files(definition.get("files"))
        return {"text": text, **extra}, description
    if kind == "mcp":
        return lib.check_mcp(definition), summary.strip()
    if kind == "agent":
        return lib.check_agent(definition), summary.strip()
    if kind == "plugin":
        plugin = str(definition.get("plugin") or name).strip()
        lib.check_name(plugin.replace("_", "-"))
        return {"plugin": plugin}, summary.strip()
    raise LibraryError("Unknown kind.")
