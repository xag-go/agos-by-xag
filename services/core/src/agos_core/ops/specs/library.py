"""The Library service's Co-Founder kinds: skills (delete, duplicate, update from
source, auto-update, versions), Skill Studio tests, skill growth settings, installs,
MCP sign-in, the GitHub token (actions/library_ops.py binds them to the Co-Founder's
page actions).

Each kind was a hand-written row of engine/cofounder_parity; declared here once, it
becomes the Co-Founder's kind, its read-vs-act row and its do / undo through the
registry (permission, workspace scope, audit row). Inputs keep the Co-Founder's own
loose fields (`CofounderFields`: its page action reads them as before).

Owns: these declarations and their input models. Must not: hold the steps (the
service's own page actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import SKILLS
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = [
    "ADD_SKILL_TEST_INPUT",
    "APPLY_SKILL_UPDATE",
    "DELETE_LIBRARY_ITEM",
    "DELETE_SKILL_TEST_INPUT",
    "DUPLICATE_SKILL",
    "GRADE_SKILL_TEST",
    "INSTALL_SKILL",
    "MCP_SIGN_IN",
    "MCP_SIGN_OUT",
    "REMOVE_GITHUB_TOKEN",
    "RERUN_SKILL_TEST",
    "RESTORE_SKILL_VERSION",
    "RUN_SKILL_TEST",
    "SAVE_SKILL_TEST_SETTINGS",
    "SET_SKILL_AUTO_UPDATE",
    "SET_SKILL_REQUEST_LIMIT",
    "SET_SKILL_REVIEW",
    "SPECS",
    "UPDATE_SKILL_TEST_INPUT",
    "AddSkillTestInput",
    "ApplySkillUpdate",
    "DeleteLibraryItem",
    "DeleteSkillTestInput",
    "DuplicateSkill",
    "GradeSkillTest",
    "InstallSkill",
    "McpSignIn",
    "McpSignOut",
    "RemoveGithubToken",
    "RerunSkillTest",
    "RestoreSkillVersion",
    "RunSkillTest",
    "SaveSkillTestSettings",
    "SetSkillAutoUpdate",
    "SetSkillRequestLimit",
    "SetSkillReview",
    "UpdateSkillTestInput",
]


class DeleteLibraryItem(CofounderFields):
    kind: Any
    name: Any


DELETE_LIBRARY_ITEM: OperationSpec[DeleteLibraryItem] = OperationSpec(
    name="delete_library_item",
    input_model=DeleteLibraryItem,
    audit_title="Delete {kind} “{name}”",
    gate="owner",
    agent_tool=None,
    web_action="deleteLibraryItem",
    cofounder_domain=SKILLS,
    cofounder_fields="kind (skill | agent | mcp), name (its ID or title)",
)


class DuplicateSkill(CofounderFields):
    name: Any
    new_name: Any


DUPLICATE_SKILL: OperationSpec[DuplicateSkill] = OperationSpec(
    name="duplicate_skill",
    input_model=DuplicateSkill,
    audit_title="Copy skill “{name}” as “{new_name}”",
    gate="undo",
    agent_tool=None,
    web_action="duplicateLibraryItem",
    cofounder_domain=SKILLS,
    cofounder_fields="name, new_name",
)


class ApplySkillUpdate(CofounderFields):
    name: Any


APPLY_SKILL_UPDATE: OperationSpec[ApplySkillUpdate] = OperationSpec(
    name="apply_skill_update",
    input_model=ApplySkillUpdate,
    audit_title="Update skill “{name}” from its source",
    gate="owner",
    agent_tool=None,
    web_action="applySkillUpdate",
    cofounder_domain=SKILLS,
    cofounder_fields="name",
    undo_after_yes=True,
)


class SetSkillAutoUpdate(CofounderFields):
    name: Any
    on: Any = None


SET_SKILL_AUTO_UPDATE: OperationSpec[SetSkillAutoUpdate] = OperationSpec(
    name="set_skill_auto_update",
    input_model=SetSkillAutoUpdate,
    audit_title="Skill “{name}” follows its source: {on}",
    gate="undo",
    agent_tool=None,
    web_action="setSkillAutoUpdate",
    cofounder_domain=SKILLS,
    cofounder_fields="name, on (true/false)",
)


class SaveSkillTestSettings(CofounderFields):
    name: Any
    template: Any = None
    checklist: Any = None


SAVE_SKILL_TEST_SETTINGS: OperationSpec[SaveSkillTestSettings] = OperationSpec(
    name="save_skill_test_settings",
    input_model=SaveSkillTestSettings,
    audit_title="Test settings of skill “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="saveSkillTestSettings",
    cofounder_domain=SKILLS,
    cofounder_fields="name, template (the test prompt; {skill} and {input} are filled in), checklist",
)


class AddSkillTestInput(CofounderFields):
    name: Any
    input_name: Any
    text: Any
    expected: Any = None


ADD_SKILL_TEST_INPUT: OperationSpec[AddSkillTestInput] = OperationSpec(
    name="add_skill_test_input",
    input_model=AddSkillTestInput,
    audit_title="Test input “{input_name}” for skill “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="addSkillTestInput",
    cofounder_domain=SKILLS,
    cofounder_fields="name, input_name, text, expected",
)


class UpdateSkillTestInput(CofounderFields):
    name: Any
    input: Any
    input_name: Any = None
    text: Any = None
    expected: Any = None


UPDATE_SKILL_TEST_INPUT: OperationSpec[UpdateSkillTestInput] = OperationSpec(
    name="update_skill_test_input",
    input_model=UpdateSkillTestInput,
    audit_title="Change test input {input} of skill “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="updateSkillTestInput",
    cofounder_domain=SKILLS,
    cofounder_fields="name, input (its number), input_name, text, expected",
)


class DeleteSkillTestInput(CofounderFields):
    name: Any
    input: Any


DELETE_SKILL_TEST_INPUT: OperationSpec[DeleteSkillTestInput] = OperationSpec(
    name="delete_skill_test_input",
    input_model=DeleteSkillTestInput,
    audit_title="Remove test input {input} of skill “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="deleteSkillTestInput",
    cofounder_domain=SKILLS,
    cofounder_fields="name, input (its number)",
)


class RunSkillTest(CofounderFields):
    name: Any
    input: Any
    member: Any = None


RUN_SKILL_TEST: OperationSpec[RunSkillTest] = OperationSpec(
    name="run_skill_test",
    input_model=RunSkillTest,
    audit_title="Test skill “{name}” on input {input}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="runSkillTest",
    cofounder_domain=SKILLS,
    cofounder_fields="name, input (its number), member (who runs it; leave out = you)",
)


class RerunSkillTest(CofounderFields):
    name: Any
    run: Any


RERUN_SKILL_TEST: OperationSpec[RerunSkillTest] = OperationSpec(
    name="rerun_skill_test",
    input_model=RerunSkillTest,
    audit_title="Run test {run} of skill “{name}” again",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="rerunSkillTest",
    cofounder_domain=SKILLS,
    cofounder_fields="name, run",
)


class GradeSkillTest(CofounderFields):
    name: Any
    run: Any


GRADE_SKILL_TEST: OperationSpec[GradeSkillTest] = OperationSpec(
    name="grade_skill_test",
    input_model=GradeSkillTest,
    audit_title="Grade test {run} of skill “{name}”",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="gradeSkillTest",
    cofounder_domain=SKILLS,
    cofounder_fields="name, run",
)


class RestoreSkillVersion(CofounderFields):
    name: Any
    version: Any


RESTORE_SKILL_VERSION: OperationSpec[RestoreSkillVersion] = OperationSpec(
    name="restore_skill_version",
    input_model=RestoreSkillVersion,
    audit_title="Skill “{name}” back to v{version}",
    gate="undo",
    agent_tool=None,
    web_action="restoreSkillVersion",
    cofounder_domain=SKILLS,
    cofounder_fields="name, version (from its Versions)",
)


class SetSkillRequestLimit(CofounderFields):
    limit: Any


SET_SKILL_REQUEST_LIMIT: OperationSpec[SetSkillRequestLimit] = OperationSpec(
    name="set_skill_request_limit",
    input_model=SetSkillRequestLimit,
    audit_title="New-skill requests per day: {limit}",
    gate="undo",
    agent_tool=None,
    web_action="saveSkillRequestLimit",
    cofounder_domain=SKILLS,
    cofounder_fields="limit (a number, 0 = none)",
)


class SetSkillReview(CofounderFields):
    on: Any = None
    time: Any = None
    day: Any = None


SET_SKILL_REVIEW: OperationSpec[SetSkillReview] = OperationSpec(
    name="set_skill_review",
    input_model=SetSkillReview,
    audit_title="Weekly skill review: {on} {time}",
    gate="undo",
    agent_tool=None,
    web_action="saveSkillReview",
    cofounder_domain=SKILLS,
    cofounder_fields="on (true/false), time (HH:MM, the owner's timezone), day (0 = Monday ... 6)",
)


class InstallSkill(CofounderFields):
    identifier: Any
    force: Any = None


INSTALL_SKILL: OperationSpec[InstallSkill] = OperationSpec(
    name="install_skill",
    input_model=InstallSkill,
    audit_title="Install skill {identifier} from the web",
    gate="owner",
    agent_tool=None,
    web_action="installSkill",
    cofounder_domain=SKILLS,
    cofounder_fields="identifier (from the Library's web search), force (true only after he read the scan)",
)


class McpSignIn(CofounderFields):
    name: Any


MCP_SIGN_IN: OperationSpec[McpSignIn] = OperationSpec(
    name="mcp_sign_in",
    input_model=McpSignIn,
    audit_title="Sign-in link for MCP server “{name}”",
    gate="once",
    agent_tool=None,
    web_action="startMcpSignIn",
    cofounder_domain=SKILLS,
    cofounder_fields="name: you get the link to send the owner",
)


class McpSignOut(CofounderFields):
    name: Any


MCP_SIGN_OUT: OperationSpec[McpSignOut] = OperationSpec(
    name="mcp_sign_out",
    input_model=McpSignOut,
    audit_title="Sign out of MCP server “{name}”",
    gate="owner",
    agent_tool=None,
    web_action="mcpSignOut",
    cofounder_domain=SKILLS,
    cofounder_fields="name",
)


class RemoveGithubToken(CofounderFields):
    pass


REMOVE_GITHUB_TOKEN: OperationSpec[RemoveGithubToken] = OperationSpec(
    name="remove_github_token",
    input_model=RemoveGithubToken,
    audit_title="Remove the GitHub token (every workspace)",
    gate="owner",
    agent_tool=None,
    web_action="removeGithubToken",
    cofounder_domain=SKILLS,
    cofounder_fields="(no fields)",
)

SPECS: tuple[OperationSpec[Any], ...] = (
    DELETE_LIBRARY_ITEM,
    DUPLICATE_SKILL,
    APPLY_SKILL_UPDATE,
    SET_SKILL_AUTO_UPDATE,
    SAVE_SKILL_TEST_SETTINGS,
    ADD_SKILL_TEST_INPUT,
    UPDATE_SKILL_TEST_INPUT,
    DELETE_SKILL_TEST_INPUT,
    RUN_SKILL_TEST,
    RERUN_SKILL_TEST,
    GRADE_SKILL_TEST,
    RESTORE_SKILL_VERSION,
    SET_SKILL_REQUEST_LIMIT,
    SET_SKILL_REVIEW,
    INSTALL_SKILL,
    MCP_SIGN_IN,
    MCP_SIGN_OUT,
    REMOVE_GITHUB_TOKEN,
)
