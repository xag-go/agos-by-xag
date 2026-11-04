"""Routines (Step 48): a heartbeat per member and a watchdog per card tree. Both
are Hermes cron jobs; AGOS shows them and holds only what Hermes has no place
for (the watchdog's last stop fingerprint)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from agos_core.actions import heartbeat, watchdogs
from agos_core.actions.heartbeat import Heartbeat
from agos_core.actions.watchdogs import Watchdog
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import HeartbeatBody, ObserveBody, Toggle
from agos_core.db.records import Record

router = APIRouter(tags=["routines"])

COFOUNDER_KEYS = ("cofounder", "manager", "")  # "manager": the name before step 44


def _agent(name: str) -> str:
    return "" if name.lower() in COFOUNDER_KEYS else name


@router.get("/workspaces/{workspace_id}/heartbeats")
async def list_heartbeats(core: CoreDep, workspace_id: str) -> list[Heartbeat]:
    """Every member's heartbeat and the Co-Founder's (agent ""), with the last run
    from Hermes's executions ledger (one read for the page)."""
    return await asyncio.to_thread(heartbeat.list_all, core, workspace_id)


@router.put("/workspaces/{workspace_id}/heartbeats/{agent}")
async def set_heartbeat(
    core: CoreDep, workspace_id: str, agent: str, body: HeartbeatBody
) -> Heartbeat:
    """The toggle on the agent card: on with an interval, or off. `agent`
    "cofounder" is the Co-Founder's own."""
    return await asyncio.to_thread(
        lambda: heartbeat.set_heartbeat(
            core, workspace_id, _agent(agent), on=body.on, interval=body.interval
        )
    )


@router.get("/workspaces/{workspace_id}/watchdogs")
async def list_watchdogs(core: CoreDep, workspace_id: str) -> list[Watchdog]:
    return await asyncio.to_thread(watchdogs.list_all, core, workspace_id)


@router.put("/workspaces/{workspace_id}/watchdogs/{card_id}")
async def watch_card(
    core: CoreDep, workspace_id: str, card_id: str, body: Toggle
) -> Watchdog | None:
    """Watch this tree (on) / stop watching (off) on the card modal."""
    return await asyncio.to_thread(lambda: watchdogs.watch(core, workspace_id, card_id, on=body.on))


class Observed(Record):
    answer: str
    acts: int


@router.post("/workspaces/{workspace_id}/watchdogs/{watchdog_id}/observe")
async def observe(
    core: CoreDep, workspace_id: str, watchdog_id: int, body: ObserveBody
) -> Observed:
    """The watchdog job's report of a stop: 'act', 'seen' or 'escalate' (AGOS's
    fingerprint rule; the agent's tool posts the same through the bridge)."""
    found = await asyncio.to_thread(
        watchdogs.observe, core, workspace_id, watchdog_id, body.fingerprint
    )
    return Observed.model_validate(found)
