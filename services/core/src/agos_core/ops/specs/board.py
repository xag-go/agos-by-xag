"""The Board's Co-Founder kinds: labels, saved views, cards (goal, assignee, hold, bulk, watch,
estimate), review rules, card documents and status cards (actions/board_ops.py binds them
to the Co-Founder's page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import BOARD
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class CreateLabel(CofounderFields):
    name: Any


CREATE_LABEL: OperationSpec[CreateLabel] = OperationSpec(
    name="create_label",
    input_model=CreateLabel,
    audit_title="Label “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="createLabel",
    cofounder_domain=BOARD,
    cofounder_fields="name, color (gray, red, green...), folder",
)


class UpdateLabel(CofounderFields):
    label: Any


UPDATE_LABEL: OperationSpec[UpdateLabel] = OperationSpec(
    name="update_label",
    input_model=UpdateLabel,
    audit_title="Change label “{label}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="updateLabel",
    cofounder_domain=BOARD,
    cofounder_fields="label (its name or number), name, color, folder",
)


class DeleteLabel(CofounderFields):
    label: Any


DELETE_LABEL: OperationSpec[DeleteLabel] = OperationSpec(
    name="delete_label",
    input_model=DeleteLabel,
    audit_title="Delete label “{label}” (off every card)",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="deleteLabel",
    cofounder_domain=BOARD,
    cofounder_fields="label",
)


class RenameLabelFolder(CofounderFields):
    folder: Any
    new: Any


RENAME_LABEL_FOLDER: OperationSpec[RenameLabelFolder] = OperationSpec(
    name="rename_label_folder",
    input_model=RenameLabelFolder,
    audit_title="Label folder “{folder}” → “{new}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="renameLabelFolder",
    cofounder_domain=BOARD,
    cofounder_fields="folder, new",
)


class SaveBoardView(CofounderFields):
    name: Any


SAVE_BOARD_VIEW: OperationSpec[SaveBoardView] = OperationSpec(
    name="save_board_view",
    input_model=SaveBoardView,
    audit_title="Kanban view “{name}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="saveBoardView",
    cofounder_domain=BOARD,
    cofounder_fields="name (an existing view of that name changes), filters (object), groupBy, sort, layout, columns",
    cofounder_structured=("filters", "columns"),
)


class DeleteBoardView(CofounderFields):
    view: Any


DELETE_BOARD_VIEW: OperationSpec[DeleteBoardView] = OperationSpec(
    name="delete_board_view",
    input_model=DeleteBoardView,
    audit_title="Delete Kanban view “{view}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="deleteBoardView",
    cofounder_domain=BOARD,
    cofounder_fields="view (its name)",
)


class SetCardGoal(CofounderFields):
    card: Any


SET_CARD_GOAL: OperationSpec[SetCardGoal] = OperationSpec(
    name="set_card_goal",
    input_model=SetCardGoal,
    audit_title="Card {card} serves goal {goal}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="setCardGoal",
    cofounder_domain=BOARD,
    cofounder_fields="card, goal (a goal's or project's number; \"\" = none)",
)


class AssignCard(CofounderFields):
    card: Any
    member: Any


ASSIGN_CARD: OperationSpec[AssignCard] = OperationSpec(
    name="assign_card",
    input_model=AssignCard,
    audit_title="Give card {card} to @{member}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="assignCard",
    cofounder_domain=BOARD,
    cofounder_fields="card, member",
)


class CardAction(CofounderFields):
    card: Any
    action: Any


CARD_ACTION: OperationSpec[CardAction] = OperationSpec(
    name="card_action",
    input_model=CardAction,
    audit_title="Card {card}: {action}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="actOnCard",
    cofounder_domain=BOARD,
    cofounder_fields="card, action (unblock | done | block | archive), summary (for done)",
)


class HoldCards(CofounderFields):
    card: Any
    action: Any


HOLD_CARDS: OperationSpec[HoldCards] = OperationSpec(
    name="hold_cards",
    input_model=HoldCards,
    audit_title="{action} card {card} and everything under it",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="holdSubtree",
    cofounder_domain=BOARD,
    cofounder_fields="card, action (pause | cancel)",
)


class ResumeHold(CofounderFields):
    hold: Any


RESUME_HOLD: OperationSpec[ResumeHold] = OperationSpec(
    name="resume_hold",
    input_model=ResumeHold,
    audit_title="Resume held cards (hold {hold})",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="resumeHold",
    cofounder_domain=BOARD,
    cofounder_fields="hold",
)


class BulkCards(CofounderFields):
    cards: Any
    action: Any


BULK_CARDS: OperationSpec[BulkCards] = OperationSpec(
    name="bulk_cards",
    input_model=BulkCards,
    audit_title="{action} on several cards",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="bulkCards",
    cofounder_domain=BOARD,
    cofounder_fields="cards (ids), action (the board toolbar's: archive, assign, labels, done...), member, add / remove (label numbers), summary",
    cofounder_structured=("cards", "add", "remove"),
)


class WatchCard(CofounderFields):
    card: Any
    member: Any


WATCH_CARD: OperationSpec[WatchCard] = OperationSpec(
    name="watch_card",
    input_model=WatchCard,
    audit_title="@{member} watches card {card}: {on}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="watchCard",
    cofounder_domain=BOARD,
    cofounder_fields="card, member (or cofounder), on (true/false)",
)


class EstimateCard(CofounderFields):
    card: Any


ESTIMATE_CARD: OperationSpec[EstimateCard] = OperationSpec(
    name="estimate_card",
    input_model=EstimateCard,
    audit_title="Estimate card {card}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="estimateCard",
    cofounder_domain=BOARD,
    cofounder_fields="card",
)


class SetCardReview(CofounderFields):
    card: Any


SET_CARD_REVIEW: OperationSpec[SetCardReview] = OperationSpec(
    name="set_card_review",
    input_model=SetCardReview,
    audit_title="Review rules of card {card}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="setReviewRules",
    cofounder_domain=BOARD,
    cofounder_fields="card, stages (reviewer names in order), cap (rounds), plan (true = plan first), plan_reviewer, reset (true = the workspace's defaults)",
    cofounder_structured=("stages",),
)


class SaveReviewSettings(CofounderFields):
    pass


SAVE_REVIEW_SETTINGS: OperationSpec[SaveReviewSettings] = OperationSpec(
    name="save_review_settings",
    input_model=SaveReviewSettings,
    audit_title="Review settings of the workspace",
    gate="undo",
    agent_tool=None,
    web_action="saveReviewSettings",
    cofounder_domain=BOARD,
    cofounder_fields="stages, cap, plan_first (true/false), plan_reviewer",
    cofounder_structured=("stages",),
)


class RestoreCardDoc(CofounderFields):
    card: Any
    key: Any
    revision: Any


RESTORE_CARD_DOC: OperationSpec[RestoreCardDoc] = OperationSpec(
    name="restore_card_doc",
    input_model=RestoreCardDoc,
    audit_title="Card {card}'s document {key} back to r{revision}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="restoreCardDoc",
    cofounder_domain=BOARD,
    cofounder_fields="card, key, revision",
)


class ResolveDocComment(CofounderFields):
    comment: Any


RESOLVE_DOC_COMMENT: OperationSpec[ResolveDocComment] = OperationSpec(
    name="resolve_doc_comment",
    input_model=ResolveDocComment,
    audit_title="Comment {comment}: resolved {resolved}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="resolveAnnotation",
    cofounder_domain=BOARD,
    cofounder_fields="card, key, comment (its number), resolved (true/false)",
)


class CreateStatusCard(CofounderFields):
    title: Any
    scope: Any


CREATE_STATUS_CARD: OperationSpec[CreateStatusCard] = OperationSpec(
    name="create_status_card",
    input_model=CreateStatusCard,
    audit_title="Status card “{title}”",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="addStatusCard",
    cofounder_domain=BOARD,
    cofounder_fields="title, scope (workspace | goal | project | member | query = some words), scope_ref (the goal/project number, the member, or the words), policy (daily | weekly | manual), time (HH:MM), day",
)


class UpdateStatusCard(CofounderFields):
    card: Any


UPDATE_STATUS_CARD: OperationSpec[UpdateStatusCard] = OperationSpec(
    name="update_status_card",
    input_model=UpdateStatusCard,
    audit_title="Change status card {card}",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="saveStatusCard",
    cofounder_domain=BOARD,
    cofounder_fields="card (its number) and the create fields",
)


class DeleteStatusCard(CofounderFields):
    card: Any


DELETE_STATUS_CARD: OperationSpec[DeleteStatusCard] = OperationSpec(
    name="delete_status_card",
    input_model=DeleteStatusCard,
    audit_title="Delete status card {card}",
    gate="owner",
    agent_tool=None,
    effect="work",
    web_action="deleteStatusCard",
    cofounder_domain=BOARD,
    cofounder_fields="card",
    undo_after_yes=True,
)


class RefreshStatusCard(CofounderFields):
    card: Any


REFRESH_STATUS_CARD: OperationSpec[RefreshStatusCard] = OperationSpec(
    name="refresh_status_card",
    input_model=RefreshStatusCard,
    audit_title="Refresh status card {card}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="refreshStatusCard",
    cofounder_domain=BOARD,
    cofounder_fields="card",
)


SPECS: tuple[OperationSpec[Any], ...] = (
    CREATE_LABEL,
    UPDATE_LABEL,
    DELETE_LABEL,
    RENAME_LABEL_FOLDER,
    SAVE_BOARD_VIEW,
    DELETE_BOARD_VIEW,
    SET_CARD_GOAL,
    ASSIGN_CARD,
    CARD_ACTION,
    HOLD_CARDS,
    RESUME_HOLD,
    BULK_CARDS,
    WATCH_CARD,
    ESTIMATE_CARD,
    SET_CARD_REVIEW,
    SAVE_REVIEW_SETTINGS,
    RESTORE_CARD_DOC,
    RESOLVE_DOC_COMMENT,
    CREATE_STATUS_CARD,
    UPDATE_STATUS_CARD,
    DELETE_STATUS_CARD,
    REFRESH_STATUS_CARD,
)
