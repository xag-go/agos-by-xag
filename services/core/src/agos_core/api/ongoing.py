"""What the agents keep going for the owner in a workspace (jobs they scheduled in
its Hermes), with Stop; and Hermes's own settings for the workspace."""

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import ongoing as actions
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Ongoing

router = APIRouter(tags=["ongoing"])


@router.get("/workspaces/{workspace_id}/ongoing")
async def get_ongoing(core: CoreDep, workspace_id: str) -> Ongoing:
    return await asyncio.to_thread(actions.ongoing, core, workspace_id)


@router.post("/workspaces/{workspace_id}/scheduled/{job_id}/remove", status_code=204)
async def remove_scheduled(core: CoreDep, workspace_id: str, job_id: str) -> None:
    """Stops a job an agent scheduled in the workspace's Hermes."""
    await asyncio.to_thread(actions.remove_job, core, workspace_id, job_id)


class HermesSettings(Body):
    values: dict[str, str] = Field(default_factory=dict, max_length=20)
    # Hermes's own default of each (read from Hermes; empty when it can't be read).
    defaults: dict[str, str] = Field(default_factory=dict, max_length=20)


@router.get("/workspaces/{workspace_id}/hermes-settings")
async def get_hermes_settings(core: CoreDep, workspace_id: str) -> HermesSettings:
    """Hermes's own settings for this workspace, as its Hermes has them."""
    from agos_core.actions import hermes_settings

    values = await asyncio.to_thread(hermes_settings.read, core, workspace_id)
    return HermesSettings(
        values=values, defaults=await asyncio.to_thread(hermes_settings.defaults, core)
    )


@router.put("/workspaces/{workspace_id}/hermes-settings")
async def put_hermes_settings(
    core: CoreDep, workspace_id: str, body: HermesSettings
) -> HermesSettings:
    """Written into the workspace's Hermes (AGOS keeps no copy)."""
    from agos_core.actions import hermes_settings

    values = await asyncio.to_thread(hermes_settings.write, core, workspace_id, body.values)
    return HermesSettings(
        values=values, defaults=await asyncio.to_thread(hermes_settings.defaults, core)
    )


class AccessLists(Body):
    """Hermes's own deny and allow rules of the workspace (approvals.deny,
    command_allowlist), as its Co-Founder's Hermes has them."""

    deny: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)


@router.get("/workspaces/{workspace_id}/access-lists")
async def get_access_lists(core: CoreDep, workspace_id: str) -> AccessLists:
    from agos_core.actions import access
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return AccessLists.model_validate(await asyncio.to_thread(access.lists, core, workspace_id))


@router.put("/workspaces/{workspace_id}/access-lists")
async def put_access_lists(core: CoreDep, workspace_id: str, body: AccessLists) -> AccessLists:
    """Written into the workspace's Hermes (its Co-Founder, then each member)."""
    from agos_core.actions import access
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    found = await asyncio.to_thread(access.set_lists, core, workspace_id, body.deny, body.allow)
    return AccessLists.model_validate(found)


class HeldWriteChange(Body):
    """One note a held memory write adds, removes or changes (Hermes's pinned entry)."""

    action: str  # add / remove / patch / replace
    target: str  # memory (the agent's own notes) / user (its notes about the owner)
    before: str  # the note as it is now ("" for an add)
    after: str  # the note as it would be ("" for a remove)
    gone: bool  # the note isn't in the memory any more: approving would fail


class HeldWrite(Body):
    """One memory or skill write Hermes holds for the owner's review."""

    profile: str  # the engine key of the agent's Hermes profile
    agent: str
    id: str
    subsystem: str  # memory / skills
    action: str
    summary: str
    target: str
    origin: str  # foreground / background_review
    created_at: float
    detail: str  # what it changes (Hermes's own diff for a skill)
    ops: list[HeldWriteChange] = Field(default_factory=list)  # a memory write, note by note
    group: str = ""  # the same request asked again (only a changed note's wording differs)


class HeldWrites(Body):
    gates: dict[str, bool]  # Hermes's memory/skills write_approval (on in any profile)
    items: list[HeldWrite]
    unread: list[str] = Field(default_factory=list)  # agents whose Hermes didn't answer
    said: str = ""  # what Hermes answered to the last approve/reject


class HeldWriteDecision(Body):
    approve: bool


@router.get("/workspaces/{workspace_id}/held-writes")
async def get_held_writes(core: CoreDep, workspace_id: str) -> HeldWrites:
    from agos_core.actions import held_writes

    return HeldWrites.model_validate(await asyncio.to_thread(held_writes.read, core, workspace_id))


@router.post("/workspaces/{workspace_id}/held-writes/{profile}/{subsystem}/{pending_id}")
async def decide_held_write(
    core: CoreDep,
    workspace_id: str,
    profile: str,
    subsystem: str,
    pending_id: str,
    body: HeldWriteDecision,
) -> HeldWrites:
    from agos_core.actions import held_writes

    found = await asyncio.to_thread(
        held_writes.decide, core, workspace_id, profile, subsystem, pending_id, body.approve
    )
    return HeldWrites.model_validate(found)


class HeldWriteExplained(Body):
    text: str  # one or two plain sentences from Hermes's auxiliary model


@router.post("/workspaces/{workspace_id}/held-writes/{profile}/{subsystem}/{pending_id}/explain")
async def explain_held_write(
    core: CoreDep, workspace_id: str, profile: str, subsystem: str, pending_id: str
) -> HeldWriteExplained:
    from agos_core.actions import held_writes

    text = await asyncio.to_thread(
        held_writes.explain, core, workspace_id, profile, subsystem, pending_id
    )
    return HeldWriteExplained(text=text)


class HeldGroupDecision(Body):
    profile: str = Field(min_length=1, max_length=200)
    subsystem: str = Field(min_length=1, max_length=20)
    ids: list[str] = Field(min_length=1, max_length=50)
    approve: bool


class HeldGroupDecided(Body):
    said: str
    waiting: int


@router.post("/workspaces/{workspace_id}/held-writes/decide")
async def decide_held_group(
    core: CoreDep, workspace_id: str, body: HeldGroupDecision
) -> HeldGroupDecided:
    """One request asked several times, decided as one: Approve applies the newest
    copy, Reject drops them all (Hermes's own approve / reject)."""
    from agos_core.actions import held_writes

    found = await asyncio.to_thread(
        held_writes.decide_group,
        core,
        workspace_id,
        body.profile,
        body.subsystem,
        body.ids,
        body.approve,
    )
    return HeldGroupDecided.model_validate(found)
