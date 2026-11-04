"""Across workspaces: a short status for the Dashboard (actions/services/system/dashboard.py)."""

from fastapi import APIRouter

from agos_core.actions.services.system import dashboard
from agos_core.actions.services.system.dashboard import WorkspaceOverview
from agos_core.actions.services.system.dashboard import read_ahead as read_ahead
from agos_core.actions.services.system.dashboard import workspace_overview as workspace_overview
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["overview"])


@router.get("/workspaces/{workspace_id}/overview")
def overview(core: CoreDep, workspace_id: str) -> WorkspaceOverview:
    return dashboard.workspace_overview(core, workspace_id)
