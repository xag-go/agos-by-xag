"""The Co-Founder's kinds for Telegram and channels (team group, reactions, chat addresses,
people) and artifacts (actions/workspace_admin_ops.py binds them to the page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class SetTeamGroup(CofounderFields):
    pass


SET_TEAM_GROUP: OperationSpec[SetTeamGroup] = OperationSpec(
    name="set_team_group",
    input_model=SetTeamGroup,
    audit_title="Telegram team group: {group}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="setTeamGroup",
    cofounder_domain=WORKSPACE,
    cofounder_fields='group (its id, -100...; "" = none)',
)


class SetBotReactions(CofounderFields):
    pass


SET_BOT_REACTIONS: OperationSpec[SetBotReactions] = OperationSpec(
    name="set_bot_reactions",
    input_model=SetBotReactions,
    audit_title="Bot reactions on Telegram: {on}",
    gate="undo",
    agent_tool=None,
    web_action="setBotReactions",
    cofounder_domain=WORKSPACE,
    cofounder_fields="on (true/false)",
)


class AddChatAddress(CofounderFields):
    chat: Any


ADD_CHAT_ADDRESS: OperationSpec[AddChatAddress] = OperationSpec(
    name="add_chat_address",
    input_model=AddChatAddress,
    audit_title="Link chat {chat} to Telegram",
    gate="undo",
    agent_tool=None,
    web_action="addAddress",
    cofounder_domain=WORKSPACE,
    cofounder_fields="chat (its number), address (a group/topic from the Telegram places) or create_topic (a group id: a new topic), notify",
)


class RemoveChatAddress(CofounderFields):
    chat: Any
    address: Any


REMOVE_CHAT_ADDRESS: OperationSpec[RemoveChatAddress] = OperationSpec(
    name="remove_chat_address",
    input_model=RemoveChatAddress,
    audit_title="Unlink a Telegram place from chat {chat}",
    gate="owner",
    agent_tool=None,
    web_action="removeAddress",
    cofounder_domain=WORKSPACE,
    cofounder_fields="chat, address",
)


class ApprovePerson(CofounderFields):
    request: Any


APPROVE_PERSON: OperationSpec[ApprovePerson] = OperationSpec(
    name="approve_person",
    input_model=ApprovePerson,
    audit_title="Let {request} talk to the bot",
    gate="owner",
    agent_tool=None,
    web_action="approvePerson",
    cofounder_domain=WORKSPACE,
    cofounder_fields="request (the pairing code)",
)


class RemovePerson(CofounderFields):
    user: Any


REMOVE_PERSON: OperationSpec[RemovePerson] = OperationSpec(
    name="remove_person",
    input_model=RemovePerson,
    audit_title="The bot stops listening to {user}",
    gate="owner",
    agent_tool=None,
    web_action="removePerson",
    cofounder_domain=WORKSPACE,
    cofounder_fields="user (Telegram user id)",
)


class ReviewArtifact(CofounderFields):
    artifact: Any


REVIEW_ARTIFACT: OperationSpec[ReviewArtifact] = OperationSpec(
    name="review_artifact",
    input_model=ReviewArtifact,
    audit_title="Review {artifact}: {state}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="reviewArtifact",
    cofounder_domain=WORKSPACE,
    cofounder_fields='artifact, state (approved | changes | "" = take back), note',
)


class PromoteArtifact(CofounderFields):
    card: Any
    attachment: Any


PROMOTE_ARTIFACT: OperationSpec[PromoteArtifact] = OperationSpec(
    name="promote_artifact",
    input_model=PromoteArtifact,
    audit_title="Attachment {attachment} becomes a document of card {card}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="promoteArtifact",
    cofounder_domain=WORKSPACE,
    cofounder_fields="card, attachment (its number), key",
)


SPECS: tuple[OperationSpec[Any], ...] = (
    SET_TEAM_GROUP,
    SET_BOT_REACTIONS,
    ADD_CHAT_ADDRESS,
    REMOVE_CHAT_ADDRESS,
    APPROVE_PERSON,
    REMOVE_PERSON,
    REVIEW_ARTIFACT,
    PROMOTE_ARTIFACT,
)
