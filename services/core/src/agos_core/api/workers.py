"""Workers: the workspace's team, its direct messages and groups.

Messages, live answers, stop, approvals… use the chat routes (same ids)."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import hire_kit, hire_suggestions, member_kits
from agos_core.actions import workers as actions
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body, Created
from agos_core.db.records import Record

router = APIRouter(tags=["workers"])


class OpenDm(Body):
    # A library agent's name; "" for the cofounder.
    agent: str = Field(default="", max_length=63)


class NewGroup(Body):
    title: str = Field(min_length=1)
    members: list[str] = Field(default=[])


class GroupMembers(Body):
    members: list[str] = Field()


@router.get("/workspaces/{workspace_id}/workers")
def team(core: CoreDep, workspace_id: str) -> actions.Team:
    return actions.team(core, workspace_id)


class SuggestHires(Body):
    # The owner's optional words to the Co-Founder (no limit: they go on the card as is).
    note: str = ""


class HiresAsked(Record):
    card: str | None
    created: bool = False


@router.get("/workspaces/{workspace_id}/team/suggest-hires")
def asked_for_hires(core: CoreDep, workspace_id: str) -> HiresAsked:
    """The owner's "Suggest hires" card still open on Hermes's board, if any."""
    require_workspace(core, workspace_id)
    return HiresAsked(card=hire_suggestions.open_card(core, workspace_id))


@router.post("/workspaces/{workspace_id}/team/suggest-hires")
def suggest_hires(core: CoreDep, workspace_id: str, body: SuggestHires) -> HiresAsked:
    """A card on the Co-Founder: propose the hires the team needs, one by one (the
    open one instead while an earlier ask is still on the board)."""
    card, created = hire_suggestions.ask(core, workspace_id, body.note)
    return HiresAsked(card=card, created=created)


class SuggestKit(Body):
    # The owner's optional words to the Co-Founder (they go on the card as is).
    note: str = ""


class KitAsked(Record):
    member: str
    card: str


class KitsAsked(Record):
    asked: list[KitAsked]
    # Members whose kit was asked for already (its card is open or waits in the Inbox).
    already: list[KitAsked]
    # Members still without a kit beyond this press's limit (the next press asks).
    left: int = 0


@router.post("/workspaces/{workspace_id}/workers/{member}/suggest-kit")
def suggest_kit(core: CoreDep, workspace_id: str, member: str, body: SuggestKit) -> HiresAsked:
    """A card on the Co-Founder: propose a whole kit for this member (the open one
    instead while an earlier ask, or its proposal, is still waiting)."""
    card, created = member_kits.ask(core, workspace_id, member, body.note)
    return HiresAsked(card=card, created=created)


@router.post("/workspaces/{workspace_id}/team/suggest-kits")
def suggest_kits(core: CoreDep, workspace_id: str, body: SuggestKit) -> KitsAsked:
    """One card per member without a whole kit, each waiting on the one before."""
    return KitsAsked.model_validate(member_kits.ask_all(core, workspace_id, body.note))


@router.post("/workspaces/{workspace_id}/workers/dm", status_code=201)
def open_dm(core: CoreDep, workspace_id: str, body: OpenDm) -> Created:
    return Created(id=actions.open_dm(core, workspace_id, body.agent.strip() or None))


@router.post("/workspaces/{workspace_id}/workers/groups", status_code=201)
def create_group(core: CoreDep, workspace_id: str, body: NewGroup) -> Created:
    return Created(id=actions.create_group(core, workspace_id, body.title, body.members))


@router.put("/workspaces/{workspace_id}/workers/groups/{chat_id}/members", status_code=204)
def set_members(core: CoreDep, workspace_id: str, chat_id: int, body: GroupMembers) -> None:
    actions.set_group_members(core, workspace_id, chat_id, body.members)


# ---- a member's hire kit and Readiness (step 62, actions/hire_kit.py) ---------------------


class KitRoute(Record):
    path: str = ""
    text: str = ""


class ReadinessItem(Record):
    id: str
    kind: Literal["model", "topic", "team", "skill", "tool", "doc"]
    label: str
    ok: bool
    state: Literal["ready", "missing", "not_needed"]
    how: str = ""
    action: str = "none"
    owner: bool = False
    href: str | None = None
    # The Co-Founder's route for it, read from its 'Make it ready' card's result.
    route: KitRoute | None = None
    # The owner's reason when he marked it Not needed.
    reason: str = ""


class OnboardingTry(Record):
    card: str
    n: int
    status: str
    grade: Literal["passed", "failed"] | None = None
    notes: str = ""


class Onboarding(Record):
    task: str
    criteria: list[str]
    tries: list[OnboardingTry]
    passed: bool
    skipped: bool
    escalated: bool


class Readiness(Record):
    member: str
    title: str
    state: Literal["not_ready", "onboarding", "ready"]
    started_anyway: bool = False
    items: list[ReadinessItem]
    onboarding: Onboarding | None = None
    gap_card: str | None = None
    kit: dict[str, Any]


class ReadinessChoice(Body):
    item: str = Field(default="", max_length=200)
    choice: Literal["not_needed", "start_anyway", "skip_test", "retry", "make_topic", "clear"]
    reason: str = Field(default="", max_length=2000)


class KitBody(Body):
    kit: dict[str, Any]


def _readiness(found: dict[str, Any] | None) -> Readiness | None:
    return Readiness.model_validate(found) if found is not None else None


@router.get("/workspaces/{workspace_id}/workers/{member}/readiness")
def member_readiness(core: CoreDep, workspace_id: str, member: str) -> Readiness | None:
    """The member's checklist, each item checked now (null: hired without a kit)."""
    require_workspace(core, workspace_id)
    return _readiness(hire_kit.readiness(core, workspace_id, member))


@router.post("/workspaces/{workspace_id}/workers/{member}/readiness")
async def check_readiness(core: CoreDep, workspace_id: str, member: str) -> Readiness | None:
    """Look again now: AGOS gives what it can, the Co-Founder's card or the
    onboarding test follows."""
    require_workspace(core, workspace_id)
    return _readiness(await asyncio.to_thread(hire_kit.advance, core, workspace_id, member))


@router.post("/workspaces/{workspace_id}/workers/{member}/readiness/choice")
async def choose_readiness(
    core: CoreDep, workspace_id: str, member: str, body: ReadinessChoice
) -> Readiness | None:
    """The owner's button: Not needed (with a reason), Start anyway, Skip test, Retry,
    Make topic, or clear (undo of his choice)."""
    return _readiness(
        await asyncio.to_thread(
            hire_kit.choose, core, workspace_id, member, body.item, body.choice, body.reason
        )
    )


@router.put("/workspaces/{workspace_id}/workers/{member}/kit")
async def save_member_kit(
    core: CoreDep, workspace_id: str, member: str, body: KitBody
) -> Readiness | None:
    """The owner's own kit for a member (his own hire, or one hired before kits)."""
    return _readiness(
        await asyncio.to_thread(hire_kit.save_kit, core, workspace_id, member, body.kit)
    )
