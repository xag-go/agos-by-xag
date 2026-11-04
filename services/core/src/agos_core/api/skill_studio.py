"""Skill Studio: a workspace skill's versions (Hermes's skill ledger, diffed and
restored through Hermes), its test runs (Hermes Kanban cards) and its auto-update
flag (a Hermes cron job)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import skill_tests, skill_updates, skill_versions
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body, Created
from agos_core.db.records import Record

router = APIRouter(tags=["skill-studio"])

BASE = "/workspaces/{workspace_id}/skills/{item_id}"


# ---- versions ----------------------------------------------------------------------------


class SkillVersion(Record):
    number: int
    at: str
    author: str
    action: str
    summary: str
    size: int
    files: list[str]
    entries: list[str]


class FileDiff(Record):
    path: str
    diff: str


class Restored(Record):
    restored: bool
    version: int
    skipped: list[str]


@router.get(BASE + "/versions")
async def list_versions(core: CoreDep, workspace_id: str, item_id: int) -> list[SkillVersion]:
    """Newest first; derived from Hermes's skill ledger (asked again only when it moved)."""
    found = await asyncio.to_thread(skill_versions.versions, core, workspace_id, item_id)
    return [SkillVersion.model_validate(v) for v in found]


@router.get(BASE + "/versions/diff")
async def diff_versions(
    core: CoreDep, workspace_id: str, item_id: int, a: int, b: int
) -> list[FileDiff]:
    """Unified diff per file, from version a to version b (server-side)."""
    found = await asyncio.to_thread(skill_versions.diff, core, workspace_id, item_id, a, b)
    return [FileDiff.model_validate(d) for d in found]


@router.get(BASE + "/versions/{number}")
async def version_content(
    core: CoreDep, workspace_id: str, item_id: int, number: int
) -> dict[str, str | None]:
    """One version's files (text; None for a binary one)."""
    return await asyncio.to_thread(skill_versions.content, core, workspace_id, item_id, number)


@router.post(BASE + "/versions/{number}/restore")
async def restore_version(core: CoreDep, workspace_id: str, item_id: int, number: int) -> Restored:
    """One Hermes skill_manage batch makes the folder that version (its ledger
    records it as the next version); already that: nothing written."""
    found = await asyncio.to_thread(skill_versions.restore, core, workspace_id, item_id, number)
    return Restored.model_validate(found)


# ---- tests ----------------------------------------------------------------------------


class TestInput(Record):
    id: int
    name: str
    text: str
    expected: str


class TestRun(Record):
    id: int
    input_id: int | None
    input_name: str
    version: int
    member: str
    card: str
    status: str
    output: str
    grade: str | None
    notes: str
    score: float | None = None  # the grader's 0-1 score (Step 63)
    gradable: bool
    created_at: str
    finished_at: str | None


class SkillTests(Record):
    template: str
    default_template: str
    checklist: str
    version: int
    inputs: list[TestInput]
    runs: list[TestRun]


class TestSettingsBody(Body):
    template: str = Field(default="", max_length=20_000)
    checklist: str = Field(default="", max_length=20_000)


class TestInputBody(Body):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20_000)
    expected: str = Field(default="", max_length=20_000)


class RunBody(Body):
    input_id: int
    member: str = Field(default="cofounder", max_length=64)


class GradeResult(Record):
    grade: str
    notes: str


@router.get(BASE + "/tests")
async def tests_overview(core: CoreDep, workspace_id: str, item_id: int) -> SkillTests:
    """The Tests tab in one read (runs brought up to date with their cards)."""
    found = await asyncio.to_thread(skill_tests.overview, core, workspace_id, item_id)
    return SkillTests.model_validate(found)


@router.put(BASE + "/tests/settings", status_code=204)
def save_test_settings(
    core: CoreDep, workspace_id: str, item_id: int, body: TestSettingsBody
) -> None:
    skill_tests.save_settings(
        core, workspace_id, item_id, template=body.template, checklist=body.checklist
    )


@router.post(BASE + "/tests/inputs", status_code=201)
def add_test_input(core: CoreDep, workspace_id: str, item_id: int, body: TestInputBody) -> Created:
    return Created(
        id=skill_tests.add_input(
            core, workspace_id, item_id, name=body.name, text=body.text, expected=body.expected
        )
    )


@router.put(BASE + "/tests/inputs/{input_id}", status_code=204)
def update_test_input(
    core: CoreDep, workspace_id: str, item_id: int, input_id: int, body: TestInputBody
) -> None:
    skill_tests.update_input(
        core,
        workspace_id,
        item_id,
        input_id,
        name=body.name,
        text=body.text,
        expected=body.expected,
    )


@router.delete(BASE + "/tests/inputs/{input_id}", status_code=204)
def delete_test_input(core: CoreDep, workspace_id: str, item_id: int, input_id: int) -> None:
    skill_tests.delete_input(core, workspace_id, item_id, input_id)


@router.post(BASE + "/tests/run", status_code=201)
async def run_test(core: CoreDep, workspace_id: str, item_id: int, body: RunBody) -> Created:
    """A Hermes Kanban card for the member, with the skill loaded and pinned."""
    run_id = await asyncio.to_thread(
        skill_tests.run, core, workspace_id, item_id, input_id=body.input_id, member=body.member
    )
    return Created(id=run_id)


@router.post(BASE + "/tests/runs/{run_id}/rerun", status_code=201)
async def rerun_test(core: CoreDep, workspace_id: str, item_id: int, run_id: int) -> Created:
    """The same input and pinned version again, on a new card."""
    return Created(
        id=await asyncio.to_thread(skill_tests.rerun, core, workspace_id, item_id, run_id)
    )


@router.post(BASE + "/tests/runs/{run_id}/grade")
async def grade_test(core: CoreDep, workspace_id: str, item_id: int, run_id: int) -> GradeResult:
    """Hermes's auxiliary model grades the run (again)."""
    found = await asyncio.to_thread(skill_tests.regrade, core, workspace_id, item_id, run_id)
    return GradeResult.model_validate(found)


# ---- auto-update ---------------------------------------------------------------------------


class AutoUpdateBody(Body):
    on: bool


class AutoUpdateState(Record):
    on: bool
    job: str  # "made" / "rewritten" / "removed" / "" (what Hermes's cron got)


@router.put(BASE + "/auto-update")
async def set_auto_update(
    core: CoreDep, workspace_id: str, item_id: int, body: AutoUpdateBody
) -> AutoUpdateState:
    """Follow the source: the workspace's Hermes cron job updates it nightly."""

    def go() -> dict[str, Any]:
        return {"on": body.on, "job": skill_updates.set_flag(core, workspace_id, item_id, body.on)}

    return AutoUpdateState.model_validate(await asyncio.to_thread(go))
