"""Documentation of a workspace: the team's rules (see actions/docs.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from agos_core.actions import docs as actions
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["docs"])


class DocSave(BaseModel):
    text: str
    why: str = Field(min_length=1)
    base_hash: str | None = None


class DocNew(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    text: str = ""
    why: str = Field(min_length=1)


class Why(BaseModel):
    why: str = ""


class DocSettings(BaseModel):
    latin_only: bool


@router.get("/workspaces/{workspace_id}/docs")
def list_docs(core: CoreDep, workspace_id: str) -> dict[str, Any]:
    return actions.page(core, workspace_id)


@router.get("/workspaces/{workspace_id}/docs/file")
def get_doc(core: CoreDep, workspace_id: str, path: str = Query(min_length=1)) -> dict[str, Any]:
    return actions.get_doc(core, workspace_id, path)


@router.put("/workspaces/{workspace_id}/docs/file")
async def save_doc(
    core: CoreDep, workspace_id: str, body: DocSave, path: str = Query(min_length=1)
) -> dict[str, Any]:
    return actions.save_doc(core, workspace_id, path, body.text, body.why, base_hash=body.base_hash)


@router.post("/workspaces/{workspace_id}/docs/file", status_code=201)
async def new_doc(core: CoreDep, workspace_id: str, body: DocNew) -> dict[str, Any]:
    text = body.text or f"# {body.path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}\n\n## 1. \n"
    return actions.save_doc(core, workspace_id, body.path, text, body.why)


@router.post("/workspaces/{workspace_id}/docs/file/delete", status_code=204)
async def delete_doc(
    core: CoreDep, workspace_id: str, body: Why, path: str = Query(min_length=1)
) -> None:
    actions.delete_doc(core, workspace_id, path, body.why or "no longer needed")


@router.get("/workspaces/{workspace_id}/docs/versions/{version_id}")
def version(core: CoreDep, workspace_id: str, version_id: int) -> dict[str, Any]:
    return actions.version_diff(core, workspace_id, version_id)


@router.post("/workspaces/{workspace_id}/docs/versions/{version_id}/restore")
async def restore(core: CoreDep, workspace_id: str, version_id: int, body: Why) -> dict[str, Any]:
    return actions.restore(core, workspace_id, version_id, body.why)


@router.get("/workspaces/{workspace_id}/docs/check")
def check(core: CoreDep, workspace_id: str) -> list[dict[str, str]]:
    return actions.check(core, workspace_id)


@router.put("/workspaces/{workspace_id}/docs/settings", status_code=204)
async def settings(core: CoreDep, workspace_id: str, body: DocSettings) -> None:
    actions.set_latin_only(core, workspace_id, body.latin_only)


@router.get("/workspaces/{workspace_id}/agents/versions")
def agent_versions(
    core: CoreDep, workspace_id: str, name: str | None = None
) -> list[dict[str, Any]]:
    return actions.agent_versions(core, workspace_id, name)


@router.post("/workspaces/{workspace_id}/agents/versions/{version_id}/restore")
def restore_agent(core: CoreDep, workspace_id: str, version_id: int) -> dict[str, int]:
    return {"id": actions.restore_agent(core, workspace_id, version_id)}
