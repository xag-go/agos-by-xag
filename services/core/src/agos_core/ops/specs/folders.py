"""The Co-Founder's folder kinds for the Automations, Skills and Projects lists (actions/
workspace_admin_ops.py binds them to the page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class CreateFolder(CofounderFields):
    kind: Any
    name: Any


CREATE_FOLDER: OperationSpec[CreateFolder] = OperationSpec(
    name="create_folder",
    input_model=CreateFolder,
    audit_title="New {kind} folder “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="createFolder",
    cofounder_domain=WORKSPACE,
    cofounder_fields="kind (automation | skill | project), name",
)


class RenameFolder(CofounderFields):
    kind: Any
    folder: Any
    new: Any


RENAME_FOLDER: OperationSpec[RenameFolder] = OperationSpec(
    name="rename_folder",
    input_model=RenameFolder,
    audit_title="Rename {kind} folder “{folder}” → “{new}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="renameFolder",
    cofounder_domain=WORKSPACE,
    cofounder_fields="kind, folder (its name or number), new",
)


class DeleteFolder(CofounderFields):
    kind: Any
    folder: Any


DELETE_FOLDER: OperationSpec[DeleteFolder] = OperationSpec(
    name="delete_folder",
    input_model=DeleteFolder,
    audit_title="Delete {kind} folder “{folder}” (its items go back to No folder)",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="deleteFolder",
    cofounder_domain=WORKSPACE,
    cofounder_fields="kind, folder: only the folder goes, never what is in it",
)


class MoveToFolder(CofounderFields):
    kind: Any
    item: Any


MOVE_TO_FOLDER: OperationSpec[MoveToFolder] = OperationSpec(
    name="move_to_folder",
    input_model=MoveToFolder,
    audit_title="Move {kind} “{item}” to {folder}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="moveToFolder",
    cofounder_domain=WORKSPACE,
    cofounder_fields='kind, item (its name, title or number), folder (its name; "" = No folder)',
)


SPECS: tuple[OperationSpec[Any], ...] = (
    CREATE_FOLDER,
    RENAME_FOLDER,
    DELETE_FOLDER,
    MOVE_TO_FOLDER,
)
