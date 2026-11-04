"""Library sources: skills found on this machine or on the web (Hermes's Skills Hub).
Must not: install anything outside the workspace's own skills folder (save goes through catalog).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.catalog import save_item
from agos_core.actions.services.library.github_token import _with_github_limit
from agos_core.actions.services.library.lifecycle import add_template
from agos_core.actions.services.library.records import TEMPLATE, workspace_skills_module
from agos_core.actions.services.library.sharing import share_servers
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.records import Record
from agos_core.engine import sources
from agos_core.engine.library import Kind, LibraryError
from agos_core.engine.models import hermes_python
from agos_core.hermes_gateway import process as hermes_process

__all__ = [
    "FoundItem",
    "Inspected",
    "import_from_machine",
    "inspect_web",
    "on_this_machine",
    "search_web",
]

# ---- sources: this machine, the web ------------------------------------------------


class FoundItem(Record):
    kind: Literal["skill", "agent", "mcp", "plugin", "tool"]
    name: str
    title: str
    summary: str
    origin: str
    importable: bool
    locked: str | None = None
    trust: str = ""
    in_library: bool = False


class Inspected(Record):
    identifier: str
    preview: str


def _sources(
    core: Core,
    home: Path | None = None,
    *,
    category: str = "",
    extra_env: dict[str, str] | None = None,
) -> sources.Sources:
    """Hermes's sources. `home`: the Hermes home its hub commands install into (a
    workspace's root: actions/workspace_skills.py)."""
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    from agos_core.engine.models import hermes_repo

    settings = core.engine.settings
    return sources.Sources(
        settings,
        hermes_python(settings),
        hermes_repo(settings),
        home,
        category=category,
        extra_env=extra_env,
    )


def _found(
    core: Core, rows: list[sources.Found], workspace_id: str | None = None
) -> list[FoundItem]:
    have = {
        (r["kind"], r["name"])
        for r in repo.list_items(core.db, None, workspace_id)
        if r["kind"] != "agent"
    }
    return [
        FoundItem(**sources.as_dict(f), in_library=(f.kind, f.name) in have) for f in rows if f.name
    ]


def on_this_machine(core: Core, kind: Kind, workspace_id: str | None = None) -> list[FoundItem]:
    if kind == "skill":
        if workspace_id is None:
            raise ActionError("Add a skill from the workspace that should have it.")
        found: list[FoundItem] = workspace_skills_module().on_this_machine(core, workspace_id)
        return found
    src = _sources(core)
    if kind == "mcp":
        share_servers(core)
        mine = [
            sources.Found(
                kind="mcp",
                name=str(r["name"]),
                title=str(r["title"]),
                summary=str(r["summary"]),
                origin=f"{TEMPLATE}:{r['id']}",
                trust="Yours",
            )
            for r in repo.list_templates(core.db)
        ]
        return _found(core, mine + src.machine_mcp(), workspace_id)
    if kind == "plugin":
        return _found(core, src.machine_plugins())
    return []


def import_from_machine(
    core: Core, kind: Kind, origin: str, workspace_id: str | None = None
) -> int:
    """One click: the definition is copied into the library (no secrets). An MCP
    server goes into the workspace it is added from."""
    if kind == "mcp" and origin.startswith(f"{TEMPLATE}:"):
        if workspace_id is None:
            raise ActionError("Add it from the workspace that should use it.")
        try:
            template_id = int(origin.split(":", 1)[1])
        except ValueError:
            raise NotFoundError("This MCP server") from None
        return add_template(core, workspace_id, template_id)
    if kind == "skill":
        if workspace_id is None:
            raise ActionError("Add a skill from the workspace that should have it.")
        made: int = workspace_skills_module().import_from_machine(core, workspace_id, origin)
        return made
    src = _sources(core)
    try:
        if kind == "mcp":
            match = next((f for f in src.machine_mcp() if f.origin == origin), None)
            if match is None or not match.importable:
                raise ActionError((match.locked if match else None) or "Not in Hermes's catalog.")
            url = origin.split("|", 1)[1]
            return save_item(
                core,
                None,
                kind="mcp",
                name=match.name,
                title=match.title,
                summary=match.summary,
                definition={"transport": "http", "url": url},
                source="machine",
                workspace_id=workspace_id,
            )
        if kind == "plugin":
            name = origin.removeprefix("plugin:")
            return save_item(
                core,
                None,
                kind="plugin",
                name=name.replace("_", "-").lower()[:63],
                title=name,
                summary="",
                definition={"plugin": name},
                source="machine",
            )
    except (sources.SourceError, LibraryError) as error:
        raise ActionError(str(error)) from error
    raise ActionError("Nothing to import for this kind.")


def search_web(
    core: Core, kind: Kind, query: str, workspace_id: str | None = None
) -> list[FoundItem]:
    if kind != "skill":
        return on_this_machine(core, kind) if kind == "mcp" else []
    if workspace_id is not None:
        found: list[FoundItem] = workspace_skills_module().search_web(core, workspace_id, query)
        return found
    try:
        return _found(core, _sources(core).search_skills(query))
    except (sources.SourceError, hermes_process.TimeoutExpired) as error:
        raise ActionError(f"The skills hub didn't answer: {error}", 503) from error


def inspect_web(core: Core, identifier: str) -> Inspected:
    try:
        return Inspected(identifier=identifier, preview=_sources(core).inspect_skill(identifier))
    except (sources.SourceError, hermes_process.TimeoutExpired) as error:
        raise ActionError(_with_github_limit(core, str(error)), 400) from error
