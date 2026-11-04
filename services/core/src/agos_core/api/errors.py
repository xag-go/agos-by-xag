"""Settings → Errors: AGOS's own errors grouped into issues (actions/error_issues.py),
and the web app's broken pages reported into the same list."""

import asyncio
import logging
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from agos_core.actions import error_issues
from agos_core.actions.error_issues import ErrorIssues
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["errors"])

web_log = logging.getLogger("agos.web")

REPORTS_PER_MINUTE = 30
_reports: list[float] = []
_reports_lock = threading.Lock()
_FRAME = re.compile(r"at (?:async )?([\w$.<>]+) \(")
_WORKSPACE = re.compile(r"^/w/([^/?#]+)")


class StatusChange(Record):
    before: str


class WebError(Body):
    """A page of the web app that broke (its error boundary or the server's render)."""

    kind: Literal["page", "app", "server", "unhandled"] = "page"
    name: str = Field(default="Error", max_length=120)
    message: str = Field(default="", max_length=2000)
    stack: str = Field(default="", max_length=8000)
    digest: str = Field(default="", max_length=64)
    url: str = Field(default="", max_length=500)


@router.get("/errors")
async def list_errors(
    core: CoreDep,
    workspace: str | None = Query(default=None, max_length=100),
    source: Literal["core", "web", "hermes"] | None = None,
    status: Literal["open", "fixed", "all"] = "open",
) -> ErrorIssues:
    issues = await asyncio.to_thread(
        error_issues.listed, core.db, workspace_id=workspace, source=source, status=status
    )
    return ErrorIssues(issues=issues, version=error_issues.agos_version())


@router.post("/errors/{issue_id}/fixed")
async def mark_fixed(core: CoreDep, issue_id: int) -> StatusChange:
    before = await asyncio.to_thread(
        error_issues.set_status, core.db, issue_id, "fixed", workspace_id=None
    )
    return StatusChange(before=before)


@router.post("/errors/{issue_id}/open")
async def reopen(core: CoreDep, issue_id: int) -> StatusChange:
    before = await asyncio.to_thread(
        error_issues.set_status, core.db, issue_id, "open", workspace_id=None
    )
    return StatusChange(before=before)


def _room_for_report() -> bool:
    moment = time.monotonic()
    with _reports_lock:
        _reports[:] = [t for t in _reports if moment - t < 60]
        if len(_reports) >= REPORTS_PER_MINUTE:
            return False
        _reports.append(moment)
        return True


@router.post("/errors/report", status_code=204)
def report_web_error(body: WebError) -> None:
    """Counted on its issue like the core's own (secrets wiped by the System Log)."""
    if not _room_for_report():
        return
    path = body.url.split("?", 1)[0].split("#", 1)[0][:300]
    frames = _FRAME.findall(body.stack)[:3] or [body.kind]
    found = _WORKSPACE.match(path)
    web_log.error(
        "web %s error on %s: %s%s",
        body.kind,
        path or "?",
        body.message[:500] or body.name,
        f" (digest {body.digest})" if body.digest else "",
        extra={
            "agos_source": "web",
            "agos_where": f"web {body.kind}",
            "agos_type": body.name,
            "agos_trace": body.stack,
            "agos_frames": frames,
            "agos_route": path,
            "agos_request": body.digest,
            "agos_workspace": found.group(1) if found else None,
        },
    )
