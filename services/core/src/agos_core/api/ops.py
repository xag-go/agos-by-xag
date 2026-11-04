"""Operations: feature flags (Settings → General → Labs)."""

import asyncio
import time

from fastapi import APIRouter, Request

from agos_core.actions import diagnostics, flags
from agos_core.actions.flags import FlagView
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["ops"])


class FlagValue(Body):
    on: bool


class FlagChange(Record):
    before: bool


@router.get("/flags")
async def list_flags(core: CoreDep) -> list[FlagView]:
    return await asyncio.to_thread(flags.listed, core)


@router.put("/flags/{name}")
async def put_flag(core: CoreDep, name: str, body: FlagValue) -> FlagChange:
    return FlagChange(before=await asyncio.to_thread(flags.put, core, name, body.on))


class Diagnostics(Record):
    made_at: str
    text: str


@router.get("/diagnostics")
async def get_diagnostics(core: CoreDep, request: Request) -> Diagnostics:
    """A redacted report for a GitHub issue (agos doctor --bundle, Settings → Errors)."""
    health = diagnostics.deep(request.app, core)
    text = await asyncio.to_thread(diagnostics.report, core, health)
    return Diagnostics(made_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), text=text)
