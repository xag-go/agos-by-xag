"""The workspace Log's HTTP route (actions/services/system/workspace_log.py builds it).

Read-only: one timeline of everything that happened in a project, with who did it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from agos_core.actions.services.system import workspace_log as log_service
from agos_core.actions.services.system.workspace_log import Area, LogPage
from agos_core.actions.services.system.workspace_log import LogActor as LogActor
from agos_core.actions.services.system.workspace_log import LogEntry as LogEntry
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["log"])


@router.get("/workspaces/{workspace_id}/log")
def workspace_log(
    core: CoreDep,
    workspace_id: str,
    level: Literal["all", "problems"] = "all",
    area: Area | None = None,
    q: str = Query(default="", max_length=200),
    before: str = Query(default="9999", max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    actor: str = Query(default="", max_length=80, pattern=r"^[a-z]*(:[A-Za-z0-9_.-]{1,64})?$"),
    since: str = Query(default="", max_length=40, description="From this day (YYYY-MM-DD) or time"),
    until: str = Query(default="", max_length=40, description="Up to this day (included) or time"),
) -> LogPage:
    return log_service.page(
        core,
        workspace_id,
        level=level,
        area=area,
        q=q,
        before=before,
        limit=limit,
        actor=actor,
        since=since,
        until=until,
    )
