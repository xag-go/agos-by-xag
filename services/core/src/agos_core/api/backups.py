"""Settings → Server & backup."""

import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import backups as actions
from agos_core.actions.backups import BackupFile, BackupStatus, Rehearsal
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body

router = APIRouter(tags=["backups"])


class PasswordBody(Body):
    password: str = Field(min_length=10, max_length=200)


class ScheduleBody(Body):
    schedule: Literal["off", "daily", "weekly"]
    keep: int = Field(default=7, ge=1, le=60)


class RehearseBody(Body):
    name: str | None = Field(default=None, max_length=100)


@router.get("/backups")
async def status(core: CoreDep) -> BackupStatus:
    return await asyncio.to_thread(actions.status, core)


@router.put("/backups/password", status_code=204)
async def set_password(core: CoreDep, body: PasswordBody) -> None:
    actions.set_password(core, body.password)


@router.put("/backups/schedule", status_code=204)
async def set_schedule(core: CoreDep, body: ScheduleBody) -> None:
    actions.set_schedule(core, body.schedule, body.keep)


@router.post("/backups/run", status_code=201)
async def run(core: CoreDep) -> BackupFile:
    return await asyncio.to_thread(actions.run_backup, core)


@router.post("/backups/rehearse")
async def rehearse(core: CoreDep, body: RehearseBody) -> Rehearsal:
    return await asyncio.to_thread(actions.rehearse, core, body.name)


class ServerRehearsalBody(Body):
    ok: bool
    summary: str = Field()


@router.post("/server/rehearsal", status_code=204)
async def server_rehearsal(core: CoreDep, body: ServerRehearsalBody) -> None:
    """Recorded by deploy/rehearse-in-container.sh when it finishes."""
    actions.record_server_rehearsal(core, body.ok, body.summary)
