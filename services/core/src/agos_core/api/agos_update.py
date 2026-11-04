"""Settings → General → Update AGOS (Check Update and Update now; `agos update`)."""

import asyncio

from fastapi import APIRouter

from agos_core.actions import agos_update as actions
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["agos-update"])


@router.get("/agos-update")
def status(core: CoreDep) -> dict[str, object]:
    """This release, the last check and the running (or last) update's progress."""
    return actions.status(core)


@router.post("/agos-update/check")
async def check(core: CoreDep) -> dict[str, object]:
    """Check Update: a newer AGOS release on its branch? (read-only)"""
    return await asyncio.to_thread(actions.run_check, core)


@router.post("/agos-update/run")
async def run(core: CoreDep) -> dict[str, object]:
    """Update now: backups, the new release, restart (AGOS is down a few minutes)."""
    return await asyncio.to_thread(actions.start_update, core)
