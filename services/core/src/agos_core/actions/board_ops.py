"""The Board service's Co-Founder kinds (declared in ops/specs/board.py), bound to the
page actions the Co-Founder already ran: each runs through the registry, which validates
its fields, checks the caller and its workspace and writes the audit row; its card's Undo
is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import (
    board_actions,
)
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import (
    board,
)

__all__: list[str] = []  # binds at import; nothing to call

bind_page(board.CREATE_LABEL, board_actions.do_create_label, board_actions.undo_create_label)
bind_page(board.UPDATE_LABEL, board_actions.do_update_label, board_actions.undo_update_label)
bind_page(board.DELETE_LABEL, board_actions.do_delete_label)
bind_page(
    board.RENAME_LABEL_FOLDER, board_actions.do_rename_folder, board_actions.undo_rename_folder
)
bind_page(board.SAVE_BOARD_VIEW, board_actions.do_save_view, board_actions.undo_save_view)
bind_page(board.DELETE_BOARD_VIEW, board_actions.do_delete_view, board_actions.undo_delete_view)
bind_page(board.SET_CARD_GOAL, board_actions.do_card_goal, board_actions.undo_card_goal)
bind_page(board.ASSIGN_CARD, board_actions.do_assign, board_actions.undo_assign)
bind_page(board.CARD_ACTION, board_actions.do_card_action)
bind_page(board.HOLD_CARDS, board_actions.do_hold, board_actions.undo_hold)
bind_page(board.RESUME_HOLD, board_actions.do_resume_hold)
bind_page(board.BULK_CARDS, board_actions.do_bulk)
bind_page(board.WATCH_CARD, board_actions.do_watch_card, board_actions.undo_watch_card)
bind_page(board.ESTIMATE_CARD, board_actions.do_estimate)
bind_page(board.SET_CARD_REVIEW, board_actions.do_card_review, board_actions.undo_card_review)
bind_page(
    board.SAVE_REVIEW_SETTINGS, board_actions.do_review_settings, board_actions.undo_review_settings
)
bind_page(board.RESTORE_CARD_DOC, board_actions.do_card_doc, board_actions.undo_card_doc)
bind_page(board.RESOLVE_DOC_COMMENT, board_actions.do_doc_comment, board_actions.undo_doc_comment)
bind_page(
    board.CREATE_STATUS_CARD, board_actions.do_create_status, board_actions.undo_create_status
)
bind_page(
    board.UPDATE_STATUS_CARD, board_actions.do_update_status, board_actions.undo_update_status
)
bind_page(
    board.DELETE_STATUS_CARD, board_actions.do_delete_status, board_actions.undo_delete_status
)
bind_page(board.REFRESH_STATUS_CARD, board_actions.do_refresh_status)
