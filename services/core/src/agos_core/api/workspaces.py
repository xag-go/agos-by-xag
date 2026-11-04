"""Workspaces, their settings, folders, archive and trash."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse

from agos_core.actions import engine as engine_actions
from agos_core.actions import workspace_ops
from agos_core.actions import workspaces as actions
from agos_core.actions.errors import ActionError
from agos_core.actions.services.workspace import icon
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import (
    Confirm,
    Created,
    FolderAccess,
    GatewayRestartOut,
    NewFolder,
    NewWorkspace,
    TrashedWorkspace,
    WorkspaceFolderOut,
    WorkspaceSettingsBody,
)
from agos_core.db.records import ActivityItem, BoardCounters, Workspace
from agos_core.ops import registry
from agos_core.ops.operation import OWNER
from agos_core.ops.specs.workspace import DeleteWorkspace

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces")
def list_workspaces(core: CoreDep, include_archived: bool = False) -> list[Workspace]:
    return actions.listed(core, include_archived=include_archived)


@router.post("/workspaces", status_code=201)
def create_workspace(
    core: CoreDep,
    body: NewWorkspace,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> Created:
    # With an Idempotency-Key, a retry or a double click gets the first answer.
    result = registry.run(
        core, workspace_ops.CREATE.spec.name, body, actor=OWNER, idempotency_key=idempotency_key
    )
    return Created(id=result["workspace_id"])


@router.get("/workspaces/{workspace_id}")
def get_workspace(core: CoreDep, workspace_id: str) -> Workspace:
    return actions.require_workspace(core, workspace_id)


@router.put("/workspaces/{workspace_id}")
def save_settings(core: CoreDep, workspace_id: str, body: WorkspaceSettingsBody) -> None:
    actions.save_settings(
        core,
        workspace_id,
        name=body.name.strip(),
        description=body.description.strip(),
        default_model=body.default_model,
        chat_access=body.chat_access,
    )


@router.post("/workspaces/{workspace_id}/archive")
def archive(core: CoreDep, workspace_id: str) -> None:
    actions.archive(core, workspace_id, True)


# ---- the icon on the workspace's tile (actions/services/workspace/icon.py) --------------------


async def _icon_bytes(request: Request) -> bytes:
    """The picture, sent as the request's body (its type is read from the bytes);
    stops reading past the limit instead of holding a large upload in memory."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > icon.MAX_BYTES:
        raise ActionError(icon.TOO_BIG, 413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > icon.MAX_BYTES:
            raise ActionError(icon.TOO_BIG, 413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.put("/workspaces/{workspace_id}/icon", status_code=204)
async def put_icon(core: CoreDep, workspace_id: str, request: Request) -> None:
    """A PNG, JPEG, WebP or SVG (without scripts) of up to 1 MB: 415 for another
    type, 413 above the size. The previous icon goes."""
    actions.require_workspace(core, workspace_id)
    data = await _icon_bytes(request)
    await asyncio.to_thread(icon.save, core, workspace_id, data)


@router.delete("/workspaces/{workspace_id}/icon", status_code=204)
def delete_icon(core: CoreDep, workspace_id: str) -> None:
    icon.remove(core, workspace_id)


@router.get("/workspaces/{workspace_id}/icon", response_class=FileResponse)
def get_icon(core: CoreDep, workspace_id: str) -> FileResponse:
    """The icon file. Cached for good: its URL carries the record's `icon` stamp,
    which changes with the file. An SVG is fenced so it can't run anything."""
    path, mime = icon.find(core, workspace_id)
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    }
    if mime == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return FileResponse(path, media_type=mime, headers=headers)


@router.post("/workspaces/{workspace_id}/unarchive")
def unarchive(core: CoreDep, workspace_id: str) -> None:
    actions.archive(core, workspace_id, False)


@router.post("/workspaces/{workspace_id}/delete")
def delete_workspace(core: CoreDep, workspace_id: str, body: Confirm) -> None:
    data = DeleteWorkspace(workspace_id=workspace_id, confirm=body.confirm)
    registry.run(core, workspace_ops.DELETE.spec.name, data, actor=OWNER, workspace_id=workspace_id)


@router.get("/workspaces-archived")
def archived(core: CoreDep) -> list[Workspace]:
    return actions.archived_list(core)


@router.get("/trash")
def trash(core: CoreDep) -> list[TrashedWorkspace]:
    return [TrashedWorkspace.model_validate(t) for t in actions.trashed(core)]


@router.post("/trash/{workspace_id}/restore")
def restore(core: CoreDep, workspace_id: str) -> None:
    actions.restore(core, workspace_id)


@router.delete("/trash/{workspace_id}")
def purge(core: CoreDep, workspace_id: str) -> None:
    actions.purge(core, workspace_id)


@router.get("/workspaces/{workspace_id}/folders")
async def folders(core: CoreDep, workspace_id: str) -> list[WorkspaceFolderOut]:
    actions.require_workspace(core, workspace_id)
    own = WorkspaceFolderOut(name=workspace_id, access="read-write", own=True, host_path=None)
    return [own] + [
        WorkspaceFolderOut(name=f.name, access=f.access, own=False, host_path=f.host_path)
        for f in await asyncio.to_thread(engine_actions.folders, core, workspace_id)
    ]


@router.post("/workspaces/{workspace_id}/folders", status_code=201)
def add_folder(core: CoreDep, workspace_id: str, body: NewFolder) -> Created:
    return Created(
        id=actions.add_folder(core, workspace_id, path=body.path.strip(), access=body.access)
    )


@router.put("/workspaces/{workspace_id}/folders/{name}")
def folder_access(core: CoreDep, workspace_id: str, name: str, body: FolderAccess) -> None:
    actions.set_folder_access(core, workspace_id, name, body.access)


@router.delete("/workspaces/{workspace_id}/folders/{name}")
def remove_folder(core: CoreDep, workspace_id: str, name: str) -> None:
    actions.remove_folder(core, workspace_id, name)


@router.get("/workspaces/{workspace_id}/gateway-restart")
def gateway_restart(core: CoreDep, workspace_id: str) -> GatewayRestartOut:
    """The gateway restart after a folder click (it runs after the click's answer):
    restarting, done, or failed with the reason (the agent is then stopped). The
    bot's lamp elsewhere stays Hermes's own verdict."""
    actions.require_workspace(core, workspace_id)
    state, reason = engine_actions.restart_state(workspace_id)
    return GatewayRestartOut(state=state, reason=reason)


@router.get("/workspaces/{workspace_id}/counters")
def counters(core: CoreDep, workspace_id: str) -> BoardCounters:
    from agos_core.actions import inbox, kanban_board

    actions.require_workspace(core, workspace_id)
    return BoardCounters(
        **kanban_board.counters(core, workspace_id), inbox=inbox.count(core, workspace_id)
    )


@router.get("/workspaces/{workspace_id}/activity")
async def activity(core: CoreDep, workspace_id: str) -> list[ActivityItem]:
    """The Dashboard's "Board activity": Hermes's own Kanban events of the workspace's
    board (task_events, read only), newest first. The owner's audit trail (AGOS's
    `activity` table) is the Log's, not this."""
    from datetime import UTC, datetime

    from agos_core.actions import kanban_board

    actions.require_workspace(core, workspace_id)
    found = await asyncio.to_thread(kanban_board.events, core, workspace_id, 20)
    return [
        ActivityItem(
            id=e["id"],
            at=datetime.fromtimestamp(e["at"], UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            text=f"{kanban_board.EVENTS[e['kind']][1]}: “{e['title'] or e['card']}”",
            task_id=e["card"],
        )
        for e in found
    ]
