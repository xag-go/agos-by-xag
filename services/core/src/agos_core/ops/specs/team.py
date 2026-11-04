"""The Team and Hire services' Co-Founder kinds: group chats, hire kits and Readiness,
a kit for a member hired without one, the office look, a ready-made team installed,
an agent's versions (actions/team_ops.py binds them to the Co-Founder's page
actions).

Each kind was a hand-written row of engine/cofounder_parity; declared here once, it
becomes the Co-Founder's kind, its read-vs-act row and its do / undo through the
registry (permission, workspace scope, audit row). Inputs keep the Co-Founder's own
loose fields (`CofounderFields`: its page action reads them as before).

Owns: these declarations and their input models. Must not: hold the steps (the
service's own page actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import TEAM, WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = [
    "CHOOSE_READINESS",
    "CREATE_GROUP",
    "INSTALL_TEMPLATE",
    "RESTORE_AGENT_REVISION",
    "RESTORE_AGENT_VERSION",
    "SAVE_KIT",
    "SET_GROUP_MEMBERS",
    "SET_OFFICE_LOOK",
    "SPECS",
    "SUGGEST_MEMBER_KIT",
    "ChooseReadiness",
    "CreateGroup",
    "InstallTemplate",
    "RestoreAgentRevision",
    "RestoreAgentVersion",
    "SaveKit",
    "SetGroupMembers",
    "SetOfficeLook",
    "SuggestMemberKit",
]


class CreateGroup(CofounderFields):
    title: Any
    members: Any


CREATE_GROUP: OperationSpec[CreateGroup] = OperationSpec(
    name="create_group",
    input_model=CreateGroup,
    audit_title="Group chat “{title}”",
    gate="undo",
    effect="work",
    web_action="createGroup",
    cofounder_domain=TEAM,
    cofounder_fields="title, members (member IDs)",
    cofounder_structured=("members",),
)


class SetGroupMembers(CofounderFields):
    group: Any
    members: Any


SET_GROUP_MEMBERS: OperationSpec[SetGroupMembers] = OperationSpec(
    name="set_group_members",
    input_model=SetGroupMembers,
    audit_title="Members of the group “{group}”",
    gate="undo",
    effect="work",
    web_action="setGroupMembers",
    cofounder_domain=TEAM,
    cofounder_fields="group (its title or chat number), members (the whole new list of member IDs)",
    cofounder_structured=("members",),
)


class SaveKit(CofounderFields):
    member: Any
    kit: Any


SAVE_KIT: OperationSpec[SaveKit] = OperationSpec(
    name="save_kit",
    input_model=SaveKit,
    audit_title="Kit of @{member}",
    gate="undo",
    web_action="saveKit",
    cofounder_domain=TEAM,
    cofounder_fields="member, kit (the hire_agent kit object: tools, skills, docs, team, onboarding)",
    cofounder_structured=("kit",),
)


class SuggestMemberKit(CofounderFields):
    member: Any
    note: Any = None
    kit: Any = None
    model: Any = None
    model_why: Any = None
    why: Any = None


SUGGEST_MEMBER_KIT: OperationSpec[SuggestMemberKit] = OperationSpec(
    name="suggest_member_kit",
    input_model=SuggestMemberKit,
    audit_title="Kit for @{member}",
    gate="once",
    effect="work",
    web_action="suggestKit",
    cofounder_domain=TEAM,
    cofounder_fields=(
        'member (its ID, or "all" = every member without a whole kit), note; or, to '
        "propose it yourself: kit, model, model_why, why (as agos_propose kind kit). "
        "Always a card the owner approves in his Inbox, never written on the spot"
    ),
    cofounder_structured=("kit", "model"),
)


class ChooseReadiness(CofounderFields):
    member: Any
    choice: Any
    item: Any = None
    reason: Any = None


CHOOSE_READINESS: OperationSpec[ChooseReadiness] = OperationSpec(
    name="choose_readiness",
    input_model=ChooseReadiness,
    audit_title="Readiness of @{member}: {choice} {item}",
    gate="undo",
    effect="work",
    web_action="chooseReadiness",
    cofounder_domain=TEAM,
    cofounder_fields=(
        "member, choice (not_needed | start_anyway | skip_test | retry | make_topic | "
        "clear), item (the checklist item id, for not_needed), reason"
    ),
)


class SetOfficeLook(CofounderFields):
    member: Any
    look: Any


SET_OFFICE_LOOK: OperationSpec[SetOfficeLook] = OperationSpec(
    name="set_office_look",
    input_model=SetOfficeLook,
    audit_title="Office look of @{member}",
    gate="undo",
    effect="work",
    web_action="saveOfficeLook",
    cofounder_domain=TEAM,
    cofounder_fields='member, look (the Office page\'s fields, e.g. {"pet_name": ...}; named fields only)',
    cofounder_structured=("look",),
)


class InstallTemplate(CofounderFields):
    slug: Any
    under: Any = None
    inputs: Any = None
    later: Any = None


INSTALL_TEMPLATE: OperationSpec[InstallTemplate] = OperationSpec(
    name="install_template",
    input_model=InstallTemplate,
    audit_title="Install the ready-made team {slug} here",
    gate="owner",
    web_action="installTemplate",
    cofounder_domain=WORKSPACE,
    cofounder_fields="slug, under (a member: the team's lead), inputs, later",
    cofounder_structured=("inputs", "later"),
)


class RestoreAgentVersion(CofounderFields):
    version: Any


RESTORE_AGENT_VERSION: OperationSpec[RestoreAgentVersion] = OperationSpec(
    name="restore_agent_version",
    input_model=RestoreAgentVersion,
    audit_title="Agent back to kept version {version}",
    gate="undo",
    web_action="restoreAgent",
    cofounder_domain=WORKSPACE,
    cofounder_fields="version (AGOS's identity history; brings back a deleted agent too)",
)


class RestoreAgentRevision(CofounderFields):
    agent: Any
    revision: Any


RESTORE_AGENT_REVISION: OperationSpec[RestoreAgentRevision] = OperationSpec(
    name="restore_agent_revision",
    input_model=RestoreAgentRevision,
    audit_title="@{agent} back to v{revision}",
    gate="undo",
    web_action="restoreAgentRevision",
    cofounder_domain=WORKSPACE,
    cofounder_fields="agent, revision",
)

SPECS: tuple[OperationSpec[Any], ...] = (
    CREATE_GROUP,
    SET_GROUP_MEMBERS,
    SAVE_KIT,
    SUGGEST_MEMBER_KIT,
    CHOOSE_READINESS,
    SET_OFFICE_LOOK,
    INSTALL_TEMPLATE,
    RESTORE_AGENT_VERSION,
    RESTORE_AGENT_REVISION,
)
