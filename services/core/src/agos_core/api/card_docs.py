"""A card's documents: files in the workspace folder, a revision per save, passage
comments (actions/card_docs.py)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import card_docs as actions
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(prefix="/workspaces/{workspace_id}/kanban/{card_id}/docs", tags=["card-docs"])


class CardDocument(Record):
    """One document in the card's list (and the Artifacts page)."""

    key: str
    revision: int
    size: int
    updated_at: str
    who: str
    open_annotations: int


class CardDocRevision(Record):
    n: int
    at: str
    who: str
    why: str
    vote: int = 0


class CardDocAnnotation(Record):
    id: int
    revision: int
    quote: str
    prefix: str
    suffix: str
    start: int
    end: int
    body: str
    author: str
    anchor: str
    anchored_revision: int
    resolved: bool
    created_at: str


class CardDocOpen(Record):
    key: str
    content: str
    revision: int
    dirty: bool
    revisions: list[CardDocRevision]
    annotations: list[CardDocAnnotation]


class CardDocSaved(Record):
    saved: bool
    revision: int
    annotations: dict[str, int] = Field(default_factory=dict)


class CardDocRevisionText(Record):
    n: int
    content: str
    diff: str


class CardDocSave(Body):
    content: str = Field(max_length=2_000_000)
    why: str = Field(default="", max_length=300)
    # The revision the editor opened; None only for a new document.
    base_revision: int | None = None


class CardDocRestore(Body):
    revision: int = Field(ge=1)


class NewAnnotation(Body):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=5000)


class Resolved(Body):
    resolved: bool = True


def _ws(core: Any, workspace_id: str) -> str:
    require_workspace(core, workspace_id)
    return workspace_id


@router.get("")
async def list_docs(core: CoreDep, workspace_id: str, card_id: str) -> list[CardDocument]:
    ws = _ws(core, workspace_id)
    found = await asyncio.to_thread(actions.list_docs, core, ws, card_id)
    return [CardDocument.model_validate(d) for d in found]


@router.get("/{key}")
async def get_doc(core: CoreDep, workspace_id: str, card_id: str, key: str) -> CardDocOpen:
    ws = _ws(core, workspace_id)
    return CardDocOpen.model_validate(
        await asyncio.to_thread(actions.get_doc, core, ws, card_id, key)
    )


@router.put("/{key}")
async def save_doc(
    core: CoreDep, workspace_id: str, card_id: str, key: str, body: CardDocSave
) -> CardDocSaved:
    """The owner's save: 409 when the document moved since he opened it."""
    ws = _ws(core, workspace_id)
    return CardDocSaved.model_validate(
        await asyncio.to_thread(
            lambda: actions.save(
                core,
                ws,
                card_id,
                key,
                body.content,
                who="Owner",
                why=body.why.strip() or "edited by the owner",
                base_revision=body.base_revision,
            )
        )
    )


@router.post("/{key}/restore")
async def restore_doc(
    core: CoreDep, workspace_id: str, card_id: str, key: str, body: CardDocRestore
) -> CardDocSaved:
    """A new revision with an older one's text."""
    ws = _ws(core, workspace_id)
    return CardDocSaved.model_validate(
        await asyncio.to_thread(
            lambda: actions.restore(core, ws, card_id, key, body.revision, who="Owner")
        )
    )


@router.get("/{key}/revisions/{n}")
async def revision(
    core: CoreDep, workspace_id: str, card_id: str, key: str, n: int
) -> CardDocRevisionText:
    ws = _ws(core, workspace_id)
    return CardDocRevisionText.model_validate(
        await asyncio.to_thread(actions.revision, core, ws, card_id, key, n)
    )


@router.post("/{key}/annotations", status_code=201)
async def annotate(
    core: CoreDep, workspace_id: str, card_id: str, key: str, body: NewAnnotation
) -> CardDocAnnotation:
    ws = _ws(core, workspace_id)
    return CardDocAnnotation.model_validate(
        await asyncio.to_thread(
            lambda: actions.annotate(
                core, ws, card_id, key, start=body.start, end=body.end, body=body.body
            )
        )
    )


@router.post("/{key}/annotations/{annotation_id}/resolve", status_code=204)
async def resolve(
    core: CoreDep, workspace_id: str, card_id: str, key: str, annotation_id: int, body: Resolved
) -> None:
    ws = _ws(core, workspace_id)
    await asyncio.to_thread(actions.resolve, core, ws, annotation_id, body.resolved)


@router.delete("/{key}/annotations/{annotation_id}", status_code=204)
async def remove_annotation(
    core: CoreDep, workspace_id: str, card_id: str, key: str, annotation_id: int
) -> None:
    ws = _ws(core, workspace_id)
    await asyncio.to_thread(actions.remove_annotation, core, ws, annotation_id)
