"""A card's runtime services and the live chips of linked outside objects (Step 59)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from agos_core.actions import card_services, external_objects
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["card-services"])

CARD = r"^[A-Za-z0-9_-]{1,64}$"


class CardService(Record):
    id: int
    card: str
    label: str
    command: str
    port: int
    process_id: str
    running: bool
    answering: bool
    preview: str
    started_at: str
    stopped_at: str | None = None


class PreviewTarget(Record):
    host: str
    port: int


@router.get("/workspaces/{workspace_id}/kanban/{card_id}/services")
async def card_services_list(core: CoreDep, workspace_id: str, card_id: str) -> list[CardService]:
    """The dev servers / previews the card's worker started (newest first)."""
    require_workspace(core, workspace_id)
    found = await asyncio.to_thread(card_services.of_card, core, workspace_id, card_id)
    return [CardService.model_validate(s) for s in found]


@router.post("/workspaces/{workspace_id}/services/{service_id}/stop")
async def stop_service(core: CoreDep, workspace_id: str, service_id: int) -> CardService:
    require_workspace(core, workspace_id)
    shown = await asyncio.to_thread(card_services.stop, core, workspace_id, service_id)
    return CardService.model_validate(shown)


@router.get("/workspaces/{workspace_id}/preview-target")
async def preview_target(
    core: CoreDep,
    workspace_id: str,
    card: str = Query(pattern=CARD),
    port: int = Query(ge=1024, le=65535),
) -> PreviewTarget:
    """Where the web's /preview/<ws>/<card>/<port>/ proxy goes (a running service only)."""
    require_workspace(core, workspace_id)
    found = await asyncio.to_thread(card_services.target, core, workspace_id, card, port)
    return PreviewTarget.model_validate(found)


class ExternalObject(Record):
    url: str
    kind: Literal["github_pr", "github_issue", "linear", "jira"]
    ok: bool
    key: str = ""
    title: str = ""
    state: str = ""
    state_label: str = ""
    done: bool = False
    why: str = ""


class ExternalObjectsBody(Body):
    urls: list[str] = Field(max_length=external_objects.MAX_LINKS)


@router.post("/workspaces/{workspace_id}/external-objects")
async def external_objects_status(
    core: CoreDep, workspace_id: str, body: ExternalObjectsBody
) -> list[ExternalObject]:
    """Live chips for the links in a card's text and comments (known kinds only)."""
    require_workspace(core, workspace_id)
    urls = [u[:500] for u in body.urls]
    found = await asyncio.to_thread(external_objects.resolve, core, workspace_id, urls)
    return [ExternalObject.model_validate(o) for o in found]
