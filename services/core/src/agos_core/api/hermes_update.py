"""Settings → General → Hermes update (the Check Update button and the update)."""

import asyncio

from fastapi import APIRouter

from agos_core.actions import hermes_update as actions
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["hermes-update"])


@router.get("/hermes-update")
def status(core: CoreDep) -> dict[str, object]:
    """The last check's answer and the running (or last) update's progress."""
    return actions.status(core)


@router.post("/hermes-update/check")
async def check(core: CoreDep) -> dict[str, object]:
    """Check Update: read-only, Hermes's own answer (nothing installed)."""
    return await asyncio.to_thread(actions.run_check, core)


@router.post("/hermes-update/run")
async def run(core: CoreDep) -> dict[str, object]:
    """Do the update now (the popup's yes). Progress comes from GET /hermes-update."""
    return await asyncio.to_thread(actions.start_update, core)
