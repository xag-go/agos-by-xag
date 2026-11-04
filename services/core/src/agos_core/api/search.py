"""Workspace search (Step 55) and the status cards' page (Step 55), one read each."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from agos_core.actions import search as search_actions
from agos_core.actions import status_cards
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["search"])

SearchType = Literal["card", "comment", "document", "artifact", "agent", "goal", "skill", "chat"]


class SearchResult(Record):
    type: SearchType
    id: str
    title: str
    excerpt: str
    # [start, end) of each matched word in `excerpt` (the page highlights them).
    marks: list[list[int]] = Field(default_factory=list)
    href: str
    where: str = ""
    at: float = 0


class SearchCounts(Record):
    card: int = 0
    comment: int = 0
    document: int = 0
    artifact: int = 0
    agent: int = 0
    goal: int = 0
    skill: int = 0
    chat: int = 0


class SearchPage(Record):
    query: str
    terms: list[str]
    results: list[SearchResult]
    counts: SearchCounts
    took_ms: float


@router.get("/workspaces/{workspace_id}/search")
async def search(
    core: CoreDep,
    workspace_id: str,
    q: str = Query(default="", max_length=200),
    types: str = Query(default="", max_length=200, description="Comma-separated types"),
) -> SearchPage:
    wanted = [t for t in types.split(",") if t.strip()] or None
    found = await asyncio.to_thread(search_actions.search, core, workspace_id, q, wanted)
    return SearchPage.model_validate(found)


# ---- status cards -------------------------------------------------------------------


Scope = Literal["workspace", "goal", "project", "member", "query"]
Policy = Literal["daily", "weekly", "manual"]


class StatusRevision(Record):
    n: int
    at: str
    who: str
    why: str


class StatusJob(Record):
    next_at: str | None = None
    last_at: str | None = None
    last_status: str | None = None
    # When Hermes's monitor last saw the scope change (its monitor_state).
    changed_at: str | None = None
    problem: str | None = None


class StatusCard(Record):
    id: int
    title: str
    scope: Scope
    scope_ref: str
    scope_label: str
    policy: Policy
    time: str
    day: int | None = None
    summary: str
    revision: int
    written_at: str
    written_by: str
    revisions: list[StatusRevision]
    refresh_asked_at: str | None = None
    job: StatusJob | None = None


class StatusPlanItem(Record):
    id: int
    level: str
    title: str


class StatusMember(Record):
    name: str
    title: str


class StatusPage(Record):
    cards: list[StatusCard]
    plan: list[StatusPlanItem]
    members: list[StatusMember]


class StatusCardBody(Body):
    title: str = Field(min_length=1, max_length=120)
    scope: Scope
    scope_ref: str = Field(default="", max_length=200)
    policy: Policy = "daily"
    time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    day: int | None = Field(default=None, ge=0, le=6)


class StatusRevisionText(Record):
    n: int
    content: str
    diff: str


@router.get("/workspaces/{workspace_id}/status-cards")
async def get_status_cards(core: CoreDep, workspace_id: str) -> StatusPage:
    return StatusPage.model_validate(await asyncio.to_thread(status_cards.page, core, workspace_id))


@router.post("/workspaces/{workspace_id}/status-cards", status_code=201)
async def add_status_card(core: CoreDep, workspace_id: str, body: StatusCardBody) -> StatusCard:
    made = await asyncio.to_thread(
        lambda: status_cards.create(
            core,
            workspace_id,
            title=body.title,
            scope=body.scope,
            scope_ref=body.scope_ref,
            policy=body.policy,
            time=body.time,
            day=body.day,
        )
    )
    return StatusCard.model_validate(made)


@router.put("/workspaces/{workspace_id}/status-cards/{card_id}")
async def change_status_card(
    core: CoreDep, workspace_id: str, card_id: int, body: StatusCardBody
) -> StatusCard:
    changed = await asyncio.to_thread(
        lambda: status_cards.update(
            core,
            workspace_id,
            card_id,
            title=body.title,
            scope=body.scope,
            scope_ref=body.scope_ref,
            policy=body.policy,
            time=body.time,
            day=body.day,
        )
    )
    return StatusCard.model_validate(changed)


@router.post("/workspaces/{workspace_id}/status-cards/{card_id}/refresh")
async def refresh_status_card(core: CoreDep, workspace_id: str, card_id: int) -> StatusCard:
    return StatusCard.model_validate(
        await asyncio.to_thread(status_cards.refresh, core, workspace_id, card_id)
    )


@router.delete("/workspaces/{workspace_id}/status-cards/{card_id}", status_code=204)
async def delete_status_card(core: CoreDep, workspace_id: str, card_id: int) -> None:
    await asyncio.to_thread(status_cards.delete, core, workspace_id, card_id)


@router.get("/workspaces/{workspace_id}/status-cards/{card_id}/revisions/{n}")
async def status_card_revision(
    core: CoreDep, workspace_id: str, card_id: int, n: int
) -> StatusRevisionText:
    return StatusRevisionText.model_validate(
        await asyncio.to_thread(status_cards.revision, core, workspace_id, card_id, n)
    )
