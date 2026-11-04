"""The workspace's Inbox: everything waiting for the owner, decided from AGOS.

One derived list (actions/inbox.py): the agents' proposals (actions/proposals.py:
Approve / Revise / Reject, Undo), their typed questions (actions/questions.py: the
answer for each kind), the cards' Autonomy asks (Allow once / Deny, answered on the
chats router), the cards blocked for him with no row, the cards whose blocker chain
stalled (both derived from Hermes's board) and the command approvals Hermes asks in
a chat right now. Read / dismiss marks persist (with undo); one cheap count for the
sidebar's badge.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import inbox, proposals, questions
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.founder import FounderTask
from agos_core.api.kanban_schemas import KanbanCardAsk, KanbanMember, ReviewNote
from agos_core.api.schemas import Body
from agos_core.api.workers import Readiness
from agos_core.db.records import Record

router = APIRouter(tags=["inbox"])


class ServedGoal(Record):
    """The goal or project a hire serves (its goal_id), read as it is now."""

    id: int
    title: str | None = None  # None: it is gone
    level: str = ""
    status: str = ""


class ModelChoice(Record):
    id: str
    label: str
    family: str  # haiku | sonnet | opus ("" for a model with no family)
    efforts: list[str]
    default_effort: str


class WorkspaceModel(Record):
    model: str
    effort: str


class ModelChoices(Record):
    """What the owner may pick for a hire's member (Hermes's model catalog, the
    workspace's provider only)."""

    provider: str
    label: str
    models: list[ModelChoice]
    workspace: WorkspaceModel | None = None


class ProposalView(Record):
    id: int
    card: str
    kind: Literal["hire", "instructions", "plan", "goal", "skill", "kit"]
    member: str
    member_name: str
    label: str
    payload: dict[str, Any]
    problems: list[str]
    round: int
    status: str
    note: str | None = None
    created_at: str
    decided_at: str | None = None
    can_undo: bool = False
    # The proposal as the owner approved it after editing (None: as proposed).
    edited_payload: dict[str, Any] | None = None
    # A hire: the goal or project it serves (None: none named).
    serves: ServedGoal | None = None
    # A waiting hire: the models the owner may pick (None: not known now).
    model_choices: ModelChoices | None = None


class QuestionView(Record):
    id: int
    card: str
    kind: Literal["ask", "confirm", "checkbox", "choice", "verdicts", "suggest_tasks"]
    member: str
    member_name: str
    label: str
    payload: dict[str, Any]
    continuation: Literal["wake_assignee", "none"] = "wake_assignee"
    asked_from: str = ""
    status: str
    answer: dict[str, Any] | None = None
    created_at: str
    decided_at: str | None = None


class InboxAsk(KanbanCardAsk):
    card: str
    member: str
    created_at: str


class BlockedView(Record):
    """A card Hermes holds blocked, as its chain stands (actions/blocked.py)."""

    reason: str
    state: Literal["covered", "needs_attention"]
    stalled: bool = False
    why: str
    owner: str
    action: str
    block_kind: str = ""
    blockers: list[str] = Field(default_factory=list)


class ApprovalView(Record):
    """Hermes's Allow / Deny card waiting in one of this workspace's chats."""

    key: str
    chat_id: int
    title: str
    detail: str = ""
    member_name: str = ""
    created_at: str = ""


class StalledLead(Record):
    lead: str
    why: Literal["paused", "missing", "stuck", "loop"]
    words: str
    members: list[str]


class ChainView(Record):
    """Every team a lead above it keeps from moving (actions/org.py), one item."""

    lines: list[str]
    leads: list[StalledLead]


class NoteView(Record):
    """A note AGOS left about the team (a lead removed, its reports moved)."""

    kind: str
    detail: str = ""


class ReviewWait(Record):
    """A card's review decision waiting for him (actions/reviews.py inbox): a stage
    or a plan at him, or a card stuck in review after the round cap."""

    kind: Literal["stage", "plan", "stuck"]
    stage: int = 0
    stages: int = 0
    label: str = ""
    round: int = 1
    rounds: int = 0
    cap: int = 3
    plan_revision: int = 0
    notes: list[ReviewNote] = Field(default_factory=list)
    owner_can: list[Literal["approve", "changes", "reassign", "drop"]] = Field(default_factory=list)
    members: list[KanbanMember] = Field(default_factory=list)


class MentionView(Record):
    """A comment that waits for him (actions/threads.py inbox_items): it @mentions
    him, or it is on a card at his own Review stage."""

    comment_id: int
    body: str
    reason: Literal["mention", "review"]


class HeldChange(Record):
    action: str  # add / remove / patch / replace
    target: str  # memory / user
    before: str
    after: str
    gone: bool


class HeldView(Record):
    """A memory or skill change an agent wants and Hermes holds for him
    (actions/held_writes.py groups): the same request asked again folded in."""

    group: str
    profile: str
    agent: str
    subsystem: str
    target: str
    origin: str
    id: str  # the newest copy: the one Approve applies
    ids: list[str]  # every copy, oldest first
    first_at: str
    last_at: str
    ops: list[HeldChange]
    detail: str = ""  # a skill's diff
    stale: bool = False  # a note it removes / changes is gone already (part is done)
    left: int = 0  # its changes that still apply (Approve saves only these when stale)
    title: str


class InboxItem(Record):
    key: str
    type: Literal[
        "proposal",
        "question",
        "ask",
        "review",
        "blocked",
        "attention",
        "approval",
        "chain",
        "note",
        "mention",
        "held",
        "readiness",
        "founder",
    ]
    card: str = ""
    title: str
    member_name: str = ""
    created_at: str = ""
    read: bool = False
    dismissed: bool = False
    proposal: ProposalView | None = None
    question: QuestionView | None = None
    ask: InboxAsk | None = None
    blocked: BlockedView | None = None
    approval: ApprovalView | None = None
    chain: ChainView | None = None
    note: NoteView | None = None
    review: ReviewWait | None = None
    mention: MentionView | None = None
    held: HeldView | None = None
    readiness: Readiness | None = None
    # One of his own tasks (the Founder's card on Hermes's board), with its Done.
    founder: FounderTask | None = None


class Inbox(Record):
    items: list[InboxItem]
    count: int
    unread: int
    # The sidebar badge's number (inbox.count: one query), so the page's live
    # refresh compares the same stamp as /inbox/count.
    badge: int


class InboxCount(Record):
    count: int


class Decision(Body):
    choice: Literal["approve", "revise", "reject"]
    note: str = Field(default="", max_length=4000)
    # The owner's edits of a plan proposal (a key result's numbers, a project's or a
    # goal's fields, a daily plan's items), applied with the approve.
    payload: dict[str, Any] | None = None


class Answer(Body):
    """The owner's answer, shaped by the question's kind (engine/questions.py
    check_answer): text / yes / selected / verdicts / accepted, and a note."""

    answer: dict[str, Any] = Field(default_factory=dict)


class Mark(Body):
    key: str = Field(min_length=1, max_length=160)
    mark: Literal["read", "dismissed"]


def _inbox(core: Any, workspace_id: str, with_dismissed: bool) -> Inbox:
    require_workspace(core, workspace_id)
    found = [InboxItem(**i) for i in inbox.items(core, workspace_id, with_dismissed=with_dismissed)]
    shown = [i for i in found if not i.dismissed]
    return Inbox(
        items=found,
        count=len(shown),
        unread=sum(1 for i in shown if not i.read),
        badge=inbox.count(core, workspace_id),
    )


@router.get("/workspaces/{workspace_id}/inbox")
async def get_inbox(core: CoreDep, workspace_id: str, dismissed: bool = False) -> Inbox:
    """Everything waiting for him, newest first; `dismissed` adds what he dismissed."""
    return await asyncio.to_thread(_inbox, core, workspace_id, dismissed)


@router.get("/workspaces/{workspace_id}/inbox/count")
def inbox_count(core: CoreDep, workspace_id: str) -> InboxCount:
    """The sidebar's badge: AGOS's own waiting rows he hasn't read or dismissed (one
    query), nothing from Hermes."""
    require_workspace(core, workspace_id)
    return InboxCount(count=inbox.count(core, workspace_id))


@router.post("/workspaces/{workspace_id}/inbox/marks", status_code=204)
def mark_item(core: CoreDep, workspace_id: str, body: Mark) -> None:
    """Read (seen) or dismissed (hidden until the item changes)."""
    require_workspace(core, workspace_id)
    inbox.mark(core, workspace_id, body.key, body.mark)


@router.delete("/workspaces/{workspace_id}/inbox/marks", status_code=204)
def unmark_item(
    core: CoreDep, workspace_id: str, key: str, mark: Literal["read", "dismissed"]
) -> None:
    """Undo of a read or a dismiss."""
    require_workspace(core, workspace_id)
    inbox.unmark(core, workspace_id, key, mark)


@router.get("/workspaces/{workspace_id}/proposals")
def list_proposals(core: CoreDep, workspace_id: str) -> list[ProposalView]:
    require_workspace(core, workspace_id)
    return [ProposalView(**p) for p in proposals.waiting(core, workspace_id)]


@router.post("/workspaces/{workspace_id}/proposals/{ask_id}")
async def decide_proposal(
    core: CoreDep, workspace_id: str, ask_id: int, body: Decision
) -> ProposalView:
    """Approve (optionally with the owner's edits of a plan proposal) / Revise (with a
    note) / Reject. The same decision again is a no-op; another one after a decision
    is a 409."""
    require_workspace(core, workspace_id)
    shown = await asyncio.to_thread(
        proposals.decide, core, workspace_id, ask_id, body.choice, body.note, body.payload
    )
    return ProposalView(**shown)


@router.post("/workspaces/{workspace_id}/proposals/{ask_id}/undo")
async def undo_proposal(core: CoreDep, workspace_id: str, ask_id: int) -> ProposalView:
    """Undo of an approved hire: the member goes."""
    require_workspace(core, workspace_id)
    shown = await asyncio.to_thread(proposals.undo, core, workspace_id, ask_id)
    return ProposalView(**shown)


@router.get("/workspaces/{workspace_id}/questions")
def list_questions(core: CoreDep, workspace_id: str) -> list[QuestionView]:
    require_workspace(core, workspace_id)
    return [QuestionView(**q) for q in questions.waiting(core, workspace_id)]


@router.post("/workspaces/{workspace_id}/questions/{ask_id}")
async def answer_question(
    core: CoreDep, workspace_id: str, ask_id: int, body: Answer
) -> QuestionView:
    """The owner's answer: written on the card (Hermes), then the card goes on as
    its continuation says. The same answer again is a no-op; another is a 409."""
    require_workspace(core, workspace_id)
    shown = await asyncio.to_thread(questions.answer, core, workspace_id, ask_id, body.answer)
    return QuestionView(**shown)
