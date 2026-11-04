"""The library (Settings) and each workspace's own items and connectors."""

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header
from pydantic import Field

from agos_core.actions import library as actions
from agos_core.actions import mcp_signin
from agos_core.actions import workspace_skills as skills
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.library import (
    Connector,
    FoundItem,
    GithubTokenState,
    Inspected,
    LibraryItem,
    McpTest,
)
from agos_core.actions.workspace_skills import CopyableSkill, Installed, Update
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body, Created
from agos_core.ops import idempotency

router = APIRouter(tags=["library"])

KindParam = Literal["skill", "agent", "mcp", "plugin", "tool"]


class ItemBody(Body):
    name: str = Field(min_length=1, max_length=63)
    title: str = Field(default="")
    summary: str = Field(default="")
    definition: dict[str, Any] = Field(default_factory=dict)


class DuplicateBody(Body):
    name: str = Field(min_length=1, max_length=63)


class DeletedItem(Body):
    used_by: list[str]


class ConnectorBody(Body):
    on: bool
    allowed_tools: list[str] = Field(default_factory=list, max_length=200)
    local: str = Field(default="")


class SecretBody(Body):
    value: str | None = Field(default=None, max_length=4000)


@router.get("/library")
def list_items(core: CoreDep, kind: KindParam | None = None) -> list[LibraryItem]:
    # Agents and skills are per workspace (GET /workspaces/{id}/agents, /skills);
    # the global library holds MCP templates, plugins and tools.
    if kind in ("agent", "skill"):
        return []
    return [i for i in actions.list_items(core, kind) if i.kind != "agent"]


class GithubTokenBody(Body):
    token: str = Field(min_length=1, max_length=400)


@router.get("/library/github-token")
async def github_token(core: CoreDep) -> GithubTokenState:
    """What Hermes's Skills Hub uses to read GitHub (its own GitHubAuth)."""
    return await asyncio.to_thread(actions.github_token_status, core)


@router.put("/library/github-token")
async def save_github_token(core: CoreDep, body: GithubTokenBody) -> GithubTokenState:
    """Hermes saves it (GITHUB_TOKEN in its .env) for the library's hub only."""
    return await asyncio.to_thread(actions.save_github_token, core, body.token)


@router.delete("/library/github-token", status_code=204)
async def remove_github_token(core: CoreDep) -> None:
    await asyncio.to_thread(actions.remove_github_token, core)


@router.post("/library/{kind}", status_code=201)
def create_item(core: CoreDep, kind: KindParam, body: ItemBody) -> Created:
    if kind == "agent":
        raise ActionError("Agents are created in a workspace's Hierarchy.", 400)
    if kind == "skill":
        raise ActionError("Skills are made in a workspace's Settings → Skills.", 400)
    # An MCP server here is a shared definition (Settings → Connectors): each
    # workspace adds its own copy and signs in or gives its key there.
    return Created(
        id=actions.save_item(
            core,
            None,
            kind=kind,
            name=body.name.strip(),
            title=body.title,
            summary=body.summary,
            definition=body.definition,
        )
    )


@router.put("/library/{kind}/{item_id}")
def update_item(core: CoreDep, kind: KindParam, item_id: int, body: ItemBody) -> None:
    actions.save_item(
        core,
        item_id,
        kind=kind,
        name=body.name.strip(),
        title=body.title,
        summary=body.summary,
        definition=body.definition,
    )


@router.post("/library/items/{item_id}/duplicate", status_code=201)
def duplicate_item(core: CoreDep, item_id: int, body: DuplicateBody) -> Created:
    return Created(id=actions.duplicate_item(core, item_id, body.name.strip()))


# ---- a workspace's own agents (its team) -----------------------------------------


class CopyAgentBody(Body):
    item_id: int
    name: str = Field(default="", max_length=63)


@router.get("/workspaces/{workspace_id}/agents")
def list_agents(core: CoreDep, workspace_id: str) -> list[LibraryItem]:
    return actions.list_items(core, "agent", workspace_id)


@router.post("/workspaces/{workspace_id}/agents", status_code=201)
def create_agent(core: CoreDep, workspace_id: str, body: ItemBody) -> Created:
    return Created(
        id=actions.save_item(
            core,
            None,
            kind="agent",
            name=body.name.strip(),
            title=body.title,
            summary=body.summary,
            definition=body.definition,
            workspace_id=workspace_id,
        )
    )


@router.post("/workspaces/{workspace_id}/hires", status_code=201)
def create_own_hire(
    core: CoreDep,
    workspace_id: str,
    body: ItemBody,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> Created:
    """The owner's own New agent (Hierarchy → Create agent): the same rules as every
    hire (its whole kit and model), made at once (his click is his Approve). With an
    Idempotency-Key, a retry or a double click gets the first hire's id."""
    from agos_core.actions import proposals

    require_workspace(core, workspace_id)

    def hire() -> dict[str, Any]:
        made = proposals.own_hire(
            core,
            workspace_id,
            name=body.name.strip(),
            title=body.title,
            summary=body.summary,
            definition=dict(body.definition or {}),
        )
        return {"id": made}

    found = idempotency.once(
        core, "own_hire", idempotency_key, hire, workspace_id=workspace_id, title="Hire"
    )
    return Created(id=found["id"])


@router.put("/workspaces/{workspace_id}/agents/{item_id}", status_code=204)
def update_agent(core: CoreDep, workspace_id: str, item_id: int, body: ItemBody) -> None:
    actions.save_item(
        core,
        item_id,
        kind="agent",
        name=body.name.strip(),
        title=body.title,
        summary=body.summary,
        definition=body.definition,
        workspace_id=workspace_id,
    )


@router.delete("/workspaces/{workspace_id}/agents/{item_id}", status_code=204)
def delete_agent(core: CoreDep, workspace_id: str, item_id: int) -> None:
    actions.delete_item(core, item_id, workspace_id)


class ReportsToBody(Body):
    # "" = the Co-Founder; else a member's name of this workspace (no loops).
    reports_to: str = Field(default="", max_length=63)


@router.put("/workspaces/{workspace_id}/agents/{item_id}/reports-to", status_code=204)
def set_reports_to(core: CoreDep, workspace_id: str, item_id: int, body: ReportsToBody) -> None:
    """Who the member reports to in the org chart (its Hermes profile keeps it)."""
    from agos_core.actions import team

    agent = team.by_id(core, item_id)
    if agent is None or agent.workspace_id != workspace_id:
        raise NotFoundError("This agent")
    team.set_reports_to(core, workspace_id, agent.name, body.reports_to)


class CopyableAgent(Body):
    id: int
    title: str
    name: str
    workspace: str


@router.get("/workspaces/{workspace_id}/agents/copyable")
def copyable_agents(core: CoreDep, workspace_id: str) -> list[CopyableAgent]:
    """For the owner's "Copy from another project" dialog only (never given to a
    Co-Founder): the other projects' agents, by name."""
    return [
        CopyableAgent(id=a["id"], title=a["title"], name=a["name"], workspace=a["workspace"])
        for a in actions.copyable_agents(core, workspace_id)
    ]


@router.post("/workspaces/{workspace_id}/agents/copy", status_code=201)
def copy_agent(core: CoreDep, workspace_id: str, body: CopyAgentBody) -> Created:
    """Only on the owner's request: a copy of another project's agent, as this
    team's own. The original is never touched and the two never share anything."""
    return Created(
        id=actions.copy_agent(core, body.item_id, workspace_id, body.name.strip() or None)
    )


@router.delete("/library/items/{item_id}")
def delete_item(core: CoreDep, item_id: int) -> DeletedItem:
    return DeletedItem(used_by=actions.delete_item(core, item_id))


@router.post("/library/items/{item_id}/test")
def test_item(core: CoreDep, item_id: int, workspace: str | None = None) -> McpTest:
    return actions.test_mcp(core, item_id, workspace)


@router.get("/workspaces/{workspace_id}/connectors")
def list_connectors(core: CoreDep, workspace_id: str) -> list[Connector]:
    return actions.list_connectors(core, workspace_id)


@router.put("/workspaces/{workspace_id}/connectors/{item_id}", status_code=204)
def set_connector(core: CoreDep, workspace_id: str, item_id: int, body: ConnectorBody) -> None:
    actions.set_connector(
        core, workspace_id, item_id, on=body.on, allowed_tools=body.allowed_tools, local=body.local
    )


@router.put("/workspaces/{workspace_id}/connectors/{item_id}/secret", status_code=204)
def set_secret(core: CoreDep, workspace_id: str, item_id: int, body: SecretBody) -> None:
    actions.set_secret(core, workspace_id, item_id, body.value)


class McpSignIn(Body):
    status: str
    url: str | None = None
    error: str | None = None


@router.post("/workspaces/{workspace_id}/connectors/{item_id}/signin")
async def mcp_sign_in(core: CoreDep, workspace_id: str, item_id: int) -> McpSignIn:
    """Starts Hermes's OAuth sign-in; returns the page to open in the browser."""
    require_workspace(core, workspace_id)
    return McpSignIn.model_validate(
        await asyncio.to_thread(mcp_signin.start, core, workspace_id, item_id)
    )


@router.get("/workspaces/{workspace_id}/connectors/{item_id}/signin")
def mcp_sign_in_status(core: CoreDep, workspace_id: str, item_id: int) -> McpSignIn:
    require_workspace(core, workspace_id)
    return McpSignIn.model_validate(mcp_signin.status(core, workspace_id, item_id))


@router.delete("/workspaces/{workspace_id}/connectors/{item_id}/signin", status_code=204)
async def mcp_sign_out(core: CoreDep, workspace_id: str, item_id: int) -> None:
    require_workspace(core, workspace_id)
    await asyncio.to_thread(mcp_signin.sign_out, core, workspace_id, item_id)


class ImportBody(Body):
    origin: str = Field(min_length=1, max_length=1000)


class IdentifierBody(Body):
    identifier: str = Field(min_length=3, max_length=300)


class InstallBody(IdentifierBody):
    # Hermes's --force: the owner read the scan's findings and installs anyway.
    force: bool = False


@router.get("/library/{kind}/machine")
async def on_this_machine(core: CoreDep, kind: KindParam) -> list[FoundItem]:
    if kind == "skill":
        raise ActionError("Add a skill from the workspace that should have it.", 400)
    return await asyncio.to_thread(actions.on_this_machine, core, kind)


@router.post("/library/{kind}/machine", status_code=201)
async def import_from_machine(core: CoreDep, kind: KindParam, body: ImportBody) -> Created:
    if kind == "skill":
        raise ActionError("Add a skill from the workspace that should have it.", 400)
    return Created(id=await asyncio.to_thread(actions.import_from_machine, core, kind, body.origin))


@router.get("/library/{kind}/web")
async def search_web(core: CoreDep, kind: KindParam, q: str = "") -> list[FoundItem]:
    if kind == "skill":
        raise ActionError("Search skills from the workspace that should have one.", 400)
    return await asyncio.to_thread(actions.search_web, core, kind, q[:100])


class ToolServiceBody(Body):
    provider: str = Field(min_length=1, max_length=120)
    keys: dict[str, str] = Field(default_factory=dict)


@router.put("/library/tools/{name}/service")
async def set_tool_service(core: CoreDep, name: str, body: ToolServiceBody) -> dict[str, Any]:
    """A tool's service (Hermes's list), set up once for every workspace."""
    from agos_core.actions import tool_services

    return await asyncio.to_thread(tool_services.set_service, core, name, body.provider, body.keys)


# ---- MCP servers: each belongs to one workspace (made and seen only there) ----


@router.get("/workspaces/{workspace_id}/mcp")
def list_mcp(core: CoreDep, workspace_id: str) -> list[LibraryItem]:
    return actions.list_items(core, "mcp", workspace_id)


@router.post("/workspaces/{workspace_id}/mcp", status_code=201)
def create_mcp(core: CoreDep, workspace_id: str, body: ItemBody) -> Created:
    return Created(
        id=actions.save_item(
            core,
            None,
            kind="mcp",
            name=body.name.strip(),
            title=body.title,
            summary=body.summary,
            definition=body.definition,
            workspace_id=workspace_id,
        )
    )


@router.put("/workspaces/{workspace_id}/mcp/{item_id}", status_code=204)
def update_mcp(core: CoreDep, workspace_id: str, item_id: int, body: ItemBody) -> None:
    actions.save_item(
        core,
        item_id,
        kind="mcp",
        name=body.name.strip(),
        title=body.title,
        summary=body.summary,
        definition=body.definition,
        workspace_id=workspace_id,
    )


@router.delete("/workspaces/{workspace_id}/mcp/{item_id}", status_code=204)
def delete_mcp(core: CoreDep, workspace_id: str, item_id: int) -> None:
    actions.delete_mcp(core, item_id, workspace_id)


@router.post("/workspaces/{workspace_id}/mcp/{item_id}/test")
async def test_mcp(core: CoreDep, workspace_id: str, item_id: int) -> McpTest:
    return await asyncio.to_thread(actions.test_mcp, core, item_id, workspace_id)


@router.get("/workspaces/{workspace_id}/mcp/machine")
async def mcp_on_this_machine(core: CoreDep, workspace_id: str) -> list[FoundItem]:
    return await asyncio.to_thread(actions.on_this_machine, core, "mcp", workspace_id)


@router.post("/workspaces/{workspace_id}/mcp/machine", status_code=201)
async def import_mcp(core: CoreDep, workspace_id: str, body: ImportBody) -> Created:
    return Created(
        id=await asyncio.to_thread(
            actions.import_from_machine, core, "mcp", body.origin, workspace_id
        )
    )


# ---- skills: each belongs to one workspace (its Co-Founder and team read one folder) ----


@router.get("/workspaces/{workspace_id}/skills")
def list_skills(core: CoreDep, workspace_id: str) -> list[LibraryItem]:
    return actions.list_items(core, "skill", workspace_id)


@router.post("/workspaces/{workspace_id}/skills", status_code=201)
def create_skill(core: CoreDep, workspace_id: str, body: ItemBody) -> Created:
    """A new skill of this workspace (on in it at once; no other workspace moves)."""
    return Created(
        id=actions.save_item(
            core,
            None,
            kind="skill",
            name=body.name.strip(),
            title=body.title,
            summary=body.summary,
            definition=body.definition,
            workspace_id=workspace_id,
        )
    )


@router.put("/workspaces/{workspace_id}/skills/{item_id}", status_code=204)
def update_skill(core: CoreDep, workspace_id: str, item_id: int, body: ItemBody) -> None:
    actions.save_item(
        core,
        item_id,
        kind="skill",
        name=body.name.strip(),
        title=body.title,
        summary=body.summary,
        definition=body.definition,
        workspace_id=workspace_id,
    )


@router.delete("/workspaces/{workspace_id}/skills/{item_id}", status_code=204)
def delete_skill(core: CoreDep, workspace_id: str, item_id: int) -> None:
    """Hermes's curator archives it (recoverable); its row goes."""
    skills.delete(core, workspace_id, item_id)


@router.post("/workspaces/{workspace_id}/skills/{item_id}/duplicate", status_code=201)
def duplicate_skill(core: CoreDep, workspace_id: str, item_id: int, body: DuplicateBody) -> Created:
    return Created(id=skills.duplicate(core, workspace_id, item_id, body.name.strip()))


class CopySkillBody(Body):
    item_id: int
    name: str = Field(default="", max_length=63)


@router.get("/workspaces/{workspace_id}/skills/copyable")
def copyable_skills(core: CoreDep, workspace_id: str) -> list[CopyableSkill]:
    """For the owner's "Copy from another workspace" only (never given to a Co-Founder)."""
    return skills.copyable(core, workspace_id)


@router.post("/workspaces/{workspace_id}/skills/copy", status_code=201)
def copy_skill(core: CoreDep, workspace_id: str, body: CopySkillBody) -> Created:
    """An independent copy of another workspace's skill, as this workspace's own."""
    return Created(id=skills.copy_from(core, workspace_id, body.item_id, body.name.strip() or None))


@router.get("/workspaces/{workspace_id}/skills/machine")
async def skills_on_this_machine(core: CoreDep, workspace_id: str) -> list[FoundItem]:
    return await asyncio.to_thread(skills.on_this_machine, core, workspace_id)


@router.post("/workspaces/{workspace_id}/skills/machine", status_code=201)
async def import_skill(core: CoreDep, workspace_id: str, body: ImportBody) -> Created:
    return Created(
        id=await asyncio.to_thread(skills.import_from_machine, core, workspace_id, body.origin)
    )


@router.get("/workspaces/{workspace_id}/skills/web")
async def search_skills(core: CoreDep, workspace_id: str, q: str = "") -> list[FoundItem]:
    return await asyncio.to_thread(skills.search_web, core, workspace_id, q[:100])


@router.post("/workspaces/{workspace_id}/skills/web/inspect")
async def inspect_skill(core: CoreDep, workspace_id: str, body: IdentifierBody) -> Inspected:
    require_workspace(core, workspace_id)
    return await asyncio.to_thread(actions.inspect_web, core, body.identifier)


@router.post("/workspaces/{workspace_id}/skills/web/install", status_code=201)
async def install_skill(core: CoreDep, workspace_id: str, body: InstallBody) -> Installed:
    """Hermes's hub installs it (its scan) into this workspace's skill folder."""
    return await asyncio.to_thread(
        skills.install_web, core, workspace_id, body.identifier, force=body.force
    )


@router.get("/workspaces/{workspace_id}/skills/updates")
async def skill_updates(core: CoreDep, workspace_id: str) -> list[Update]:
    return await asyncio.to_thread(skills.check_updates, core, workspace_id)


@router.post("/workspaces/{workspace_id}/skills/{item_id}/update", status_code=204)
async def update_skill_from_source(core: CoreDep, workspace_id: str, item_id: int) -> None:
    await asyncio.to_thread(skills.apply_update, core, workspace_id, item_id)
