"""The Founder's box (actions/founder.py): the owner himself beside the Co-Founder,
his tasks on Hermes's board (cards assigned to `founder`), Done, and his title."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import founder
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["founder"])


class FounderTask(Record):
    id: str
    title: str
    body: str = ""
    status: str
    created_at: int = 0
    completed_at: int | None = None
    # The cards it waits on (its parents) and the ones that wait on it.
    waits_on: list[str] = Field(default_factory=list)
    unblocks: list[str] = Field(default_factory=list)
    can_finish: bool = False


class FounderView(Record):
    name: str = ""
    title: str
    shown: str = ""
    open: list[FounderTask]
    done: list[FounderTask]
    open_count: int


class FounderWho(Record):
    name: str = ""
    title: str
    shown: str = ""


class FounderWhoBody(Body):
    title: str = Field(max_length=200)


class FounderDoneBody(Body):
    note: str = Field(default="", max_length=4000)


@router.get("/workspaces/{workspace_id}/founder")
def get_founder(core: CoreDep, workspace_id: str) -> FounderView:
    return FounderView.model_validate(founder.view(core, workspace_id))


@router.put("/workspaces/{workspace_id}/founder")
async def save_founder(core: CoreDep, workspace_id: str, body: FounderWhoBody) -> FounderWho:
    require_workspace(core, workspace_id)
    return FounderWho.model_validate(
        await asyncio.to_thread(founder.save_who, core, workspace_id, body.title)
    )


@router.post("/workspaces/{workspace_id}/founder/{card_id}/done", status_code=204)
async def founder_done(
    core: CoreDep, workspace_id: str, card_id: str, body: FounderDoneBody
) -> None:
    """He finished one of his tasks: Hermes's complete (the cards waiting on it go on)."""
    require_workspace(core, workspace_id)
    await asyncio.to_thread(lambda: founder.done(core, workspace_id, card_id, body.note))
