"""The Co-Founder's kinds for the rule files, owner rules and Brain methods (actions/
workspace_admin_ops.py binds them to the page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class DeleteDoc(CofounderFields):
    path: Any
    why: Any


DELETE_DOC: OperationSpec[DeleteDoc] = OperationSpec(
    name="delete_doc",
    input_model=DeleteDoc,
    audit_title="Delete the rule file “{path}”",
    gate="owner",
    agent_tool=None,
    web_action="deleteDoc",
    cofounder_domain=WORKSPACE,
    cofounder_fields="path, why",
    undo_after_yes=True,
)


class RestoreDocVersion(CofounderFields):
    version: Any
    why: Any


RESTORE_DOC_VERSION: OperationSpec[RestoreDocVersion] = OperationSpec(
    name="restore_doc_version",
    input_model=RestoreDocVersion,
    audit_title="Rule file back to version {version}",
    gate="undo",
    agent_tool=None,
    web_action="restoreVersion",
    cofounder_domain=WORKSPACE,
    cofounder_fields="version (from the doc's history), why",
)


class SetLatinOnly(CofounderFields):
    pass


SET_LATIN_ONLY: OperationSpec[SetLatinOnly] = OperationSpec(
    name="set_latin_only",
    input_model=SetLatinOnly,
    audit_title="Docs in Latin letters only: {on}",
    gate="undo",
    agent_tool=None,
    web_action="setLatinOnly",
    cofounder_domain=WORKSPACE,
    cofounder_fields="on (true/false)",
)


class EditOwnerRule(CofounderFields):
    rule: Any
    text: Any


EDIT_OWNER_RULE: OperationSpec[EditOwnerRule] = OperationSpec(
    name="edit_owner_rule",
    input_model=EditOwnerRule,
    audit_title="Change your rule: “{text}”",
    gate="owner",
    agent_tool=None,
    web_action="editOwnerRule",
    cofounder_domain=WORKSPACE,
    cofounder_fields="rule (its number), text",
    undo_after_yes=True,
)


class DeleteOwnerRule(CofounderFields):
    rule: Any


DELETE_OWNER_RULE: OperationSpec[DeleteOwnerRule] = OperationSpec(
    name="delete_owner_rule",
    input_model=DeleteOwnerRule,
    audit_title="Delete your rule {rule}",
    gate="owner",
    agent_tool=None,
    web_action="deleteOwnerRule",
    cofounder_domain=WORKSPACE,
    cofounder_fields="rule",
    undo_after_yes=True,
)


class EditMethod(CofounderFields):
    method: Any
    text: Any


EDIT_METHOD: OperationSpec[EditMethod] = OperationSpec(
    name="edit_method",
    input_model=EditMethod,
    audit_title="Change Brain method {method}",
    gate="owner",
    agent_tool=None,
    web_action="editMethod",
    cofounder_domain=WORKSPACE,
    cofounder_fields="method, text",
    undo_after_yes=True,
)


class DeleteMethod(CofounderFields):
    method: Any


DELETE_METHOD: OperationSpec[DeleteMethod] = OperationSpec(
    name="delete_method",
    input_model=DeleteMethod,
    audit_title="Delete Brain method {method}",
    gate="owner",
    agent_tool=None,
    web_action="deleteMethod",
    cofounder_domain=WORKSPACE,
    cofounder_fields="method",
    undo_after_yes=True,
)


class SetMethodHere(CofounderFields):
    method: Any


SET_METHOD_HERE: OperationSpec[SetMethodHere] = OperationSpec(
    name="set_method_here",
    input_model=SetMethodHere,
    audit_title="Brain method {method} here: {used}",
    gate="undo",
    agent_tool=None,
    web_action="setMethodHere",
    cofounder_domain=WORKSPACE,
    cofounder_fields="method, used (true/false: in this workspace)",
)


SPECS: tuple[OperationSpec[Any], ...] = (
    DELETE_DOC,
    RESTORE_DOC_VERSION,
    SET_LATIN_ONLY,
    EDIT_OWNER_RULE,
    DELETE_OWNER_RULE,
    EDIT_METHOD,
    DELETE_METHOD,
    SET_METHOD_HERE,
)
