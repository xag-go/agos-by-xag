"""The agent's tools in Hermes, over HTTP: Kanban asks, proposals, asks to the owner,
goals, watchdogs, card documents and comments, labels, status cards, reviews,
pipelines, skill reviews, services, clarify.

Owns: one thin route per tool, each through its action.
Must not: decide what needs the owner (actions/owner_gate.py).

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio
import re
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.api.bridge_access import ADDRESS, Auth, Taker, _checked
from agos_core.api.deps import CoreDep

__all__ = [
    "AskOwner",
    "CardCommentCall",
    "CardDocumentCall",
    "CardTokensTold",
    "Clarify",
    "GoalsCall",
    "KanbanAsk",
    "KanbanBlocked",
    "LabelCall",
    "PipelineEvent",
    "Propose",
    "ReviewCall",
    "ReviewCheck",
    "SearchCall",
    "ServiceCall",
    "SkillReviewCall",
    "SkillTest",
    "StatusCardCall",
    "WatchdogObserve",
    "ask_owner",
    "card_comment",
    "card_document",
    "card_tokens_told",
    "clarify",
    "goals_call",
    "kanban_ask",
    "kanban_blocked",
    "label_call",
    "pipeline_event",
    "pipeline_sweep",
    "propose",
    "review_call",
    "review_check",
    "search_call",
    "service_call",
    "skill_review_call",
    "status_card_call",
    "watchdog_observe",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


class Clarify(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    question: str = Field(max_length=20_000)
    choices: list[str] = Field(default_factory=list, max_length=20)


@router.post("/clarify")
async def clarify(
    core: CoreDep, workspace_id: str, body: Clarify, authorization: Auth = None
) -> dict[str, bool]:
    """Hermes's clarify in an AGOS conversation: the agent asks and waits."""
    ws = _checked(core, workspace_id, authorization)
    with_choices = [c[:500] for c in body.choices]
    shown = await asyncio.to_thread(
        actions.clarify_asked, core, ws, body.chat, body.question, with_choices
    )
    return {"shown": shown}


class CardTokensTold(BaseModel):
    card: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    level: int = Field(ge=1)
    tokens: int = Field(ge=0)
    usual: int = Field(ge=0)


@router.post("/card-tokens-told")
async def card_tokens_told(
    core: CoreDep, workspace_id: str, body: CardTokensTold, authorization: Auth = None
) -> dict[str, bool]:
    """Hermes decided a Kanban card is far past its usual size (its own count and
    mark, in the agos-guard plugin): the owner hears it (the card goes on)."""
    from agos_core.actions import token_watch

    ws = _checked(core, workspace_id, authorization)
    await asyncio.to_thread(token_watch.told, core, ws, body.card, body.tokens, body.usual)
    return {"ok": True}


class KanbanAsk(BaseModel):
    card: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    # "" = the Co-Founder working a card.
    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    detail: str = Field(default="", max_length=900)


@router.post("/kanban-ask")
async def kanban_ask(
    core: CoreDep, workspace_id: str, body: KanbanAsk, authorization: Auth = None
) -> dict[str, bool]:
    """A member working a Kanban card needs the owner's OK (his "Ask me" rule)."""
    from agos_core.actions import kanban_asks

    ws = _checked(core, workspace_id, authorization)
    new = await asyncio.to_thread(
        kanban_asks.ask, core, ws, body.card, body.member, body.action, body.label, body.detail
    )
    return {"asked": new}


class KanbanBlocked(BaseModel):
    card: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/kanban-blocked")
async def kanban_blocked(
    core: CoreDep, workspace_id: str, body: KanbanBlocked, authorization: Auth = None
) -> dict[str, bool]:
    """A card blocked for the owner's OK (Hermes's kanban_task_blocked hook): when he
    has already answered, it goes on now."""
    from agos_core.actions import kanban_asks

    ws = _checked(core, workspace_id, authorization)
    settled = await asyncio.to_thread(kanban_asks.settle, core, ws, body.card)
    return {"settled": settled}


class Propose(BaseModel):
    """An agent's agos_propose tool (the guard's asks.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    kind: str = Field(max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict)
    words: str = Field(default="", max_length=20_000)
    revises: str = Field(default="", max_length=64)
    card: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


@router.post("/propose")
async def propose(
    core: CoreDep, workspace_id: str, body: Propose, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import proposals
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    try:
        return await asyncio.to_thread(
            proposals.propose,
            core,
            ws,
            body.kind,
            body.payload,
            body.words,
            member=body.member,
            revises=body.revises,
            by_tool=True,
        )
    except ActionError as error:
        return {"error": error.message}


class AskOwner(BaseModel):
    """An agent's agos_ask_owner tool (the guard's asks.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    kind: str = Field(max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict)
    continuation: str = Field(default="wake_assignee", max_length=20)
    card: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


@router.post("/ask-owner")
async def ask_owner(
    core: CoreDep, workspace_id: str, body: AskOwner, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import questions
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    try:
        return await asyncio.to_thread(
            questions.ask,
            core,
            ws,
            body.member,
            body.kind,
            body.payload,
            "",
            continuation=body.continuation,
            asked_from=body.card,
        )
    except ActionError as error:
        return {"error": error.message}


class GoalsCall(BaseModel):
    """An agent's agos_goals tool (the guard's goals.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(default="status", pattern=r"^(status|propose|post)$")
    # propose: goal | kr | project | kr_update | daily_plan | vision (the payload's
    # `change` says it exactly; the kind fills it in when missing). post: recap | weekly.
    kind: str = Field(default="", max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict)
    words: str = Field(default="", max_length=20_000)
    revises: str = Field(default="", max_length=64)


def _change_of(kind: str, payload: dict[str, Any]) -> str:
    """The plan change a tool call's kind stands for (when its payload says none)."""
    if payload.get("change"):
        return str(payload["change"])
    if payload.get("delete") is True and kind in ("goal", "kr", "project"):
        return f"delete_{kind}"
    if kind == "kr":
        return "update_kr" if payload.get("kr_id") else "add_kr"
    if kind == "project":
        return "update_project" if payload.get("project_id") else "add_project"
    if kind == "goal":
        return "update_goal" if payload.get("goal_id") else "add_goal"
    return {"vision": "suggest_vision", "kr_update": "kr_update", "daily_plan": "daily_plan"}.get(
        kind, ""
    )


@router.post("/goals")
async def goals_call(
    core: CoreDep, workspace_id: str, body: GoalsCall, authorization: Auth = None
) -> dict[str, Any]:
    """The plan and its progress, a plan change proposed to the owner (kind 'goal':
    a goal, a key result, a project, a key result's number, today's plan), or the
    Co-Founder's recap / weekly review post."""
    from agos_core.actions import goals, proposals, today
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    if body.action == "status":
        said = await asyncio.to_thread(goals.status_text, core, ws)
        if not body.member:
            # The Co-Founder's view ends with the team's scorecards (Step 63): its
            # weekly review reads them and proposes fixes.
            from agos_core.actions import scorecard

            lines = await asyncio.to_thread(scorecard.status_lines, core, ws)
            said = said + "\n\n" + "\n".join(lines)
        return {"status": said}
    try:
        if body.action == "post":
            if body.member:
                return {"error": "Only the Co-Founder posts the recap and the weekly review."}
            return await asyncio.to_thread(today.post, core, ws, body.kind, body.words)
        payload = {
            **{k: v for k, v in body.payload.items() if k != "delete"},
            "change": _change_of(body.kind, body.payload),
        }
        return await asyncio.to_thread(
            lambda: proposals.propose(
                core,
                ws,
                "goal",
                payload,
                body.words,
                member=body.member,
                revises=body.revises if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", body.revises) else "",
                by_tool=True,
            )
        )
    except ActionError as error:
        return {"error": error.message}


class WatchdogObserve(BaseModel):
    """The watchdog job's agos_watchdog_observe tool (the guard's watchdog.py)."""

    watchdog_id: int
    fingerprint: str = Field(default="", max_length=4000)


@router.post("/watchdog-observe")
async def watchdog_observe(
    core: CoreDep, workspace_id: str, body: WatchdogObserve, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import watchdogs
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    try:
        return await asyncio.to_thread(
            watchdogs.observe, core, ws, body.watchdog_id, body.fingerprint
        )
    except ActionError as error:
        return {"error": error.message}


class CardDocumentCall(BaseModel):
    """An agent's agos_card_document tool (the guard's documents.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    key: str = Field(default="", max_length=70)
    action: str = Field(default="write", pattern=r"^(write|read|annotations)$")
    content: str = Field(default="", max_length=2_000_000)
    base_revision: int | None = Field(default=None, ge=0)
    why: str = Field(default="", max_length=300)


@router.post("/card-document")
async def card_document(
    core: CoreDep, workspace_id: str, body: CardDocumentCall, authorization: Auth = None
) -> dict[str, Any]:
    """Read / write (with the revision check) / list the comments of a card's
    document, for the agent; a refusal is an {"error": ...} answer it reads."""
    from agos_core.actions import card_docs

    ws = _checked(core, workspace_id, authorization)
    return await asyncio.to_thread(
        lambda: card_docs.tool(
            core,
            ws,
            member=body.member,
            card_id=body.card,
            key=body.key,
            action=body.action,
            content=body.content,
            base_revision=body.base_revision,
            why=body.why,
        )
    )


class SearchCall(BaseModel):
    """An agent's agos_search tool (the guard's search.py): the same search as the
    owner's Search page, in this workspace only."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    query: str = Field(max_length=200)
    types: list[str] = Field(default_factory=list, max_length=8)


@router.post("/search")
async def search_call(
    core: CoreDep, workspace_id: str, body: SearchCall, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import search

    ws = _checked(core, workspace_id, authorization)
    return {"found": await asyncio.to_thread(search.for_agent, core, ws, body.query, body.types)}


class CardCommentCall(BaseModel):
    """The guard's post_tool_call on Hermes's kanban_comment (agos_guard/threads.py):
    a comment landed on this workspace's board. AGOS reads it back from Hermes."""

    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    comment: int = Field(ge=1)


@router.post("/card-comment")
async def card_comment(
    core: CoreDep, workspace_id: str, body: CardCommentCall, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import threads
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    try:
        return await asyncio.to_thread(threads.agent_commented, core, ws, body.card, body.comment)
    except ActionError as error:
        return {"error": str(error)}


class LabelCall(BaseModel):
    """An agent's agos_label tool (the guard's threads.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(default="list", pattern=r"^(list|add|remove)$")
    card: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    labels: list[str] = Field(default_factory=list, max_length=20)


@router.post("/labels")
async def label_call(
    core: CoreDep, workspace_id: str, body: LabelCall, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import labels

    ws = _checked(core, workspace_id, authorization)
    return await asyncio.to_thread(
        lambda: labels.for_agent(core, ws, action=body.action, card=body.card, names=body.labels)
    )


class StatusCardCall(BaseModel):
    """The Co-Founder's agos_status_card tool, and a status card's monitor script
    (action monitor: the scope's facts Hermes compares)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(default="read", pattern=r"^(list|read|write|monitor)$")
    card: int = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=20_000)
    why: str = Field(default="", max_length=300)


@router.post("/status-card")
async def status_card_call(
    core: CoreDep, workspace_id: str, body: StatusCardCall, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import status_cards

    ws = _checked(core, workspace_id, authorization)
    return await asyncio.to_thread(
        lambda: status_cards.tool(
            core,
            ws,
            member=body.member,
            action=body.action,
            card_id=body.card,
            summary=body.summary,
            why=body.why,
        )
    )


class ReviewCall(BaseModel):
    """An agent's agos_review tool (the guard's review.py): its verdict, or that the
    Hermes step AGOS gave for it landed."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    verdict: str = Field(pattern=r"^(submit|plan_ready|approve|changes|landed)$")
    note: str = Field(default="", max_length=4000)
    summary: str = Field(default="", max_length=4000)
    working: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


@router.post("/review")
async def review_call(
    core: CoreDep, workspace_id: str, body: ReviewCall, authorization: Auth = None
) -> dict[str, Any]:
    """The step a verdict takes on Hermes's board (the guard takes it with the
    agent's run), or {"error": ...} the agent reads; `landed`: tell the owner."""
    from agos_core.actions import reviews
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    if body.verdict == "landed":
        try:
            return await asyncio.to_thread(reviews.landed, core, ws, body.card)
        except ActionError as error:
            return {"error": error.message}
    try:
        return await asyncio.to_thread(
            lambda: reviews.verdict(
                core,
                ws,
                member=body.member,
                card_id=body.card,
                verdict=body.verdict,
                note=body.note,
                summary=body.summary,
                working=body.working,
            )
        )
    except ActionError as error:
        return {"error": error.message}


class ReviewCheck(BaseModel):
    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    tool: str = Field(max_length=40)


@router.post("/review-check")
async def review_check(
    core: CoreDep, workspace_id: str, body: ReviewCheck, authorization: Auth = None
) -> dict[str, str]:
    """May this finishing call of a card's worker go (review stages, plan first)?"""
    from agos_core.actions import reviews

    ws = _checked(core, workspace_id, authorization)
    refuse = await asyncio.to_thread(reviews.check, core, ws, body.card, body.tool, body.member)
    return {"refuse": refuse}


class PipelineEvent(BaseModel):
    """One of Hermes's Kanban hooks on a card (the guard's kanban observers): the
    workspace's pipeline rules read the card and act once per move (Step 59)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/pipeline-event")
async def pipeline_event(
    core: CoreDep, workspace_id: str, body: PipelineEvent, authorization: Auth = None
) -> dict[str, int]:
    from agos_core.actions import hire_kit, pipelines, skill_growth

    ws = _checked(core, workspace_id, authorization)
    fired = await asyncio.to_thread(pipelines.card_moved, core, ws, body.card)
    await asyncio.to_thread(hire_kit.sweep, core, ws)  # step 62: a test done, a gap closed
    from agos_core.actions import founder

    # A card of the Founder's (the owner) that is his now reaches his phone once.
    await asyncio.to_thread(founder.sweep, core, ws)
    # A skill test's card (a requested skill, a candidate version): they advance.
    await asyncio.to_thread(skill_growth.card_moved, core, ws, body.card)
    return {"fired": fired}


@router.post("/pipeline-sweep")
async def pipeline_sweep(
    core: CoreDep, workspace_id: str, body: Taker, authorization: Auth = None
) -> dict[str, int]:
    """Hermes's dispatcher ticked: cards that moved with no hook (review, unblock,
    schedule, archive) are found on the board and their rules act."""
    from agos_core.actions import hire_kit, pipelines, skill_growth

    ws = _checked(core, workspace_id, authorization)
    del body
    fired = await asyncio.to_thread(pipelines.sweep, core, ws)
    # Step 62: new members not ready yet move on (a connector connected, a key added).
    await asyncio.to_thread(hire_kit.sweep, core, ws)
    # Step 63: find-skills and the skill review job are there; tested skills advance.
    await asyncio.to_thread(skill_growth.sweep, core, ws)
    from agos_core.actions import founder

    # The Founder's cards whose parents just finished are his now: told once.
    await asyncio.to_thread(founder.sweep, core, ws)
    return {"fired": fired}


class SkillTest(BaseModel):
    input: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=4000)


class SkillReviewCall(BaseModel):
    """The skill review job's monitor script (`evidence`) and the Co-Founder's
    agos_skill_candidate tool (the guard's skills.py)."""

    action: str = Field(default="evidence", pattern=r"^(evidence|candidate)$")
    skill: str = Field(default="", max_length=64)
    text: str = Field(default="", max_length=60_000)
    why: str = Field(default="", max_length=300)
    evidence: list[str] = Field(default_factory=list, max_length=30)
    tests: list[SkillTest] = Field(default_factory=list, max_length=2)


@router.post("/skill-review")
async def skill_review_call(
    core: CoreDep, workspace_id: str, body: SkillReviewCall, authorization: Auth = None
) -> dict[str, Any]:
    """Skills that grow (Step 63): the week's evidence for the job's monitor, or a
    candidate version to test."""
    from agos_core.actions import skill_growth
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    try:
        if body.action == "evidence":
            return {"evidence": await asyncio.to_thread(skill_growth.evidence, core, ws)}
        return await asyncio.to_thread(
            lambda: skill_growth.candidate(
                core,
                ws,
                skill=body.skill,
                text=body.text,
                why=body.why,
                evidence_refs=body.evidence,
                tests=[t.model_dump() for t in body.tests],
            )
        )
    except ActionError as error:
        return {"error": error.message}


class ServiceCall(BaseModel):
    """A card's worker's agos_service tool (the guard's services.py, Step 59): the
    background process Hermes started for it, or a list / stop."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(pattern=r"^(started|stopped|list)$")
    card: str = Field(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    profile: str = Field(default="", max_length=200)
    process_id: str = Field(default="", alias="processId", max_length=64)
    pid: int | None = Field(default=None, ge=1)
    pid_scope: str = Field(default="host", alias="pidScope", pattern=r"^(host|sandbox)$")
    command: str = Field(default="", max_length=2000)
    port: int = Field(default=0, ge=0, le=65535)
    label: str = Field(default="", max_length=80)


@router.post("/service")
async def service_call(
    core: CoreDep, workspace_id: str, body: ServiceCall, authorization: Auth = None
) -> dict[str, Any]:
    from agos_core.actions import card_services

    ws = _checked(core, workspace_id, authorization)
    return await asyncio.to_thread(
        lambda: card_services.from_tool(
            core,
            ws,
            action=body.action,
            card_id=body.card,
            profile=body.profile,
            process_id=body.process_id,
            pid=body.pid,
            pid_scope=body.pid_scope,
            command=body.command,
            port=body.port,
            label=body.label,
        )
    )
