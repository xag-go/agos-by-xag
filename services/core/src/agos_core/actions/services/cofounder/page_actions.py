"""The table of the Co-Founder's page actions: each kind's do and undo, and running them.
Must not: hold any kind's logic (that lives in its page's module above).

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from agos_core.actions import (  # noqa: F401 - each binds its service's declared kinds
    automation_ops,
    cofounder_prefs,
    connector_ops,
    library_ops,
    portability_ops,
    settings_ops,
    team_ops,
    vision_ops,
)
from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.action_args import Fields, Result
from agos_core.actions.services.cofounder.board_actions import (
    do_assign,
    do_bulk,
    do_card_action,
    do_card_doc,
    do_card_goal,
    do_card_review,
    do_create_label,
    do_create_status,
    do_delete_label,
    do_delete_status,
    do_delete_view,
    do_doc_comment,
    do_estimate,
    do_hold,
    do_refresh_status,
    do_rename_folder,
    do_resume_hold,
    do_review_settings,
    do_save_view,
    do_update_label,
    do_update_status,
    do_watch_card,
    undo_assign,
    undo_card_doc,
    undo_card_goal,
    undo_card_review,
    undo_create_label,
    undo_create_status,
    undo_delete_status,
    undo_delete_view,
    undo_doc_comment,
    undo_hold,
    undo_rename_folder,
    undo_review_settings,
    undo_save_view,
    undo_update_label,
    undo_update_status,
    undo_watch_card,
)
from agos_core.actions.services.cofounder.connection_actions import (
    do_add_address,
    do_approve_person,
    do_promote,
    do_reactions,
    do_remove_address,
    do_remove_person,
    do_review_artifact,
    do_team_group,
    undo_add_address,
    undo_reactions,
    undo_review_artifact,
    undo_team_group,
)
from agos_core.actions.services.cofounder.folder_actions import (
    do_create_folder,
    do_delete_folder,
    do_move_to_folder,
    do_rename_folder_of,
    undo_create_folder,
    undo_delete_folder,
    undo_move_to_folder,
    undo_rename_folder_of,
)
from agos_core.actions.services.cofounder.settings_actions import (
    do_backup_schedule,
    do_check_update,
    do_rehearse,
    do_run_backup,
    do_run_update,
    undo_backup_schedule,
    undo_learned,
)
from agos_core.actions.services.cofounder.workspace_actions import (
    do_delete_doc,
    do_delete_method,
    do_delete_owner_rule,
    do_edit_method,
    do_edit_owner_rule,
    do_latin,
    do_method_here,
    do_restore_doc,
    do_stay_on,
    do_wake_now,
    do_work_hours,
    undo_delete_method,
    undo_delete_owner_rule,
    undo_doc_text,
    undo_edit_method,
    undo_edit_owner_rule,
    undo_latin,
    undo_method_here,
    undo_stay_on,
    undo_work_hours,
)
from agos_core.context import Core
from agos_core.engine import cofounder_parity as parity
from agos_core.ops import cofounder as ops_cofounder

__all__ = [
    "DOES",
    "KINDS",
    "UNDOES",
    "Do",
    "Undo",
    "do",
    "undo",
]

Do = Callable[[Core, str, Fields], Result]
Undo = Callable[[Core, str, Result], None]

# The registry's Co-Founder kinds (ops/specs), run through ops.registry like the owner's.
_OPS_DOES, _OPS_UNDOES = ops_cofounder.adapters()

DOES: dict[str, Do] = {
    **_OPS_DOES,
    "create_label": do_create_label,
    "update_label": do_update_label,
    "delete_label": do_delete_label,
    "rename_label_folder": do_rename_folder,
    "save_board_view": do_save_view,
    "delete_board_view": do_delete_view,
    "set_card_goal": do_card_goal,
    "assign_card": do_assign,
    "card_action": do_card_action,
    "hold_cards": do_hold,
    "resume_hold": do_resume_hold,
    "bulk_cards": do_bulk,
    "watch_card": do_watch_card,
    "estimate_card": do_estimate,
    "set_card_review": do_card_review,
    "save_review_settings": do_review_settings,
    "restore_card_doc": do_card_doc,
    "resolve_doc_comment": do_doc_comment,
    "create_status_card": do_create_status,
    "update_status_card": do_update_status,
    "delete_status_card": do_delete_status,
    "refresh_status_card": do_refresh_status,
    "set_work_hours": do_work_hours,
    "stay_on_today": do_stay_on,
    "wake_now": do_wake_now,
    "delete_doc": do_delete_doc,
    "restore_doc_version": do_restore_doc,
    "set_latin_only": do_latin,
    "edit_owner_rule": do_edit_owner_rule,
    "delete_owner_rule": do_delete_owner_rule,
    "edit_method": do_edit_method,
    "delete_method": do_delete_method,
    "set_method_here": do_method_here,
    "set_team_group": do_team_group,
    "set_bot_reactions": do_reactions,
    "add_chat_address": do_add_address,
    "remove_chat_address": do_remove_address,
    "approve_person": do_approve_person,
    "remove_person": do_remove_person,
    "review_artifact": do_review_artifact,
    "promote_artifact": do_promote,
    **cofounder_prefs.DOES,  # set_timezone, set_notifications, mark_error_fixed, reopen_error
    "set_backup_schedule": do_backup_schedule,
    "run_backup": do_run_backup,
    "rehearse_restore": do_rehearse,
    "check_hermes_update": do_check_update,
    "run_hermes_update": do_run_update,
    "undo_learned": undo_learned,
    "create_folder": do_create_folder,
    "rename_folder": do_rename_folder_of,
    "delete_folder": do_delete_folder,
    "move_to_folder": do_move_to_folder,
}

UNDOES: dict[str, Undo] = {
    **_OPS_UNDOES,
    "create_label": undo_create_label,
    "update_label": undo_update_label,
    "rename_label_folder": undo_rename_folder,
    "save_board_view": undo_save_view,
    "delete_board_view": undo_delete_view,
    "set_card_goal": undo_card_goal,
    "assign_card": undo_assign,
    "hold_cards": undo_hold,
    "watch_card": undo_watch_card,
    "set_card_review": undo_card_review,
    "save_review_settings": undo_review_settings,
    "restore_card_doc": undo_card_doc,
    "resolve_doc_comment": undo_doc_comment,
    "create_status_card": undo_create_status,
    "update_status_card": undo_update_status,
    "delete_status_card": undo_delete_status,
    "set_work_hours": undo_work_hours,
    "stay_on_today": undo_stay_on,
    "wake_now": undo_stay_on,
    "delete_doc": undo_doc_text,
    "restore_doc_version": undo_doc_text,
    "set_latin_only": undo_latin,
    "edit_owner_rule": undo_edit_owner_rule,
    "delete_owner_rule": undo_delete_owner_rule,
    "edit_method": undo_edit_method,
    "delete_method": undo_delete_method,
    "set_method_here": undo_method_here,
    "set_team_group": undo_team_group,
    "set_bot_reactions": undo_reactions,
    "add_chat_address": undo_add_address,
    "review_artifact": undo_review_artifact,
    **cofounder_prefs.UNDOES,
    "set_backup_schedule": undo_backup_schedule,
    "create_folder": undo_create_folder,
    "rename_folder": undo_rename_folder_of,
    "delete_folder": undo_delete_folder,
    "move_to_folder": undo_move_to_folder,
}

KINDS = frozenset(parity.KINDS)


def do(core: Core, workspace_id: str, action: str, p: Fields) -> Result:
    """Runs one of these kinds through its page's own action; returns what Undo needs.
    It runs inside the Co-Founder's own turn: a gateway restart its page's code asks
    for waits until the turn's answer is out (hermes_channel.inside_turn)."""
    from agos_core.actions import hermes_channel

    with hermes_channel.inside_turn():
        return DOES[action](core, workspace_id, p)


def undo(core: Core, workspace_id: str, action: str, result: Result) -> None:
    found = UNDOES.get(action)
    if found is None:
        raise ActionError("This can't be undone.", 409)
    found(core, workspace_id, result)
