"""Settings → Export / Import, the ready-made teams, and a member's revisions
(Step 56: F90, F91, F08)."""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import Field

from agos_core.actions import agent_revisions, portability, teams_catalog
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import AgentRevision, Record
from agos_core.domain.models import ModelSelection

router = APIRouter(tags=["templates"])

Strategy = Literal["skip", "rename", "replace"]


class Strategies(Body):
    agents: Strategy = "rename"
    skills: Strategy = "skip"
    automations: Strategy = "rename"
    vision: Strategy = "skip"


class InputOut(Record):
    """A key the bundle's team needs (Hermes's env_requires shape): asked for on
    import, never carried."""

    name: str
    description: str
    required: bool
    kind: str
    app: str


class PreviewAgent(Record):
    name: str
    title: str
    reports_to: str
    exists: bool


class PreviewItem(Record):
    name: str
    exists: bool
    agent: str = ""


class ImportPreview(Record):
    name: str
    slug: str
    kind: str
    description: str
    hash: str
    trust: Literal["markdown_only", "scripts"]
    agents: list[PreviewAgent]
    skills: list[PreviewItem]
    automations: list[PreviewItem]
    vision: bool
    vision_exists: bool
    inputs: list[InputOut]
    not_carried: list[str]


class ImportItem(Record):
    kind: str
    name: str
    result: Literal["created", "renamed", "replaced", "skipped", "failed"]
    as_name: str
    detail: str = ""


class NeedsOwner(Record):
    kind: str
    name: str
    text: str


class ImportReport(Record):
    """The fidelity report: what came in (as what), what needs the owner."""

    workspace_id: str
    items: list[ImportItem]
    needs_owner: list[NeedsOwner]
    problems: list[str]
    not_carried: list[str]


class BundleUpload(Body):
    data: str = Field(min_length=1, max_length=30_000_000)  # the zip, base64
    workspace_id: str | None = None  # None: preview against a new workspace


class ImportBody(BundleUpload):
    name: str = Field(default="", max_length=80)  # a new workspace's name
    default_model: ModelSelection | None = None  # a new workspace's model
    strategies: Strategies = Field(default_factory=Strategies)
    inputs: dict[str, str] = Field(default_factory=dict)
    later: list[str] = Field(default_factory=list)


def _bytes(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ActionError("That file couldn't be read.") from error


@router.get("/workspaces/{workspace_id}/export")
async def export_bundle(core: CoreDep, workspace_id: str) -> Response:
    """The workspace as a readable bundle (zip of markdown + YAML), no secrets."""
    name, data = await asyncio.to_thread(portability.export_zip, core, workspace_id)
    return Response(
        data,
        media_type="application/zip",
        headers={"content-disposition": f'attachment; filename="{name}"'},
    )


@router.post("/import/preview")
async def import_preview(core: CoreDep, body: BundleUpload) -> ImportPreview:
    files = portability.read_zip(_bytes(body.data))
    found = await asyncio.to_thread(portability.preview, core, files, body.workspace_id)
    return ImportPreview.model_validate(found)


def _report(view: dict[str, Any]) -> ImportReport:
    return ImportReport.model_validate(view)


@router.post("/import")
def import_bundle(core: CoreDep, body: ImportBody) -> ImportReport:
    """Into a new workspace (no workspaceId) or an existing one, through AGOS's
    normal writers; a required input left empty and not put off is a 400."""
    files = portability.read_zip(_bytes(body.data))
    report, _found = portability.apply(
        core,
        files,
        workspace_id=body.workspace_id,
        name=body.name,
        default_model=body.default_model,
        strategies=body.strategies.model_dump(),
        inputs=body.inputs,
        later=body.later,
    )
    return _report(report.view())


# ---- ready-made teams --------------------------------------------------------------------


class CatalogAgent(Record):
    name: str
    title: str
    summary: str
    reports_to: str


class CatalogAutomation(Record):
    name: str
    schedule: str
    agent: str


class CatalogTeam(Record):
    slug: str
    name: str
    description: str
    tags: list[str]
    lead: str
    hash: str
    trust: Literal["markdown_only", "scripts"]
    agents: list[CatalogAgent]
    skills: list[str]
    automations: list[CatalogAutomation]
    inputs: list[InputOut]


@router.get("/templates")
def list_templates() -> list[CatalogTeam]:
    return [CatalogTeam.model_validate(t) for t in teams_catalog.teams()]


class InstallBody(Body):
    workspace_id: str | None = None  # None: a new workspace from the template
    name: str = Field(default="", max_length=80)
    default_model: ModelSelection | None = None
    under: str = Field(default="", max_length=63)  # "" = the Co-Founder, else a lead
    strategies: Strategies = Field(default_factory=Strategies)
    inputs: dict[str, str] = Field(default_factory=dict)
    later: list[str] = Field(default_factory=list)


@router.post("/templates/{slug}/install")
def install_template(core: CoreDep, slug: str, body: InstallBody) -> ImportReport:
    return _report(
        teams_catalog.install(
            core,
            slug,
            workspace_id=body.workspace_id,
            name=body.name,
            default_model=body.default_model,
            under=body.under,
            strategies=body.strategies.model_dump(),
            inputs=body.inputs,
            later=body.later,
        )
    )


class DriftItem(Record):
    kind: str
    name: str
    change: Literal["changed", "removed", "added"]
    fields: list[str]


class InstalledTemplate(Record):
    id: int
    slug: str
    name: str
    installed_at: str
    template_changed: bool
    drift: list[DriftItem]
    gone: bool


@router.get("/workspaces/{workspace_id}/templates")
def installed_templates(core: CoreDep, workspace_id: str) -> list[InstalledTemplate]:
    """The ready-made teams this workspace installed and what now differs from them."""
    return [
        InstalledTemplate.model_validate(t) for t in teams_catalog.installed(core, workspace_id)
    ]


# ---- a member's revisions ----------------------------------------------------------------


def _member(core: Any, workspace_id: str, item_id: int) -> str:
    from agos_core.actions import team

    agent = team.by_id(core, item_id)
    if agent is None or agent.workspace_id != workspace_id:
        raise NotFoundError("This agent")
    return agent.name


@router.get("/workspaces/{workspace_id}/agents/{item_id}/revisions")
def agent_revision_list(core: CoreDep, workspace_id: str, item_id: int) -> list[AgentRevision]:
    return agent_revisions.list_for(core, workspace_id, _member(core, workspace_id, item_id))


class Restored(Record):
    n: int | None


@router.post("/workspaces/{workspace_id}/agents/{item_id}/revisions/{n}/restore")
def restore_agent_revision(core: CoreDep, workspace_id: str, item_id: int, n: int) -> Restored:
    """Restore = a new write of revision vN (recorded as 'restored from vN')."""
    done = agent_revisions.restore(core, workspace_id, _member(core, workspace_id, item_id), n)
    return Restored(n=done.get("n"))
