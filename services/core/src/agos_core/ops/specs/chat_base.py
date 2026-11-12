"""The Co-Founder's base kinds: the ones its always-on prompt teaches itself (automations,
skills, agents, MCP servers, hires, renames, rule files, owner rules, Brain methods). They run
through the action cards' own pipeline (actions/services/cofounder/dispatch.py, bound in
actions/services/cofounder/base_ops.py).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import CHAT
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class CreateAutomation(CofounderFields):
    name: Any
    instructions: Any


CREATE_AUTOMATION: OperationSpec[CreateAutomation] = OperationSpec(
    name="create_automation",
    input_model=CreateAutomation,
    audit_title="Create automation “{name}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class UpdateAutomation(CofounderFields):
    automation: Any


UPDATE_AUTOMATION: OperationSpec[UpdateAutomation] = OperationSpec(
    name="update_automation",
    input_model=UpdateAutomation,
    audit_title="Change automation “{automation}”",
    gate="undo",
    agent_tool=None,
    web_action="saveAutomation",
    extra_web_actions=("saveHook",),
    cofounder_domain=CHAT,
)


class PauseAutomation(CofounderFields):
    automation: Any


PAUSE_AUTOMATION: OperationSpec[PauseAutomation] = OperationSpec(
    name="pause_automation",
    input_model=PauseAutomation,
    audit_title="Pause automation “{automation}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="toggleAutomation",
    cofounder_domain=CHAT,
)


class ResumeAutomation(CofounderFields):
    automation: Any


RESUME_AUTOMATION: OperationSpec[ResumeAutomation] = OperationSpec(
    name="resume_automation",
    input_model=ResumeAutomation,
    audit_title="Turn on automation “{automation}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class RunAutomation(CofounderFields):
    automation: Any


RUN_AUTOMATION: OperationSpec[RunAutomation] = OperationSpec(
    name="run_automation",
    input_model=RunAutomation,
    audit_title="Run automation “{automation}” now",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="runAutomationNow",
    cofounder_domain=CHAT,
)


class DeleteAutomation(CofounderFields):
    automation: Any


DELETE_AUTOMATION: OperationSpec[DeleteAutomation] = OperationSpec(
    name="delete_automation",
    input_model=DeleteAutomation,
    audit_title="Delete automation “{automation}”",
    gate="undo",
    agent_tool=None,
    web_action="deleteAutomation",
    cofounder_domain=CHAT,
)


class CreateSkill(CofounderFields):
    name: Any
    description: Any
    instructions: Any


CREATE_SKILL: OperationSpec[CreateSkill] = OperationSpec(
    name="create_skill",
    input_model=CreateSkill,
    audit_title="Create skill “{name}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class CreateAgent(CofounderFields):
    name: Any


CREATE_AGENT: OperationSpec[CreateAgent] = OperationSpec(
    name="create_agent",
    input_model=CreateAgent,
    audit_title="Create agent “{name}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class HireAgent(CofounderFields):
    name: Any
    title: Any
    role: Any


HIRE_AGENT: OperationSpec[HireAgent] = OperationSpec(
    name="hire_agent",
    input_model=HireAgent,
    audit_title="Hire “{title}” (@{name})",
    gate="undo",
    agent_tool=None,
    web_action="askToHire",
    cofounder_domain=CHAT,
)


class CreateMcp(CofounderFields):
    name: Any
    url: Any


CREATE_MCP: OperationSpec[CreateMcp] = OperationSpec(
    name="create_mcp",
    input_model=CreateMcp,
    audit_title="Add MCP server “{name}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class UpdateSkill(CofounderFields):
    name: Any


UPDATE_SKILL: OperationSpec[UpdateSkill] = OperationSpec(
    name="update_skill",
    input_model=UpdateSkill,
    audit_title="Update skill “{name}”",
    gate="undo",
    agent_tool=None,
    web_action="saveLibraryItem",
    cofounder_domain=CHAT,
)


class UpdateAgent(CofounderFields):
    name: Any


UPDATE_AGENT: OperationSpec[UpdateAgent] = OperationSpec(
    name="update_agent",
    input_model=UpdateAgent,
    audit_title="Update agent “{name}”",
    gate="undo",
    agent_tool=None,
    web_action="setReportsTo",
    cofounder_domain=CHAT,
)


class UpdateMcp(CofounderFields):
    name: Any


UPDATE_MCP: OperationSpec[UpdateMcp] = OperationSpec(
    name="update_mcp",
    input_model=UpdateMcp,
    audit_title="Update MCP server “{name}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class Rename(CofounderFields):
    kind: Any
    name: Any
    title: Any


RENAME: OperationSpec[Rename] = OperationSpec(
    name="rename",
    input_model=Rename,
    audit_title="Rename {kind} “{name}” to “{title}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    cofounder_domain=CHAT,
)


class UpdateDoc(CofounderFields):
    path: Any
    why: Any


UPDATE_DOC: OperationSpec[UpdateDoc] = OperationSpec(
    name="update_doc",
    input_model=UpdateDoc,
    audit_title="Change the rule file “{path}”",
    gate="undo",
    agent_tool=None,
    web_action="saveDoc",
    extra_web_actions=("newDoc",),
    cofounder_domain=CHAT,
)


class UpdateFile(CofounderFields):
    path: Any
    why: Any


UPDATE_FILE: OperationSpec[UpdateFile] = OperationSpec(
    name="update_file",
    input_model=UpdateFile,
    audit_title="Change the file “{path}”",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class AddOwnerRule(CofounderFields):
    text: Any


ADD_OWNER_RULE: OperationSpec[AddOwnerRule] = OperationSpec(
    name="add_owner_rule",
    input_model=AddOwnerRule,
    audit_title="Rule for all your workspaces: “{text}”",
    gate="owner",
    agent_tool=None,
    web_action="addOwnerRule",
    cofounder_domain=CHAT,
    undo_after_yes=True,
)


class AddMethod(CofounderFields):
    text: Any


ADD_METHOD: OperationSpec[AddMethod] = OperationSpec(
    name="add_method",
    input_model=AddMethod,
    audit_title="Way of working for every workspace (Brain): “{text}”",
    gate="owner",
    agent_tool=None,
    web_action="addMethod",
    cofounder_domain=CHAT,
    undo_after_yes=True,
)


SPECS: tuple[OperationSpec[Any], ...] = (
    CREATE_AUTOMATION,
    UPDATE_AUTOMATION,
    PAUSE_AUTOMATION,
    RESUME_AUTOMATION,
    RUN_AUTOMATION,
    DELETE_AUTOMATION,
    CREATE_SKILL,
    CREATE_AGENT,
    HIRE_AGENT,
    CREATE_MCP,
    UPDATE_SKILL,
    UPDATE_AGENT,
    UPDATE_MCP,
    RENAME,
    UPDATE_DOC,
    UPDATE_FILE,
    ADD_OWNER_RULE,
    ADD_METHOD,
)
