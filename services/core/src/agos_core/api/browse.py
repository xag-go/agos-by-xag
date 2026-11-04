"""The folder picker: this machine's folders, names only."""

import asyncio

from fastapi import APIRouter, Query

from agos_core.actions import browse as actions
from agos_core.actions.browse import FolderListing
from agos_core.api.deps import CoreDep

router = APIRouter(tags=["folders"])


@router.get("/machine/folders")
async def list_folders(
    core: CoreDep, path: str | None = Query(default=None, max_length=1000)
) -> FolderListing:
    """Subfolders of `path` (default: the home folder), to pick one to add."""
    return await asyncio.to_thread(actions.list_folders, core, path)
