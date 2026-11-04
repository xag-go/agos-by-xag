"""Workspace → Settings → Keys (actions/tool_keys.py). No answer ever holds a key."""

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import tool_keys as actions
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body

router = APIRouter(tags=["tool-keys"])


class ToolKey(Body):
    app: str  # the app's name as the owner typed it
    name: str  # the variable Hermes holds it under ($NAME in the tools)
    saved: bool  # the root's .env has it
    ends_with: str  # its last 4 characters ("" for a short value)
    saved_at: str | None = None
    tested_at: str | None = None
    test_ok: bool | None = None
    testable: bool = False  # AGOS can also try it with the app itself


class ToolKeys(Body):
    keys: list[ToolKey]
    saved_name: str | None = None  # the name the last save used


class ToolKeyName(Body):
    name: str
    url: str = ""  # where to get a key (Hermes's catalog)
    exists: bool = False  # a key of that name is saved already (Save replaces it)


class ToolKeyTest(Body):
    ok: bool
    message: str


class AppBody(Body):
    app: str = Field(max_length=200)


class NewToolKey(Body):
    app: str = Field(max_length=200)
    key: str  # unconstrained on purpose: a validation error would echo it
    name: str | None = Field(default=None, max_length=64)  # a fixed name (moving old keys)


class KeyBody(Body):
    key: str


@router.get("/workspaces/{workspace_id}/tool-keys")
async def list_tool_keys(core: CoreDep, workspace_id: str) -> ToolKeys:
    return ToolKeys.model_validate(await asyncio.to_thread(actions.read, core, workspace_id))


@router.post("/workspaces/{workspace_id}/tool-keys/name")
async def tool_key_name(core: CoreDep, workspace_id: str, body: AppBody) -> ToolKeyName:
    """The variable a key for this app would be saved under (nothing is written)."""
    found = await asyncio.to_thread(actions.preview, core, workspace_id, body.app)
    return ToolKeyName.model_validate(found)


@router.post("/workspaces/{workspace_id}/tool-keys")
async def add_tool_key(core: CoreDep, workspace_id: str, body: NewToolKey) -> ToolKeys:
    found = await asyncio.to_thread(actions.save, core, workspace_id, body.app, body.key, body.name)
    return ToolKeys.model_validate(found)


@router.put("/workspaces/{workspace_id}/tool-keys/{name}")
async def replace_tool_key(core: CoreDep, workspace_id: str, name: str, body: KeyBody) -> ToolKeys:
    found = await asyncio.to_thread(actions.replace, core, workspace_id, name, body.key)
    return ToolKeys.model_validate(found)


@router.delete("/workspaces/{workspace_id}/tool-keys/{name}")
async def remove_tool_key(core: CoreDep, workspace_id: str, name: str) -> ToolKeys:
    return ToolKeys.model_validate(
        await asyncio.to_thread(actions.remove, core, workspace_id, name)
    )


@router.post("/workspaces/{workspace_id}/tool-keys/{name}/test")
async def test_tool_key(core: CoreDep, workspace_id: str, name: str) -> ToolKeyTest:
    return ToolKeyTest.model_validate(
        await asyncio.to_thread(actions.test, core, workspace_id, name)
    )
