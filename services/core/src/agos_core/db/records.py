"""Plain data returned by the repositories and by the API (camelCase JSON)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agos_core.domain.models import ModelSelection


class Record(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)


class Workspace(Record):
    id: str
    name: str
    description: str
    default_model: ModelSelection
    chat_access: Literal["ask", "full"] = "ask"
    archived: bool
    created_at: str
    # The icon file's stamp (storage/workspace_icon.stamp), None without one; the
    # web puts it after the icon's URL so a new picture is fetched again.
    icon: str | None = None


class AddedFolder(Record):
    name: str
    host_path: str
    access: Literal["read", "read-write"]


class Attachment(Record):
    """A screenshot, voice note or file the owner sent with a message."""

    id: int
    kind: Literal["image", "audio", "file"]
    name: str
    mime: str
    size: int
    duration: float | None = None
    transcript: str | None = None


class ChatMessage(Record):
    id: int
    at: str
    from_: Literal["owner", "agent"] = Field(alias="from")
    body: str
    attachments: list[Attachment] = []
    # Workers: which agent wrote it (None = the Co-Founder / the chat's agent).
    speaker: str | None = None
    # Team plans: a note between steps (handoff, review, question, answer).
    kind: Literal["chat", "handoff", "review", "question", "answer"] = "chat"
    # A reply to an earlier message of the same conversation (its id and a preview).
    reply_to: int | None = None
    reply_preview: str | None = None
    reply_from: str | None = None
    # The part of that message the owner selected and answers (None = all of it).
    reply_excerpt: str | None = None
    # When the owner last changed his message.
    edited_at: str | None = None
    # The owner's 👍 (1) / 👎 (-1) on an agent's reply (actions/feedback.py).
    vote: int = 0


class ChatActivity(Record):
    id: str
    kind: Literal["tool", "thinking", "note", "approval", "subagent"]
    title: str
    detail: str
    status: Literal["running", "done", "failed", "waiting"]
    duration: float | None = None
    choices: list[str] = []


class ChatTurn(Record):
    """One answer of the agent: what it did (activity) and the reply message."""

    id: int
    status: Literal["starting", "running", "stopping", "completed", "failed", "stopped"]
    asked_up_to: int
    reply_id: int | None
    activity: list[ChatActivity]
    model: str | None
    error: str | None
    requests: "list[CapabilityRequestView]" = []
    actions: "list[CofounderActionView]" = []
    # Who answered (a member's name; None = the Co-Founder), even with no reply.
    speaker: str | None = None


class Chat(Record):
    id: int
    workspace_id: str
    title: str
    channel: Literal["web", "telegram"]
    model: ModelSelection
    # "ask": risky commands wait for the owner; "full": allowed at once, still
    # only inside the workspace's sandbox, and Hermes's hard blocks stay on.
    access: Literal["ask", "full"] = "ask"
    # The workspace is on Full access: every chat runs commands without asking,
    # whatever its own switch says.
    workspace_full: bool = False
    agent: str | None = None
    # "chat": the classic chats; "dm"/"group": Workers (agent = DM partner).
    kind: Literal["chat", "dm", "group"] = "chat"
    members: list[str] = []
    messages: list[ChatMessage]
    turns: list[ChatTurn] = []
    updated_at: str = ""
    preview: str = ""
    working: bool = False
    pending: bool = False


class LastRun(Record):
    at: str
    result: Literal["ok", "failed"]
    summary: str


class AutomationProposal(Record):
    """A card a run made on Hermes's Kanban, waiting there for the owner."""

    id: int
    title: str
    description: str
    kanban_card: str


class AutomationRun(Record):
    id: int
    result: Literal["ok", "failed"]
    source: str
    started_at: str
    finished_at: str | None
    report: str
    error: str | None
    proposals: list[AutomationProposal] = []
    # A catch-up run (actions/catch_up.py): the occurrence it makes up for, missed
    # while the server was off. None = an ordinary run.
    caught_up: str | None = None
    # Who worked each step, how long, its tokens and cost (Hermes's counts).
    detail: "RunDetail | None" = None


class StepCondition(Record):
    """One "Only if" line of a team step (engine/step_conditions.py): a match line
    (field, op, values: the webhook's tests on the run's values) or a check line
    (check: a /workspace script whose last line says YES/AH or NO/LA)."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )

    field: str | None = Field(default=None, max_length=200)
    op: Literal["is", "is_not", "contains", "not_contains"] | None = None
    values: list[str] = Field(default_factory=list, max_length=100)
    check: str | None = Field(default=None, max_length=300)


class AutomationStep(Record):
    """One step of a team automation (the same shape as a team plan's step)."""

    key: str
    title: str
    description: str = ""
    kind: Literal["work", "review", "approval"] = "work"
    agent: str | None = None  # None = the Co-Founder (approval: the owner)
    waits_on: list[str] = Field(default_factory=list)
    reviews: str | None = None
    # Its "Only if" lines: none = it always runs.
    only_if: list[StepCondition] = Field(default_factory=list, max_length=20)


class HookCondition(Record):
    """One "Only if" line of a webhook: a delivery starts the work only when every line
    holds (Hermes's own route filters check them, before any card exists).
    `when`: only for this event (None = every event); `field`: where the value is in
    what the app sends (e.g. data.to.name)."""

    when: str | None = None
    field: str = Field(min_length=1, max_length=200)
    op: Literal["is", "is_not", "contains", "not_contains"] = "is"
    values: list[str] = Field(default_factory=list, max_length=100)


class AutomationHook(Record):
    """The automation's webhook: its address (path; the public host is in settings)."""

    path: str
    signed: bool
    events: list[str] = Field(default_factory=list)
    conditions: list[HookCondition] = Field(default_factory=list)
    # Filters set in Hermes that AGOS can't show as lines (kept as they are).
    other_filters: int = 0
    last_received_at: str | None = None
    # A signing secret AGOS just made: only in the answer of the save that made it.
    new_secret: str | None = None
    # A secret AGOS made while saving the automation: he shows it once (hook/secret).
    secret_waiting: bool = False


class AutomationEvent(Record):
    """One webhook delivery and what AGOS did with it."""

    id: int
    event: str
    status: Literal["pending", "started", "duplicate", "filtered", "rejected", "off"]
    detail: str
    plan_id: int | None
    received_at: str
    preview: str


class AutomationVariable(Record):
    """One typed variable of an automation, written as {name} in its step titles,
    bodies and (a one-agent automation) its instructions. `default` is the value a
    scheduled or webhook run uses; Run now may give another."""

    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    type: Literal["text", "number", "boolean", "select", "date"] = "text"
    default: str = Field(default="", max_length=2000)
    # select: what the owner may pick (the default is one of them).
    options: list[str] = Field(default_factory=list, max_length=50)
    label: str = Field(default="", max_length=120)


Policy = Literal["skip_if_active", "coalesce_if_active", "always_enqueue"]
CatchUp = Literal["once", "skip"]


class TicketMapping(Record):
    """A ticket on-ramp (Linear / Jira / Asana / GitHub issues): one Kanban card per
    incoming issue, keyed agos-ticket:<source>:<id>, given to `member` (None = the
    Co-Founder); the issue's close upstream completes the card."""

    source: Literal["linear", "jira", "asana", "github"]
    member: str | None = None


class RevisionChange(Record):
    field: str
    before: str
    after: str


class AutomationRevision(Record):
    """One saved version of an automation (newest first in the Revisions tab)."""

    n: int
    at: str
    who: str
    summary: str
    restored_from: int | None = None
    # The automation as it was saved (what Restore brings back).
    snapshot: dict[str, Any] = Field(default_factory=dict)
    # What changed against the revision before: field, before, after (as text).
    changes: list[RevisionChange] = Field(default_factory=list)


class AgentRevisionChange(Record):
    field: str
    before: str
    after: str
    # A long text (role, the owner's notes): its unified diff, line by line.
    lines: str = ""


class AgentRevision(Record):
    """One version of a team member (newest first in its Revisions tab)."""

    n: int
    at: str
    who: str
    why: str = ""
    summary: str
    restored_from: int | None = None
    # The member as it was (what Restore brings back).
    snapshot: dict[str, Any] = Field(default_factory=dict)
    changes: list[AgentRevisionChange] = Field(default_factory=list)


class RunCard(Record):
    """One card of an automation run, as the run history shows it."""

    id: str
    step: str
    title: str
    status: str
    assignee: str = ""


RunStatus = Literal["completed", "needs_you", "running", "waiting", "stopped"]


class AutomationRunGroup(Record):
    """One run of an automation = its cards, grouped by the run id in their
    idempotency keys; its status derived from the cards (no table of runs)."""

    automation_id: int
    automation_name: str
    run_id: str
    source: str
    started_at: str
    finished_at: str | None
    status: RunStatus
    cards: list[RunCard] = Field(default_factory=list)
    detail: "RunDetail | None" = None  # its steps in run order, with tokens and cost


class Automation(Record):
    id: int
    workspace_id: str
    name: str
    file: str
    instructions: str
    schedule: str
    model: ModelSelection
    on: bool
    last_run: LastRun | None
    # From Hermes's scheduler: when it fires next, and why it can't (if so).
    next_run_at: str | None = None
    problem: str | None = None
    # Hermes's own words for the schedule (its job's schedule_display) and the
    # job's state (scheduled / paused / completed / error).
    schedule_display: str | None = None
    state: str | None = None
    # Who does it: one agent of the team (None = the Co-Founder), or a team plan.
    agent: str | None = None
    steps: list[AutomationStep] = Field(default_factory=list)
    # Something the owner should know (e.g. an agent is gone: the Co-Founder does it).
    notice: str | None = None
    # An event: starts the moment something happens outside (None = a scheduled automation).
    hook: AutomationHook | None = None
    # The owner approves before the work goes on (otherwise it runs by itself).
    check_first: bool = False
    # Step 48: typed variables ({name} in the cards and the prompt), what a trigger
    # does while the last run's cards are still open, and a ticket on-ramp mapping.
    variables: list[AutomationVariable] = Field(default_factory=list)
    policy: Policy = "skip_if_active"
    ticket: TicketMapping | None = None
    # A run missed while the server was off (actions/catch_up.py): run it once when
    # AGOS is back, or skip it. `caught_up`: the missed occurrence its latest
    # catch-up run (the last day) made up for.
    catch_up: CatchUp = "once"
    caught_up: str | None = None


class ActivityItem(Record):
    """One event of the workspace's board: Hermes's Kanban task_events."""

    id: int
    at: str
    text: str
    task_id: str = Field(description="The Hermes card it happened to.")


class BoardCounters(Record):
    """The workspace's Kanban at a glance (its dashboard)."""

    working: int
    waiting_for_you: int
    suggestions: int
    done: int
    # The Inbox (proposals and asks waiting for him): AGOS's own rows, one query.
    inbox: int = 0


class CapabilityRequestView(Record):
    """The Co-Founder asked to turn a capability on/off; the owner decides on a card."""

    id: int
    kind: str
    name: str
    title: str
    turn_on: bool
    reason: str
    status: Literal["proposed", "connecting", "done", "rejected", "failed"]
    error: str | None = None


class CofounderActionView(Record):
    """Something the Co-Founder did (or asks to do) for the owner from a chat."""

    id: int
    action: str
    title: str
    detail: str
    status: Literal["proposed", "done", "rejected", "failed", "undone"]
    error: str | None = None
    can_undo: bool = False


ChatTurn.model_rebuild()


class OngoingJob(Record):
    """A job an agent scheduled in the workspace's Hermes (its cron)."""

    id: str
    name: str
    prompt: str
    schedule: str  # Hermes's own words for it (schedule_display)
    next_run_at: str | None
    last_run_at: str | None
    enabled: bool
    # Hermes's job state as Hermes keeps it (scheduled / paused / completed / error).
    state: str = "scheduled"
    paused_reason: str | None = None
    # AGOS's own rhythm job (daily / recap / weekly / heartbeat), made by AGOS and
    # managed on the Vision page / the agent card; None = scheduled by an agent.
    system: str | None = None


class Ongoing(Record):
    jobs: list[OngoingJob]


class Usage(Record):
    """Tokens and cost as Hermes counted them (its sessions table). cost_usd is
    None when Hermes priced none of it ("unknown"); priced is False when part of
    the tokens has no price (then cost_usd is the priced part only)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tokens: int = 0
    cost_usd: float | None = 0.0
    priced: bool = True
    sessions: int = 0


StepStatus = Literal["done", "running", "waiting", "skipped", "failed", "needs_you", "stopped"]


class RunStep(Record):
    """One step of a run: its card, who worked it, its state and what it used."""

    key: str
    title: str
    card_id: str
    agent: str  # who worked it as the owner reads it ("You" for his own OK)
    status: StepStatus
    reason: str | None = None  # why it was skipped, failed or waits on him
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: int | None = None
    attempts: int = 0
    usage: Usage


class RunDetail(Record):
    """A run in detail: its steps in run order and their totals."""

    automation_id: int
    automation_name: str
    run_id: str
    source: str
    started_at: str
    finished_at: str | None
    duration_s: int | None = None
    steps: list[RunStep]
    totals: Usage


class MonthUsage(Record):
    month: str  # YYYY-MM (UTC)
    runs: int = 0
    usage: Usage


class AutomationCost(Record):
    """What an automation's runs used this calendar month and last month (UTC)."""

    automation_id: int
    name: str
    this_month: MonthUsage
    last_month: MonthUsage


AutomationRun.model_rebuild()
AutomationRunGroup.model_rebuild()
