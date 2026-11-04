"""The workspace's Kanban page: Hermes's own board, seen and driven from AGOS.

Owns: the page's routes; their shapes are api/kanban_schemas.py's.
Must not: read the database or Hermes itself (the Board service, actions/, does).
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import Field

from agos_core.actions import founder, holds, kanban_board, watchdogs
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.kanban_schemas import (
    BoardColumn,
    BoardFilters,
    BoardGroup,
    BoardSort,
    BoardView,
    CreatedCard,
    KanbanAct,
    KanbanAssign,
    KanbanBoard,
    KanbanCardDetail,
    KanbanCardGoal,
    KanbanCommentBody,
    KanbanEstimate,
    KanbanHold,
    KanbanHoldAction,
    KanbanMember,
    KanbanText,
    Label,
    NewKanbanCard,
    ReviewFlow,
    ThreadResult,
    Watcher,
)
from agos_core.api.schemas import Body, Created
from agos_core.db.records import Record

router = APIRouter(tags=["kanban"])

CARD_ID = r"^[A-Za-z0-9_-]{1,64}$"


def _ws(core: Any, workspace_id: str) -> str:
    require_workspace(core, workspace_id)
    return workspace_id


def _board_with_attention(core: Any, ws: str) -> dict[str, Any]:
    """Hermes's board, each waiting card with its derived state (one read-only
    query of the board: actions/blocked.py attention) and its open pause."""
    from agos_core.actions import blocked, org

    found = kanban_board.board(core, ws)
    states = blocked.attention(core, ws)
    paused = holds.open_holds(core, ws)
    # A card whose member's team a lead above it stalls says so (actions/org.py).
    stalls = org.health(core, ws, org.stuck_from_attention(core, ws, states)).stalls
    for card in found["cards"]:
        stall = stalls.get(str(card.get("member") or ""))
        if stall is not None:
            card["chainStalled"] = stall.words()
        state = states.get(str(card["id"]))
        if state is not None:
            card["attention"] = str(state["state"])
            card["attentionWhy"] = str(state["why"])
        hold = paused.get(str(card["id"]))
        if hold is not None:
            card["holdId"] = int(hold["id"])
    return found


@router.get("/workspaces/{workspace_id}/kanban")
async def get_board(core: CoreDep, workspace_id: str) -> KanbanBoard:
    ws = _ws(core, workspace_id)
    return KanbanBoard.model_validate(await asyncio.to_thread(_board_with_attention, core, ws))


def _card_with_attention(core: Any, ws: str, card_id: str) -> dict[str, Any]:
    from agos_core.actions import blocked, org

    found = kanban_board.card(core, ws, card_id)
    states = blocked.attention(core, ws)
    stall = org.health(core, ws, org.stuck_from_attention(core, ws, states)).stalls.get(
        str(found.get("member") or "")
    )
    if stall is not None:
        found["chainStalled"] = stall.words()
    state = states.get(card_id)
    if state is not None:
        found["attention"] = str(state["state"])
        found["attentionWhy"] = str(state["why"])
    hold = holds.open_holds(core, ws).get(card_id)
    if hold is not None:
        found["holdId"] = int(hold["id"])
    watchdog = watchdogs.by_card(core, ws).get(card_id)
    if watchdog is not None:
        found["watchdogId"] = watchdog
    from agos_core.actions import card_docs

    found["documents"] = card_docs.list_docs(core, ws, card_id)
    return found


@router.get("/workspaces/{workspace_id}/kanban/{card_id}")
async def get_card(core: CoreDep, workspace_id: str, card_id: str) -> KanbanCardDetail:
    ws = _ws(core, workspace_id)
    _check(card_id)
    return KanbanCardDetail.model_validate(
        await asyncio.to_thread(_card_with_attention, core, ws, card_id)
    )


@router.post("/workspaces/{workspace_id}/kanban", status_code=201)
async def create_card(core: CoreDep, workspace_id: str, body: NewKanbanCard) -> CreatedCard:
    ws = _ws(core, workspace_id)
    card_id = await asyncio.to_thread(
        lambda: kanban_board.create(
            core,
            ws,
            body.title,
            body.body,
            body.member,
            criteria=body.criteria,
            model=body.model.model_dump() if body.model else None,
            goal=body.goal,
            parents=body.parents,
            triage=body.triage,
            skills=body.skills,
            goal_id=body.goal_id,
            founder=True,  # the owner's own card: he may give it to himself
        )
    )
    if body.member == founder.FOUNDER:
        await asyncio.to_thread(founder.tell, core, ws)
    return CreatedCard(id=card_id)


@router.put("/workspaces/{workspace_id}/kanban/{card_id}/goal", status_code=204)
async def set_card_goal(
    core: CoreDep, workspace_id: str, card_id: str, body: KanbanCardGoal
) -> None:
    """The sub-goal the card serves: its Hermes body's '## Goal' section (Hermes's
    `kanban edit --body`)."""
    from agos_core.actions import goals

    ws = _ws(core, workspace_id)
    _check(card_id)
    await asyncio.to_thread(goals.set_card_goal, core, ws, card_id, body.goal_id)


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/comment")
async def comment(
    core: CoreDep, workspace_id: str, card_id: str, body: KanbanCommentBody
) -> ThreadResult:
    """His comment (Hermes's own), and whom it woke: the assignee (the reviewer in
    Review) only, plus the members it @mentions (actions/threads.py)."""
    from agos_core.actions import threads

    ws = _ws(core, workspace_id)
    _check(card_id)
    return ThreadResult.model_validate(
        await asyncio.to_thread(
            lambda: threads.comment(core, ws, card_id, body.text, resume=body.resume)
        )
    )


class WatcherBody(Body):
    member: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/watchers")
async def add_watcher(
    core: CoreDep, workspace_id: str, card_id: str, body: WatcherBody
) -> list[Watcher]:
    """A member (or `cofounder`) follows the card: Hermes's notify subscription."""
    from agos_core.actions import threads

    ws = _ws(core, workspace_id)
    _check(card_id)
    found = await asyncio.to_thread(threads.watch, core, ws, card_id, body.member)
    return [Watcher.model_validate(w) for w in found]


@router.delete("/workspaces/{workspace_id}/kanban/{card_id}/watchers/{member}")
async def remove_watcher(
    core: CoreDep, workspace_id: str, card_id: str, member: str
) -> list[Watcher]:
    from agos_core.actions import threads

    ws = _ws(core, workspace_id)
    _check(card_id)
    found = await asyncio.to_thread(threads.unwatch, core, ws, card_id, member)
    return [Watcher.model_validate(w) for w in found]


class CardLabels(Body):
    ids: list[int] = Field(default_factory=list, max_length=20)


@router.put("/workspaces/{workspace_id}/kanban/{card_id}/labels", status_code=204)
async def set_card_labels(core: CoreDep, workspace_id: str, card_id: str, body: CardLabels) -> None:
    """Exactly these labels on the card: its Hermes body's labels block."""
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    _check(card_id)
    await asyncio.to_thread(labels.set_card, core, ws, card_id, body.ids)


class BulkBody(Body):
    cards: list[str] = Field(min_length=1, max_length=200)
    action: Literal["assign", "label", "unblock", "done", "block", "archive"]
    member: str = Field(default="", max_length=64)
    add: list[int] = Field(default_factory=list, max_length=20)
    remove: list[int] = Field(default_factory=list, max_length=20)
    summary: str = Field(default="", max_length=20_000)


class BulkResult(Record):
    done: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)


@router.post("/workspaces/{workspace_id}/kanban-bulk")
async def bulk(core: CoreDep, workspace_id: str, body: BulkBody) -> BulkResult:
    """One action on the selected cards, batched into Hermes (actions/board_views.py)."""
    from agos_core.actions import board_views

    ws = _ws(core, workspace_id)
    for card_id in body.cards:
        _check(card_id)
    return BulkResult.model_validate(
        await asyncio.to_thread(
            lambda: board_views.bulk(
                core,
                ws,
                body.cards,
                body.action,
                member=body.member,
                add=body.add,
                remove=body.remove,
                summary=body.summary,
            )
        )
    )


class LabelBody(Body):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="gray", max_length=20)
    folder: str = Field(default="", max_length=40)


class LabelPatch(Body):
    name: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=20)
    folder: str | None = Field(default=None, max_length=40)


class FolderRename(Body):
    old: str = Field(min_length=1, max_length=40)
    new: str = Field(default="", max_length=40)


@router.get("/workspaces/{workspace_id}/labels")
def get_labels(core: CoreDep, workspace_id: str) -> list[Label]:
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    return [Label.model_validate(lb) for lb in labels.listing(core, ws)]


@router.post("/workspaces/{workspace_id}/labels", status_code=201)
async def create_label(core: CoreDep, workspace_id: str, body: LabelBody) -> Label:
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    return Label.model_validate(labels.create(core, ws, body.name, body.color, body.folder))


@router.put("/workspaces/{workspace_id}/labels/{label_id}")
async def update_label(core: CoreDep, workspace_id: str, label_id: int, body: LabelPatch) -> Label:
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    return Label.model_validate(
        labels.update(core, ws, label_id, name=body.name, color=body.color, folder=body.folder)
    )


@router.delete("/workspaces/{workspace_id}/labels/{label_id}", status_code=204)
async def delete_label(core: CoreDep, workspace_id: str, label_id: int) -> None:
    """The label goes, and off every card carrying it (their Hermes bodies)."""
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    await asyncio.to_thread(labels.remove, core, ws, label_id)


@router.post("/workspaces/{workspace_id}/label-folders/rename")
async def rename_label_folder(core: CoreDep, workspace_id: str, body: FolderRename) -> list[Label]:
    from agos_core.actions import labels

    ws = _ws(core, workspace_id)
    return [Label.model_validate(lb) for lb in labels.rename_folder(core, ws, body.old, body.new)]


class BoardViewBody(Body):
    name: str = Field(min_length=1, max_length=60)
    filters: BoardFilters = Field(default_factory=BoardFilters)
    group_by: BoardGroup = "status"
    sort: BoardSort = "created-desc"
    layout: Literal["board", "list"] = "board"
    columns: list[BoardColumn] = Field(default_factory=list, max_length=9)


def _view(core: Any, ws: str, body: BoardViewBody, view_id: int = 0) -> BoardView:
    from agos_core.actions import board_views

    data = body.model_dump(by_alias=True)
    return BoardView.model_validate(board_views.save(core, ws, {**data, "id": view_id}))


@router.get("/workspaces/{workspace_id}/board-views")
def get_board_views(core: CoreDep, workspace_id: str) -> list[BoardView]:
    from agos_core.actions import board_views

    ws = _ws(core, workspace_id)
    return [BoardView.model_validate(v) for v in board_views.listing(core, ws)]


@router.post("/workspaces/{workspace_id}/board-views", status_code=201)
async def create_board_view(core: CoreDep, workspace_id: str, body: BoardViewBody) -> BoardView:
    return _view(core, _ws(core, workspace_id), body)


@router.put("/workspaces/{workspace_id}/board-views/{view_id}")
async def update_board_view(
    core: CoreDep, workspace_id: str, view_id: int, body: BoardViewBody
) -> BoardView:
    return _view(core, _ws(core, workspace_id), body, view_id)


@router.delete("/workspaces/{workspace_id}/board-views/{view_id}", status_code=204)
async def delete_board_view(core: CoreDep, workspace_id: str, view_id: int) -> None:
    from agos_core.actions import board_views

    board_views.remove(core, _ws(core, workspace_id), view_id)


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/answer", status_code=204)
async def answer(core: CoreDep, workspace_id: str, card_id: str, body: KanbanText) -> None:
    """His answer to a card waiting for him: a comment, and the card goes on."""
    ws = _ws(core, workspace_id)
    _check(card_id)
    await asyncio.to_thread(kanban_board.answer, core, ws, card_id, body.text)


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/chat")
async def card_chat(core: CoreDep, workspace_id: str, card_id: str) -> Created:
    """The card's own chat with its member (made once)."""
    ws = _ws(core, workspace_id)
    _check(card_id)
    return Created(id=await asyncio.to_thread(kanban_board.chat_of, core, ws, card_id))


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/assign", status_code=204)
async def assign(core: CoreDep, workspace_id: str, card_id: str, body: KanbanAssign) -> None:
    ws = _ws(core, workspace_id)
    _check(card_id)
    # The owner's own move: he may give a card to himself (the Founder, actions/founder.py).
    await asyncio.to_thread(
        lambda: kanban_board.assign(core, ws, card_id, body.member, founder=True)
    )


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/act", status_code=204)
async def act(core: CoreDep, workspace_id: str, card_id: str, body: KanbanAct) -> None:
    ws = _ws(core, workspace_id)
    _check(card_id)
    await asyncio.to_thread(kanban_board.act, core, ws, card_id, body.action, body.summary)


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/hold")
async def hold_subtree(
    core: CoreDep, workspace_id: str, card_id: str, body: KanbanHoldAction
) -> KanbanHold:
    """Pause (Hermes `kanban schedule` on every todo / ready card of the subtree) or
    Cancel (`kanban archive` on every open card of it), recorded as one hold."""
    ws = _ws(core, workspace_id)
    _check(card_id)
    run = holds.pause if body.action == "pause" else holds.cancel
    return KanbanHold.model_validate(await asyncio.to_thread(run, core, ws, card_id))


@router.post("/workspaces/{workspace_id}/kanban/holds/{hold_id}/resume")
async def resume_hold(core: CoreDep, workspace_id: str, hold_id: int) -> KanbanHold:
    """Resume: releases exactly the cards that pause parked and are still parked."""
    ws = _ws(core, workspace_id)
    return KanbanHold.model_validate(await asyncio.to_thread(holds.resume, core, ws, hold_id))


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/estimate")
async def estimate(core: CoreDep, workspace_id: str, card_id: str) -> KanbanEstimate:
    """Hermes's own effort estimate for the card (one model call)."""
    ws = _ws(core, workspace_id)
    _check(card_id)
    return KanbanEstimate.model_validate(
        await asyncio.to_thread(kanban_board.estimate, core, ws, card_id)
    )


class ReviewDecision(Body):
    """The owner on a card's review: approve / changes (with a note) a stage or a plan
    waiting in Hermes's review column; approve, changes (send back), reassign (to
    `member`) or drop a card stuck in review."""

    action: Literal["approve", "changes", "reassign", "drop"]
    note: str = Field(default="", max_length=4000)
    member: str = Field(default="", max_length=64)


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/review")
async def review_decision(
    core: CoreDep, workspace_id: str, card_id: str, body: ReviewDecision
) -> ReviewFlow:
    from agos_core.actions import reviews

    ws = _ws(core, workspace_id)
    _check(card_id)
    return ReviewFlow.model_validate(
        await asyncio.to_thread(
            reviews.owner_act, core, ws, card_id, body.action, body.note, body.member
        )
    )


class ReviewRules(Body):
    """A card's own review rules (its body's agos-review block). Leave a field out
    for the workspace's default; `reset` = the defaults for everything."""

    stages: list[str] | None = Field(default=None, max_length=6)
    cap: int | None = Field(default=None, ge=1, le=20)
    plan: bool | None = None
    plan_reviewer: str | None = Field(default=None, max_length=64)
    reset: bool = False


@router.put("/workspaces/{workspace_id}/kanban/{card_id}/review")
async def set_review_rules(
    core: CoreDep, workspace_id: str, card_id: str, body: ReviewRules
) -> ReviewFlow | None:
    from agos_core.actions import reviews

    ws = _ws(core, workspace_id)
    _check(card_id)
    data: dict[str, Any] = {}
    if not body.reset:
        if body.stages is not None:
            data["stages"] = body.stages
        if body.cap is not None:
            data["cap"] = body.cap
        if body.plan is not None:
            data["plan"] = body.plan
        if body.plan_reviewer:
            data["planReviewer"] = body.plan_reviewer
    found = await asyncio.to_thread(reviews.set_card, core, ws, card_id, data)
    return ReviewFlow.model_validate(found) if found is not None else None


class ReviewSettings(Record):
    """The workspace's review defaults: the stages every card goes through (none =
    no review), the round cap, and whether cards with children need a plan first."""

    stages: list[str] = Field(default_factory=list, max_length=6)
    cap: int = Field(default=3, ge=1, le=20)
    plan_first: bool = False
    plan_reviewer: str = Field(default="owner", max_length=64)
    # Who a stage may name (the team, by member name).
    members: list[KanbanMember] = Field(default_factory=list)


def _review_settings(core: Any, ws: str, saved: dict[str, Any]) -> ReviewSettings:
    from agos_core.actions import reviews

    people = reviews.org(core, ws)
    return ReviewSettings.model_validate(
        {
            **saved,
            "members": [
                {"name": name, "title": people.titles.get(p, name)}
                for p, name in people.names.items()
            ],
        }
    )


class ReviewSettingsBody(Body):
    stages: list[str] = Field(default_factory=list, max_length=6)
    cap: int = Field(default=3, ge=1, le=20)
    plan_first: bool = False
    plan_reviewer: str = Field(default="owner", max_length=64)


@router.get("/workspaces/{workspace_id}/review-settings")
async def get_review_settings(core: CoreDep, workspace_id: str) -> ReviewSettings:
    from agos_core.actions import reviews

    ws = _ws(core, workspace_id)
    return await asyncio.to_thread(lambda: _review_settings(core, ws, reviews.defaults(core, ws)))


@router.put("/workspaces/{workspace_id}/review-settings")
async def put_review_settings(
    core: CoreDep, workspace_id: str, body: ReviewSettingsBody
) -> ReviewSettings:
    from agos_core.actions import reviews

    ws = _ws(core, workspace_id)
    saved = await asyncio.to_thread(
        reviews.save_defaults,
        core,
        ws,
        {
            "stages": body.stages,
            "cap": body.cap,
            "planFirst": body.plan_first,
            "planReviewer": body.plan_reviewer,
        },
    )
    return await asyncio.to_thread(_review_settings, core, ws, saved)


class KanbanFile(Body):
    name: str = Field(min_length=1, max_length=200)
    data: str = Field(min_length=1, max_length=70_000_000)  # base64


@router.post("/workspaces/{workspace_id}/kanban/{card_id}/attachments", status_code=204)
async def attach(core: CoreDep, workspace_id: str, card_id: str, body: KanbanFile) -> None:
    import base64
    import binascii

    from agos_core.actions.errors import ActionError

    ws = _ws(core, workspace_id)
    _check(card_id)
    try:
        data = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ActionError("That file couldn't be read.") from error
    await asyncio.to_thread(kanban_board.attach, core, ws, card_id, body.name, data)


@router.get("/workspaces/{workspace_id}/kanban/{card_id}/attachments/{attachment_id}")
async def download(
    core: CoreDep, workspace_id: str, card_id: str, attachment_id: int
) -> FileResponse:
    ws = _ws(core, workspace_id)
    _check(card_id)
    path = await asyncio.to_thread(kanban_board.attachment_path, core, ws, card_id, attachment_id)
    return FileResponse(path, filename=path.name)


@router.delete(
    "/workspaces/{workspace_id}/kanban/{card_id}/attachments/{attachment_id}", status_code=204
)
async def remove_attachment(
    core: CoreDep, workspace_id: str, card_id: str, attachment_id: int
) -> None:
    ws = _ws(core, workspace_id)
    _check(card_id)
    await asyncio.to_thread(kanban_board.remove_attachment, core, ws, card_id, attachment_id)


def _check(card_id: str) -> None:
    import re

    from agos_core.actions.errors import NotFoundError

    if not re.fullmatch(CARD_ID, card_id):
        raise NotFoundError("This card")
