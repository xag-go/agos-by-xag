"""The workspace's Artifacts page (actions/artifacts.py) and the owner's 👍 / 👎
(actions/feedback.py)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import artifacts as actions
from agos_core.actions import feedback
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["artifacts"])


class Artifact(Record):
    ref: str  # attachment:<card>:<id> | document:<card>:<key>
    source: Literal["attachment", "document"]
    card: str
    card_title: str
    name: str
    kind: Literal["image", "pdf", "html", "md", "other"]
    size: int
    member: str
    at: int
    attachment_id: int | None
    key: str
    revision: int
    review: Literal["", "approved", "needs_work"]
    review_note: str


class Artifacts(Record):
    items: list[Artifact]
    # Why the board's files are missing, when they are ("" otherwise).
    note: str = ""


class ArtifactReview(Body):
    artifact: str = Field(min_length=1, max_length=200)
    state: Literal["", "approved", "needs_work"]
    note: str = Field(default="", max_length=2000)


class Promote(Body):
    card: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    attachment: int = Field(ge=1)
    key: str = Field(default="", max_length=70)


class Promoted(Record):
    card: str
    key: str
    revision: int


class Vote(Body):
    kind: Literal["reply", "revision"]
    ref: str = Field(min_length=1, max_length=200)
    vote: Literal[-1, 0, 1]
    note: str = Field(default="", max_length=2000)
    # What the item is, in words (the agent reads it with the vote).
    subject: str = Field(default="", max_length=2000)


class Voted(Record):
    vote: int


def _ws(core: Any, workspace_id: str) -> str:
    require_workspace(core, workspace_id)
    return workspace_id


@router.get("/artifacts")
async def artifacts_page(core: CoreDep, workspace_id: str) -> Artifacts:
    ws = _ws(core, workspace_id)
    return Artifacts.model_validate(await asyncio.to_thread(actions.page, core, ws))


@router.put("/artifacts/review", status_code=204)
async def review(core: CoreDep, workspace_id: str, body: ArtifactReview) -> None:
    ws = _ws(core, workspace_id)
    await asyncio.to_thread(actions.review, core, ws, body.artifact, body.state, body.note)


@router.post("/artifacts/promote", status_code=201)
async def promote(core: CoreDep, workspace_id: str, body: Promote) -> Promoted:
    """A markdown attachment becomes a document of its card (its first revision)."""
    ws = _ws(core, workspace_id)
    return Promoted.model_validate(
        await asyncio.to_thread(actions.promote, core, ws, body.card, body.attachment, body.key)
    )


@router.post("/feedback")
async def vote(core: CoreDep, workspace_id: str, body: Vote) -> Voted:
    """👍 / 👎 on a reply or a document revision; said into Hermes's learning."""
    ws = _ws(core, workspace_id)
    return Voted.model_validate(
        await asyncio.to_thread(
            lambda: feedback.vote(
                core,
                ws,
                kind=body.kind,
                ref=body.ref,
                value=body.vote,
                note=body.note,
                subject=body.subject,
            )
        )
    )
