"""The Vision page (Step 53; Step 51's Goals page grew into it): the workspace's
Vision and strategy (the owner's words), its goals with their key results, each
goal's projects, today's column (each member's cards of today's plan and the
owner's own list) and the Co-Founder's daily rhythm, in one read. The owner edits
everything here; an agent's change is a proposal (Inbox kind 'goal')."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import goals, rhythm, today, vision_notes
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["vision"])

Status = Literal["active", "paused", "done", "dropped"]
Date = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class GoalCards(Record):
    done: int = 0
    open: int = 0
    blocked: int = 0


class KeyResultView(Record):
    id: int
    goal_id: int
    title: str
    start: float = 0
    current: float = 0
    target: float | None = None
    unit: str = ""
    due_on: str = ""
    source: str = ""
    position: int = 0
    # From its start to its target, 0..1 (None: no target yet).
    progress: float | None = None


class NextCard(Record):
    """A row's next open card (running, then review, blocked, ready / to do)."""

    id: str
    title: str
    status: str


class PlanNode(Record):
    """The Vision, a goal or a project (the goals table's levels)."""

    id: int
    parent_id: int | None = None
    level: Literal["vision", "goal", "project"]
    title: str
    why: str = ""
    owner: str = ""
    status: Status
    position: int = 0
    strategy: str = ""
    due_on: str = ""
    project_kind: str = ""
    starts_on: str = ""
    ends_on: str = ""
    rhythm: str = ""
    # Its cards and those of the rows below it (Hermes's board, one read).
    cards: GoalCards
    # Its next open card (same board read; None: no open card).
    next_card: NextCard | None = None
    # 0..1: a project's cards done; a goal's key results (else its cards); the
    # Vision's active goals. None: nothing to measure yet.
    progress: float | None = None
    results: list[KeyResultView] = Field(default_factory=list)
    children: list[PlanNode] = Field(default_factory=list)


class TodayCard(Record):
    id: str
    title: str
    # Hermes's status (todo, ready, triage, scheduled, running, review, blocked, done).
    status: str
    # The goal or project the card serves (its '## Goal' line), when it names one.
    goal_id: int | None = None


class TodayMember(Record):
    member: str
    title: str
    cards: list[TodayCard]


class TodayItem(TodayCard):
    done: bool = False
    # One of his Founder tasks (a card assigned to him on the board, actions/founder.py),
    # shown in his list while it is open; `can_finish`: Hermes can complete it now.
    founder: bool = False
    can_finish: bool = True


class TodayPlan(Record):
    ask_id: int
    card: str
    status: str
    summary: str = ""
    note: str | None = None


class Today(Record):
    date: str
    plan: TodayPlan | None = None
    members: list[TodayMember] = Field(default_factory=list)
    you: list[TodayItem] = Field(default_factory=list)


class RhythmJob(Record):
    """One of the Co-Founder's daily jobs (a Hermes cron job in its own profile)."""

    which: Literal["daily", "recap", "weekly"]
    name: str
    on: bool
    time: str
    day: int | None = None
    next_at: str | None = None
    last_at: str | None = None
    last_status: str | None = None
    problem: str | None = None


class VisionMember(Record):
    name: str
    title: str


class NotesRevision(Record):
    n: int
    at: str
    who: str
    why: str


class VisionNotes(Record):
    """The owner's free notes on the Vision page (vision/notes.md, revised)."""

    text: str
    revision: int
    updated_at: str | None = None
    revisions: list[NotesRevision] = Field(default_factory=list)


class VisionView(Record):
    vision: PlanNode | None = None
    today: Today
    rhythm: list[RhythmJob] = Field(default_factory=list)
    members: list[VisionMember] = Field(default_factory=list)
    # The owner's free notes at the top of the page (step 60).
    notes: VisionNotes | None = None


class VisionText(Body):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=2000)
    strategy: str = Field(default="", max_length=2000)


class NewGoal(Body):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=64)
    due_on: str = Date


class NewProject(Body):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=64)
    project_kind: Literal["dated", "recurring"] = "dated"
    starts_on: str = Date
    ends_on: str = Date
    rhythm: str = Field(default="", max_length=120)


class ItemChange(Body):
    """A goal's or a project's fields (only those given change)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    why: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=64)
    status: Status | None = None
    position: int | None = None
    due_on: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    project_kind: Literal["dated", "recurring"] | None = None
    starts_on: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    ends_on: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    rhythm: str | None = Field(default=None, max_length=120)
    # A project moves to another goal.
    parent_id: int | None = None


class NewResult(Body):
    title: str = Field(min_length=1, max_length=200)
    start: float = 0
    current: float | None = None
    target: float | None = None
    unit: str = Field(default="", max_length=40)
    due_on: str = Date


class ResultChange(Body):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    start: float | None = None
    current: float | None = None
    target: float | None = None
    unit: str | None = Field(default=None, max_length=40)
    due_on: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    position: int | None = None


class RhythmChange(Body):
    on: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day: int | None = Field(default=None, ge=0, le=6)


class Created(Record):
    id: int


class NotesText(Body):
    text: str = Field(max_length=vision_notes.MAX_NOTES)


class NotesRevisionText(Record):
    n: int
    content: str
    diff: str


class FoundResult(Record):
    title: str
    target: float | None = None
    unit: str = ""
    due_on: str = ""


class FoundProject(Record):
    title: str


class FoundGoal(Record):
    title: str
    why: str = ""
    key_results: list[FoundResult] = Field(default_factory=list)
    projects: list[FoundProject] = Field(default_factory=list)


class Organized(Record):
    """Organize's answer: the Vision, Why and Strategy as a preview (not saved) and
    the goals it found (proposed in the Inbox: `proposed` now, `already` before;
    `waiting` until the first Vision is saved)."""

    revision: int
    vision: str
    why: str = ""
    strategy: str = ""
    goals: list[FoundGoal] = Field(default_factory=list)
    proposed: int = 0
    already: int = 0
    waiting: int = 0
    problems: list[str] = Field(default_factory=list)


def _view(core: Any, workspace_id: str) -> VisionView:
    require_workspace(core, workspace_id)
    return VisionView.model_validate(
        {**goals.view(core, workspace_id), "notes": vision_notes.read(core, workspace_id)}
    )


def _set(body: Body) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


def _noted(core: Any, workspace_id: str, text: str) -> None:
    goals.note_owner_change(core, workspace_id, text)


@router.get("/workspaces/{workspace_id}/vision")
async def get_vision(core: CoreDep, workspace_id: str) -> VisionView:
    """The whole page in one read: the plan with its rollup, today, the rhythm."""
    return await asyncio.to_thread(_view, core, workspace_id)


@router.put("/workspaces/{workspace_id}/vision")
async def put_vision(core: CoreDep, workspace_id: str, body: VisionText) -> VisionView:
    """The Vision, its why and the strategy (the owner's); every agent's prompt follows.
    The first one sets up the Co-Founder's daily plan, recap and weekly review."""
    await asyncio.to_thread(
        lambda: goals.set_vision(
            core, workspace_id, title=body.title, why=body.why, strategy=body.strategy
        )
    )
    _noted(core, workspace_id, f"Vision set: {body.title}")
    # Goals an Organize found before there was a Vision go to the Inbox now.
    await asyncio.to_thread(vision_notes.propose_goals, core, workspace_id)
    return await asyncio.to_thread(_view, core, workspace_id)


@router.get("/workspaces/{workspace_id}/vision/notes")
async def get_notes(core: CoreDep, workspace_id: str) -> VisionNotes:
    """The owner's free notes and their revisions."""
    found = await asyncio.to_thread(vision_notes.read, core, workspace_id)
    return VisionNotes.model_validate(found)


@router.put("/workspaces/{workspace_id}/vision/notes")
async def put_notes(core: CoreDep, workspace_id: str, body: NotesText) -> VisionNotes:
    """The notes saved: a new revision when they changed."""
    await asyncio.to_thread(vision_notes.save, core, workspace_id, body.text)
    return VisionNotes.model_validate(
        await asyncio.to_thread(vision_notes.read, core, workspace_id)
    )


@router.get("/workspaces/{workspace_id}/vision/notes/revisions/{n}")
async def get_notes_revision(core: CoreDep, workspace_id: str, n: int) -> NotesRevisionText:
    found = await asyncio.to_thread(vision_notes.revision, core, workspace_id, n)
    return NotesRevisionText.model_validate(found)


@router.post("/workspaces/{workspace_id}/vision/notes/organize")
async def organize_notes(core: CoreDep, workspace_id: str) -> Organized:
    """The Co-Founder turns the saved notes into the Vision, Why and Strategy (a
    preview the owner edits and saves) and proposes the goals it found (one Hermes
    run, up to two minutes)."""
    found = await asyncio.to_thread(vision_notes.organize, core, workspace_id)
    return Organized.model_validate(found)


@router.post("/workspaces/{workspace_id}/vision/goals", status_code=201)
async def add_goal(core: CoreDep, workspace_id: str, body: NewGoal) -> Created:
    require_workspace(core, workspace_id)
    new_id = await asyncio.to_thread(
        lambda: goals.add_goal(
            core,
            workspace_id,
            title=body.title,
            why=body.why,
            owner=body.owner,
            due_on=body.due_on,
        )
    )
    _noted(core, workspace_id, f"Goal added: {body.title}")
    return Created(id=new_id)


@router.post("/workspaces/{workspace_id}/vision/goals/{goal_id}/projects", status_code=201)
async def add_project(core: CoreDep, workspace_id: str, goal_id: int, body: NewProject) -> Created:
    require_workspace(core, workspace_id)
    new_id = await asyncio.to_thread(
        lambda: goals.add_project(
            core,
            workspace_id,
            goal_id,
            title=body.title,
            why=body.why,
            owner=body.owner,
            project_kind=body.project_kind,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            rhythm=body.rhythm,
        )
    )
    _noted(core, workspace_id, f"Project added: {body.title}")
    return Created(id=new_id)


@router.put("/workspaces/{workspace_id}/vision/items/{item_id}", status_code=204)
async def change_item(core: CoreDep, workspace_id: str, item_id: int, body: ItemChange) -> None:
    """A goal or a project changes (the fields given)."""
    require_workspace(core, workspace_id)
    await asyncio.to_thread(goals.update_item, core, workspace_id, item_id, _set(body))
    _noted(core, workspace_id, f"Goal or project {item_id} changed: {', '.join(_set(body))}")


@router.delete("/workspaces/{workspace_id}/vision/items/{item_id}", status_code=204)
async def delete_item(core: CoreDep, workspace_id: str, item_id: int) -> None:
    """A goal (with its projects and key results) or a project goes."""
    require_workspace(core, workspace_id)
    await asyncio.to_thread(goals.delete_item, core, workspace_id, item_id)
    _noted(core, workspace_id, f"Goal or project {item_id} removed")


@router.post("/workspaces/{workspace_id}/vision/goals/{goal_id}/results", status_code=201)
async def add_result(core: CoreDep, workspace_id: str, goal_id: int, body: NewResult) -> Created:
    require_workspace(core, workspace_id)
    new_id = await asyncio.to_thread(
        lambda: goals.add_result(
            core,
            workspace_id,
            goal_id,
            title=body.title,
            start=body.start,
            current=body.current,
            target=body.target,
            unit=body.unit,
            due_on=body.due_on,
        )
    )
    _noted(core, workspace_id, f"Key result added: {body.title}")
    return Created(id=new_id)


@router.put("/workspaces/{workspace_id}/vision/results/{kr_id}", status_code=204)
async def change_result(core: CoreDep, workspace_id: str, kr_id: int, body: ResultChange) -> None:
    require_workspace(core, workspace_id)
    await asyncio.to_thread(goals.update_result, core, workspace_id, kr_id, _set(body))
    _noted(core, workspace_id, f"Key result {kr_id} changed: {', '.join(_set(body))}")


@router.delete("/workspaces/{workspace_id}/vision/results/{kr_id}", status_code=204)
async def delete_result(core: CoreDep, workspace_id: str, kr_id: int) -> None:
    require_workspace(core, workspace_id)
    await asyncio.to_thread(goals.delete_result, core, workspace_id, kr_id)
    _noted(core, workspace_id, f"Key result {kr_id} removed")


@router.put("/workspaces/{workspace_id}/vision/rhythm/{which}")
async def set_rhythm(
    core: CoreDep, workspace_id: str, which: str, body: RhythmChange
) -> list[RhythmJob]:
    """One of the Co-Founder's jobs (daily plan, recap, weekly review): on / off and
    its time (the owner's clock; the weekly one's day too)."""
    shown = await asyncio.to_thread(
        lambda: rhythm.set_job(core, workspace_id, which, on=body.on, time=body.time, day=body.day)
    )
    return [RhythmJob.model_validate(j) for j in shown]


@router.post("/workspaces/{workspace_id}/vision/today/{card_id}/done", status_code=204)
async def tick_today(core: CoreDep, workspace_id: str, card_id: str) -> None:
    """The owner ticked one of his own items for today: its card is done."""
    require_workspace(core, workspace_id)
    await asyncio.to_thread(today.check, core, workspace_id, card_id)
