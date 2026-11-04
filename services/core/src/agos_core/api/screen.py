"""The workspace's screen: what its agent sees in its own browser / desktop.

The screen is Hermes's Bot Desktop, inside the workspace's sandbox. "enabled"
is Hermes's own config (browser or computer use not in the profile's
`agent.disabled_toolsets`); the picture is a read-only grab of the screen Hermes
has running (its `bot-desktop/sandbox.json` record), 204 while it is off.
Nothing on this machine is shown: the screen exists only in that container."""

from __future__ import annotations

from fastapi import APIRouter, Response

from agos_core.actions.screen import IDLE_KEY as IDLE_KEY
from agos_core.actions.screen import idle_stop_minutes
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.db.records import Record

router = APIRouter(tags=["screen"])


class ScreenStatus(Record):
    enabled: bool
    # Hermes stops an unused screen after this (its bot_desktop.idle_stop_minutes,
    # tools/bot_desktop/runtime.py idle_stop_seconds); 0 = never; null = not known.
    idle_stop_minutes: float | None = None


@router.get("/workspaces/{workspace_id}/screen")
async def screen_status(core: CoreDep, workspace_id: str) -> ScreenStatus:
    require_workspace(core, workspace_id)
    engine = core.engine
    if engine is None:
        return ScreenStatus(enabled=False)
    import asyncio

    return ScreenStatus(
        enabled=await asyncio.to_thread(engine.has_screen, workspace_id),
        idle_stop_minutes=await asyncio.to_thread(idle_stop_minutes, core, workspace_id),
    )


@router.get("/workspaces/{workspace_id}/screen.jpg")
async def screen_picture(core: CoreDep, workspace_id: str, width: int = 1440) -> Response:
    require_workspace(core, workspace_id)
    engine = core.engine
    if engine is None:
        return Response(status_code=404)
    import asyncio

    jpeg = await asyncio.to_thread(
        engine.screen_jpeg, workspace_id, width=max(320, min(width, 1920))
    )
    if jpeg is None:
        return Response(status_code=204)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
