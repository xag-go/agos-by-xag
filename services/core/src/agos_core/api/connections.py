"""Settings → Connections (Step 59): this workspace's tools over MCP for an outside
assistant, and its voice note history."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from agos_core.actions import mcp_tools
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.db.records import Record

router = APIRouter(tags=["connections"])


class McpToken(Record):
    token: str | None = None
    made_at: str | None = None
    tools: list[str]


def _token_view(found: dict[str, Any]) -> McpToken:
    return McpToken(token=found["token"], made_at=found["madeAt"], tools=list(mcp_tools.TOOLS))


@router.get("/workspaces/{workspace_id}/mcp-token")
def get_mcp_token(core: CoreDep, workspace_id: str) -> McpToken:
    require_workspace(core, workspace_id)
    return _token_view(mcp_tools.token(core, workspace_id))


@router.post("/workspaces/{workspace_id}/mcp-token")
def new_mcp_token(core: CoreDep, workspace_id: str) -> McpToken:
    """A new token; the old one stops working at once."""
    require_workspace(core, workspace_id)
    return _token_view(mcp_tools.new_token(core, workspace_id))


@router.delete("/workspaces/{workspace_id}/mcp-token", status_code=204)
def remove_mcp_token(core: CoreDep, workspace_id: str) -> None:
    require_workspace(core, workspace_id)
    mcp_tools.remove_token(core, workspace_id)


@router.post("/workspaces/{workspace_id}/mcp-serve", include_in_schema=False)
async def mcp_call(
    core: CoreDep,
    workspace_id: str,
    request: Request,
    x_agos_mcp_token: Annotated[str | None, Header()] = None,
) -> Response:
    """MCP (Streamable HTTP, JSON answers) for this workspace, with ITS token only.
    The web passes the assistant's Bearer token on as x-agos-mcp-token."""
    require_workspace(core, workspace_id)
    given = (x_agos_mcp_token or "").strip()
    if not given or not mcp_tools.allowed(core, workspace_id, given):
        raise HTTPException(status_code=401, detail="Not allowed")
    try:
        message = await request.json()
    except ValueError:
        return JSONResponse(mcp_tools.handle(core, workspace_id, None), status_code=400)
    if isinstance(message, list):
        answers = [
            a
            for a in [
                await asyncio.to_thread(mcp_tools.handle, core, workspace_id, m)
                for m in message[:20]
            ]
            if a is not None
        ]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await asyncio.to_thread(mcp_tools.handle, core, workspace_id, message)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)
