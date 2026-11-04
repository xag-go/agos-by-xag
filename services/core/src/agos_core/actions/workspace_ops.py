"""The Workspace service's operations, bound to its code: creating a workspace and
deleting it to the trash (declared in ops/specs/workspace.py; owner-only). Every
caller runs them through the registry (`ops.registry.run`), which validates the
input, checks the caller, keeps the idempotency key and writes the audit row.

Owns: the binding (input model -> the service's function, its result, its undo).
Must not: hold the steps themselves (actions/workspaces.py's sagas do).
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import workspaces
from agos_core.context import Core
from agos_core.ops import registry
from agos_core.ops.operation import OpContext
from agos_core.ops.specs.workspace import (
    CREATE_WORKSPACE,
    DELETE_WORKSPACE,
    DeleteWorkspace,
    NewWorkspace,
)

__all__ = ["CREATE", "DELETE"]


def _create(core: Core, ctx: OpContext, data: NewWorkspace) -> dict[str, Any]:
    workspace_id = workspaces.create_workspace(
        core,
        name=data.name.strip(),
        description=data.description.strip(),
        default_model=data.default_model,
    )
    return {"workspace_id": workspace_id}


def _delete(core: Core, ctx: OpContext, data: DeleteWorkspace) -> dict[str, Any]:
    workspaces.delete_to_trash(core, data.workspace_id, data.confirm)
    return {"workspace_id": data.workspace_id}


def _restore(core: Core, ctx: OpContext, result: dict[str, Any]) -> None:
    """Undo of a delete: the trash's own restore."""
    workspaces.restore(core, str(result["workspace_id"]))


CREATE = registry.bind(CREATE_WORKSPACE, do=_create)
DELETE = registry.bind(DELETE_WORKSPACE, do=_delete, undo=_restore)
