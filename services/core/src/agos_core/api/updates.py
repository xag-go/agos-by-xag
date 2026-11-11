"""Settings → General → Updates: one card for both parts of an install
(actions/updates.py composes the two existing update actions).

Must not: run git or the engine itself (the actions do).
"""

import asyncio

from fastapi import APIRouter

from agos_core.actions import updates as actions
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["updates"])


@router.get("/updates")
def status(core: CoreDep) -> dict[str, object]:
    """Both parts' progress, as the two old endpoints gave it."""
    return actions.status(core)


@router.post("/updates/check")
async def check(core: CoreDep) -> dict[str, object]:
    """Check update: both parts, read-only; one `ready` + `note` for the card."""
    return await asyncio.to_thread(actions.run_check, core)


@router.post("/updates/run")
async def run(core: CoreDep) -> dict[str, object]:
    """Update now: AGOS's update first when it has one, else the engine's."""
    return await asyncio.to_thread(actions.start_update, core)
