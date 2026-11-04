"""Folders on the Automations, Skills and Projects lists (actions/folders.py): the
owner's own grouping, AGOS-only (Hermes runs nothing differently)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import folders
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["folders"])

Kind = Literal["automation", "skill", "project"]


class Folder(Record):
    """One folder of one list; `items` = the ids of the automations, skills (library
    items) or projects (goals) in it."""

    id: int
    kind: Kind
    name: str
    items: list[int] = Field(default_factory=list)


class FolderBody(Body):
    kind: Kind
    name: str = Field(min_length=1, max_length=80)


class FolderRename(Body):
    name: str = Field(min_length=1, max_length=80)


class FolderMove(Body):
    kind: Kind
    item: int
    folder: int | None = None  # None = "No folder"


def _ws(core: CoreDep, workspace_id: str) -> str:
    require_workspace(core, workspace_id)
    return workspace_id


@router.get("/workspaces/{workspace_id}/list-folders")
def get_folders(core: CoreDep, workspace_id: str, kind: Kind) -> list[Folder]:
    ws = _ws(core, workspace_id)
    return [Folder.model_validate(f) for f in folders.listing(core, ws, kind)]


@router.post("/workspaces/{workspace_id}/list-folders", status_code=201)
def create_folder(core: CoreDep, workspace_id: str, body: FolderBody) -> Folder:
    ws = _ws(core, workspace_id)
    return Folder.model_validate(folders.create(core, ws, body.kind, body.name))


@router.put("/workspaces/{workspace_id}/list-folders/{folder_id}")
def rename_folder(core: CoreDep, workspace_id: str, folder_id: int, body: FolderRename) -> Folder:
    ws = _ws(core, workspace_id)
    return Folder.model_validate(folders.rename(core, ws, folder_id, body.name))


@router.delete("/workspaces/{workspace_id}/list-folders/{folder_id}", status_code=204)
def delete_folder(core: CoreDep, workspace_id: str, folder_id: int) -> None:
    """The folder goes; its items stay, back in "No folder"."""
    ws = _ws(core, workspace_id)
    folders.remove(core, ws, folder_id)


@router.post("/workspaces/{workspace_id}/list-folders/move")
def move_to_folder(core: CoreDep, workspace_id: str, body: FolderMove) -> list[Folder]:
    """Puts one item in a folder (or back in "No folder"); the list's folders after."""
    ws = _ws(core, workspace_id)
    folders.move(core, ws, body.kind, body.item, body.folder)
    return [Folder.model_validate(f) for f in folders.listing(core, ws, body.kind)]
