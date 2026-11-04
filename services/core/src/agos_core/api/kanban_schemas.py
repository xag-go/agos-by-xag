"""The Kanban page's shapes: what the board, a card and its review flow look like to
the web, and the bodies the page sends.

Owns: those request/response models (their names are the OpenAPI schema names the
web's types are generated from). Must not: hold a route or call a service
(api/kanban.py does).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from agos_core.api.card_docs import CardDocument
from agos_core.api.schemas import Body
from agos_core.db.records import Record
from agos_core.domain.models import ModelSelection

__all__ = [
    "BoardColumn",
    "BoardFilters",
    "BoardGroup",
    "BoardSort",
    "BoardView",
    "CardRef",
    "CreatedCard",
    "GoalRef",
    "HeldCard",
    "KanbanAct",
    "KanbanAssign",
    "KanbanAttachment",
    "KanbanBoard",
    "KanbanCard",
    "KanbanCardAsk",
    "KanbanCardDetail",
    "KanbanCardGoal",
    "KanbanColumn",
    "KanbanComment",
    "KanbanCommentBody",
    "KanbanEstimate",
    "KanbanEvent",
    "KanbanHold",
    "KanbanHoldAction",
    "KanbanMember",
    "KanbanStep",
    "KanbanText",
    "Label",
    "NewKanbanCard",
    "ReviewChip",
    "ReviewFlow",
    "ReviewNote",
    "ReviewStage",
    "SkillPin",
    "ThreadResult",
    "Watcher",
    "Woken",
]


class KanbanMember(Record):
    name: str
    title: str


class SkillPin(Record):
    skill: str
    version: int


class ReviewChip(Record):
    """The board card's review chip ('Review 2/3 · round 1', 'Plan waiting')."""

    stage: int = 0  # the stage it waits for (0 = not in review)
    stages: int = 0
    round: int = 1
    phase: Literal["", "work", "review", "stuck", "done"] = ""
    plan: Literal["none", "needed", "waiting", "changes", "accepted"] = "none"


class ReviewStage(Record):
    stage: str  # lead | cofounder | owner | a member's name
    reviewer: str  # who it is for this card (a member's name, cofounder, owner, "")
    label: str
    state: Literal["waiting", "current", "approved", "changes", "skipped", "stuck"]


class ReviewNote(Record):
    kind: Literal["review", "plan"]
    verb: str
    stage: int = 0
    revision: int = 0
    round: int = 0
    author: str = ""
    text: str = ""
    at: int = 0


class ReviewFlow(Record):
    """A card's review stages, rounds, notes and plan (actions/reviews.py view)."""

    stages: list[ReviewStage] = Field(default_factory=list)
    phase: str = ""
    current: int = 0
    round: int = 1
    rounds: int = 0
    cap: int = 3
    own: bool = False  # the card sets its own rules (else the workspace's defaults)
    notes: list[ReviewNote] = Field(default_factory=list)
    plan: Literal["none", "needed", "waiting", "changes", "accepted"] = "none"
    plan_revision: int = 0
    plan_reviewer: str = ""
    plan_reviewer_label: str = ""
    owner_can: list[Literal["approve", "changes", "reassign", "drop"]] = Field(default_factory=list)
    at_owner: bool = False


class KanbanCard(Record):
    id: str
    title: str
    body: str
    status: str
    member: str
    member_title: str
    created_at: int
    created_by: str = ""
    model: str = ""
    goal: bool = False
    block_kind: str = ""
    started_at: int | None = None
    completed_at: int | None = None
    # Hermes's label for the status, and what the owner may do with the card now
    # (actions/services/board/kanban_workflow.py card_actions): the web repeats neither.
    status_label: str = ""
    actions: list[Literal["unblock", "archive", "done", "block"]] = Field(default_factory=list)
    # A waiting card's derived state (actions/blocked.py attention): covered (what
    # it waits on moves by itself) or needs_attention (the owner must act; `stalled`
    # when its blocker chain stopped), with why; "" for a card that isn't waiting.
    attention: str = ""
    attention_why: str = ""
    # An unresumed Pause holds this card's subtree (the Board's Resume button).
    hold_id: int | None = None
    # A watchdog watches this card's tree (the modal's "Watch this tree").
    watchdog_id: int | None = None
    # The workspace skills (and their versions) the card was made with: Hermes loads
    # them for the worker; the versions pin what it read (actions/skill_versions.py).
    skill_pins: list[SkillPin] = Field(default_factory=list)
    # The goal it serves (engine/goals.py): its body's '## Goal' line, or its nearest
    # parent's (`goal_inherited`); None = none.
    goal_id: int | None = None
    goal_inherited: bool = False
    # Its member's team is stalled by a lead above it (actions/org.py): the words.
    chain_stalled: str = ""
    # Its review stages / plan first (actions/reviews.py): None = no review rules.
    review_chip: ReviewChip | None = None
    # Its labels (ids of the workspace's labels; a block in its Hermes body).
    labels: list[int] = Field(default_factory=list)
    # Hermes's priority (a sort of the Board's views).
    priority: int = 0


class Label(Record):
    """One of the workspace's labels (actions/labels.py); `folder` groups them."""

    id: int
    name: str
    color: str
    folder: str = ""


class BoardFilters(Record):
    """A Board view's filters: each one left empty = everything (all in the browser,
    over the board's one read)."""

    members: list[str] = Field(default_factory=list, max_length=50)
    statuses: list[str] = Field(default_factory=list, max_length=20)
    labels: list[int] = Field(default_factory=list, max_length=50)
    goal: int | None = None
    review: Literal["", "any", "waiting", "at_owner", "stuck", "none"] = ""
    blocked: Literal["", "yes", "no", "asks"] = ""
    text: str = Field(default="", max_length=200)


BoardGroup = Literal["status", "member", "label", "goal", "project"]
BoardSort = Literal["created-desc", "created-asc", "title", "priority", "status"]
BoardColumn = Literal[
    "id", "title", "status", "member", "labels", "goal", "review", "created", "priority"
]


class BoardView(Record):
    """A saved Board view (actions/board_views.py): the owner's preferences row."""

    id: int
    name: str
    filters: BoardFilters = Field(default_factory=BoardFilters)
    group_by: BoardGroup = "status"
    sort: BoardSort = "created-desc"
    layout: Literal["board", "list"] = "board"
    columns: list[BoardColumn] = Field(default_factory=list)


class GoalRef(Record):
    """A goal as a card's chip and the modal's picker show it."""

    id: int
    parent_id: int | None = None
    level: str = "goal"
    title: str
    status: str
    owner: str = ""


class KanbanColumn(Record):
    """One of Hermes's Kanban columns (its workflow), in Hermes's order."""

    status: str
    label: str
    # A card here still has work ahead (not done, not archived): the Office's open cards.
    open: bool = True


class KanbanBoard(Record):
    columns: list[KanbanColumn] = Field(default_factory=list)
    # Seconds between Hermes's dispatcher rounds (kanban.dispatch_interval_seconds as
    # the workspace's gateway reads it); None when Hermes can't be read.
    dispatch_seconds: int | None = None
    cards: list[KanbanCard]
    members: list[KanbanMember]
    goals: list[GoalRef] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    views: list[BoardView] = Field(default_factory=list)


class KanbanComment(Record):
    id: int = 0  # Hermes's comment id
    author: str
    body: str
    at: int


class CardRef(Record):
    """A card a text names (t_…): its reference chip."""

    id: str
    title: str
    status: str
    status_label: str = ""


class Watcher(Record):
    """Who follows the card: a Hermes notify subscription, as a person."""

    name: str  # a member's name, cofounder; "" for another chat
    title: str
    kind: Literal["member", "chat"] = "member"
    mode: str = "notify"


class KanbanEvent(Record):
    kind: str
    at: int
    detail: str


class KanbanStep(Record):
    text: str
    status: str


class KanbanCardAsk(Record):
    id: int
    label: str
    detail: str
    member_name: str


class KanbanAttachment(Record):
    id: int
    name: str
    size: int
    by: str
    at: int


class KanbanEstimate(Record):
    tokens: int
    complexity: str
    why: str


class KanbanCardDetail(KanbanCard):
    attachments: list[KanbanAttachment] = Field(default_factory=list)
    # The card's documents (files under cards/<card>/ in the workspace folder,
    # actions/card_docs.py): listed with the card, their text read on open.
    documents: list[CardDocument] = Field(default_factory=list)
    summary: str
    # Mark done asks what was done first: Hermes refuses this card's completion
    # without a summary (kanban_board.done_needs_summary, its empty-completion gate).
    done_needs_summary: bool = False
    plan: list[KanbanStep] = Field(default_factory=list)
    question: str = ""
    asks: list[KanbanCardAsk] = Field(default_factory=list)
    chat_id: int | None = None
    comments: list[KanbanComment]
    events: list[KanbanEvent]
    parents: list[str]
    children: list[str]
    goals: list[GoalRef] = Field(default_factory=list)
    review: ReviewFlow | None = None
    refs: list[CardRef] = Field(default_factory=list)
    watchers: list[Watcher] = Field(default_factory=list)


class NewKanbanCard(Body):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=20_000)
    member: str = Field(default="", max_length=64)
    criteria: list[str] = Field(default_factory=list, max_length=30)
    model: ModelSelection | None = None
    goal: bool = False
    parents: list[str] = Field(default_factory=list, max_length=20)
    # A rough idea: Hermes fleshes it out and splits it among the team.
    triage: bool = False
    # Workspace skills Hermes force-loads for the worker (their versions get pinned).
    skills: list[str] = Field(default_factory=list, max_length=20)
    # The sub-goal it serves: its body starts with that goal's '## Goal' line.
    goal_id: int | None = None


class KanbanCardGoal(Body):
    """The card's sub-goal (None: none): its Hermes body's '## Goal' section."""

    goal_id: int | None = None


class KanbanText(Body):
    text: str = Field(min_length=1, max_length=20_000)


class KanbanCommentBody(Body):
    text: str = Field(min_length=1, max_length=20_000)
    # Start a stopped card again with it (Paperclip's comment `resume`).
    resume: bool = False


class Woken(Record):
    """Someone a comment reached, and how (engine/threads.py wake_plan)."""

    who: str
    title: str
    how: Literal["steer", "unblock", "dispatch", "waits", "review", "inbox", "mention"]
    why: Literal["assignee", "reviewer", "mention"]
    said: str


class ThreadResult(Record):
    woke: list[Woken] = Field(default_factory=list)


class KanbanAssign(Body):
    member: str = Field(default="", max_length=64)


class KanbanAct(Body):
    action: Literal["unblock", "archive", "done", "block"]
    # Mark done: his words on what was done (Hermes's completion summary); "" = none.
    summary: str = Field(default="", max_length=20_000)


class CreatedCard(Record):
    id: str


class KanbanHoldAction(Body):
    """Pause / Cancel the card and everything under it (actions/holds.py)."""

    action: Literal["pause", "cancel"]


class HeldCard(Record):
    card: str
    was: str


class KanbanHold(Record):
    id: int
    card: str
    action: Literal["pause", "cancel"]
    held: list[HeldCard]
    created_at: str
    released_at: str | None = None
    # Cards of the subtree the hold did not move (running, blocked, done…).
    left: list[str] = Field(default_factory=list)
    # Resume: the cards it released (still scheduled by this pause).
    released: list[str] = Field(default_factory=list)
