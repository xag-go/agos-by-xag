"""The Workspace service's operations (actions/workspace_ops.py binds them).

Creating and deleting a whole workspace is the owner's alone (owner rule: the
Co-Founder never creates, archives, deletes or restores a workspace), so both are
owner-only: no Co-Founder kind, no agent tool. `NewWorkspace` is the create's input
and the API's request body (api/schemas.py re-exports it).

Owns: these declarations and their input models. Must not: hold the steps (the
service's saga in actions/workspaces.py does).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agos_core.domain.models import ModelSelection
from agos_core.ops.spec import OperationSpec

__all__ = [
    "CREATE_WORKSPACE",
    "DELETE_WORKSPACE",
    "SPECS",
    "WHOLE_WORKSPACE",
    "DeleteWorkspace",
    "NewWorkspace",
]

WHOLE_WORKSPACE = "creating, archiving, deleting or restoring a whole workspace: his alone"


class NewWorkspace(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(default="")
    default_model: ModelSelection


class DeleteWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    confirm: str = Field(max_length=100)


CREATE_WORKSPACE: OperationSpec[NewWorkspace] = OperationSpec(
    name="create_workspace",
    input_model=NewWorkspace,
    audit_title="Create the workspace {name}",
    gate="once",
    web_action="createWorkspace",
    owner_only=WHOLE_WORKSPACE,
    idempotent=True,
)

# To the trash; its undo is the trash's own restore.
DELETE_WORKSPACE: OperationSpec[DeleteWorkspace] = OperationSpec(
    name="delete_workspace",
    input_model=DeleteWorkspace,
    audit_title="Delete the workspace {workspace_id}",
    gate="undo",
    web_action="deleteWorkspace",
    owner_only=WHOLE_WORKSPACE,
)

SPECS: tuple[OperationSpec[Any], ...] = (CREATE_WORKSPACE, DELETE_WORKSPACE)
