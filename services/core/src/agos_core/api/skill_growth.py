"""Skills that grow and the agent scorecard (Step 63): the owner's settings for
find-skills (the daily request limit) and the weekly skill review job, the request
log (each with its source and what Hermes's scan said), the week's candidates, and
each member's scorecard."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import scorecard, skill_growth, skill_requests
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["skill-growth"])

BASE = "/workspaces/{workspace_id}/skill-growth"


class SkillReviewJob(Record):
    name: str
    on: bool
    time: str
    day: int
    next_at: str | None = None
    last_at: str | None = None
    last_status: str | None = None
    changed_at: str | None = None
    problem: str | None = None


class SkillRequestTest(Record):
    input: str
    expected: str = ""


class SkillRequest(Record):
    id: int
    member: str
    name: str
    source: str
    reason: str
    status: str
    verdict: str
    scan: str
    scripts: bool
    forced: bool
    item_id: int | None
    ask_id: int | None
    tests: list[SkillRequestTest]
    note: str
    created_at: str
    updated_at: str


class SkillCandidate(Record):
    id: int
    item_id: int
    name: str
    batch: str
    status: str
    from_: int = Field(alias="from")
    to: int | None
    why: str
    evidence: list[str]
    score: float | None
    base_score: float | None
    note: str
    created_at: str
    decided_at: str | None


class SkillGrowth(Record):
    limit: int
    used_today: int
    job: SkillReviewJob
    requests: list[SkillRequest]
    candidates: list[SkillCandidate]


class LimitBody(Body):
    limit: int = Field(ge=0, le=20)


class ReviewJobBody(Body):
    on: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day: int = Field(ge=0, le=6)


def _overview(core: Any, workspace_id: str) -> SkillGrowth:
    requests = skill_requests.listed(core, workspace_id)
    return SkillGrowth.model_validate(
        {
            "limit": skill_requests.limit(core, workspace_id),
            "usedToday": skill_requests.used_today(core, workspace_id),
            "job": skill_growth.job(core, workspace_id),
            "requests": requests,
            "candidates": skill_growth.candidates(core, workspace_id),
        }
    )


@router.get(BASE)
def skill_growth_overview(core: CoreDep, workspace_id: str) -> SkillGrowth:
    """The settings, the request log and the candidates in one read (no Hermes start)."""
    return _overview(core, workspace_id)


@router.put(BASE + "/limit")
def set_request_limit(core: CoreDep, workspace_id: str, body: LimitBody) -> SkillGrowth:
    skill_requests.set_limit(core, workspace_id, body.limit)
    return _overview(core, workspace_id)


@router.put(BASE + "/review")
async def set_review_job(core: CoreDep, workspace_id: str, body: ReviewJobBody) -> SkillGrowth:
    """The weekly skill review job in the Co-Founder's Hermes cron: on (made or
    re-timed), off (paused, its time kept)."""
    await asyncio.to_thread(
        lambda: skill_growth.set_job(core, workspace_id, on=body.on, time=body.time, day=body.day)
    )
    return await asyncio.to_thread(_overview, core, workspace_id)


class Scorecard(Record):
    member: str
    title: str
    cards_done: int
    median_minutes: float | None
    blocked: int
    blocked_minutes: int
    submitted: int
    returned: int
    return_rate: float | None
    thumbs_up: int
    thumbs_down: int
    last_heartbeat: str | None
    skills: int
    ready: bool | None


class Scorecards(Record):
    week: str
    members: list[Scorecard]


@router.get("/workspaces/{workspace_id}/scorecards")
def workspace_scorecards(core: CoreDep, workspace_id: str, week: str | None = None) -> Scorecards:
    """Each member's week (an ISO week, default this one), derived from Hermes's board,
    the owner's votes and the profiles' heartbeat jobs (read only)."""
    return Scorecards.model_validate(scorecard.scorecards(core, workspace_id, week))
