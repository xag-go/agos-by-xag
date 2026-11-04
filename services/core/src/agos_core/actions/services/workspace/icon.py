"""A workspace's icon (the picture on its tile in the rail): checked, saved, removed
and found for the API, each for a workspace that exists.

Owns those steps and the owner-facing refusals. Must not: read or write the file
itself (storage/workspace_icon.py does) or pick HTTP statuses beyond the ones the
refusal carries (ActionError).
"""

from __future__ import annotations

from pathlib import Path

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.storage import workspace_icon

__all__ = ["MAX_BYTES", "TOO_BIG", "find", "remove", "save"]

MAX_BYTES = workspace_icon.MAX_BYTES
TOO_BIG = "The icon can be up to 1 MB."


def save(core: Core, workspace_id: str, data: bytes) -> None:
    """A PNG, JPEG, WebP or SVG (without scripts) of up to 1 MB: 415 for another
    type, 413 above the size. The previous icon goes."""
    require_workspace(core, workspace_id)
    try:
        workspace_icon.save(core.layout, workspace_id, data)
    except workspace_icon.IconError as error:
        raise ActionError(error.message, error.status) from error


def remove(core: Core, workspace_id: str) -> None:
    require_workspace(core, workspace_id)
    workspace_icon.remove(core.layout, workspace_id)


def find(core: Core, workspace_id: str) -> tuple[Path, str]:
    """(the icon's file, its type)."""
    require_workspace(core, workspace_id)
    found = workspace_icon.find(core.layout, workspace_id)
    if found is None:
        raise NotFoundError("This workspace's icon")
    path, mime, _stamp = found
    return path, mime
