"""The workspace admin Co-Founder kinds (declared in ops/specs/work_hours.py, rules_docs.py,
channels.py, preferences.py, folders.py), bound to the page actions the Co-Founder
already ran: each runs through the registry (fields checked, caller and workspace
checked, audit row); its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions import cofounder_prefs
from agos_core.actions.services.cofounder import (
    connection_actions,
    folder_actions,
    settings_actions,
    workspace_actions,
)
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import (
    channels,
    folders,
    preferences,
    rules_docs,
    work_hours,
)

__all__: list[str] = []  # binds at import; nothing to call

bind_page(
    work_hours.SET_WORK_HOURS, workspace_actions.do_work_hours, workspace_actions.undo_work_hours
)
bind_page(work_hours.STAY_ON_TODAY, workspace_actions.do_stay_on, workspace_actions.undo_stay_on)
bind_page(work_hours.WAKE_NOW, workspace_actions.do_wake_now, workspace_actions.undo_stay_on)
bind_page(rules_docs.DELETE_DOC, workspace_actions.do_delete_doc, workspace_actions.undo_doc_text)
bind_page(
    rules_docs.RESTORE_DOC_VERSION,
    workspace_actions.do_restore_doc,
    workspace_actions.undo_doc_text,
)
bind_page(rules_docs.SET_LATIN_ONLY, workspace_actions.do_latin, workspace_actions.undo_latin)
bind_page(
    rules_docs.EDIT_OWNER_RULE,
    workspace_actions.do_edit_owner_rule,
    workspace_actions.undo_edit_owner_rule,
)
bind_page(
    rules_docs.DELETE_OWNER_RULE,
    workspace_actions.do_delete_owner_rule,
    workspace_actions.undo_delete_owner_rule,
)
bind_page(
    rules_docs.EDIT_METHOD, workspace_actions.do_edit_method, workspace_actions.undo_edit_method
)
bind_page(
    rules_docs.DELETE_METHOD,
    workspace_actions.do_delete_method,
    workspace_actions.undo_delete_method,
)
bind_page(
    rules_docs.SET_METHOD_HERE, workspace_actions.do_method_here, workspace_actions.undo_method_here
)
bind_page(
    channels.SET_TEAM_GROUP, connection_actions.do_team_group, connection_actions.undo_team_group
)
bind_page(
    channels.SET_BOT_REACTIONS, connection_actions.do_reactions, connection_actions.undo_reactions
)
bind_page(
    channels.ADD_CHAT_ADDRESS,
    connection_actions.do_add_address,
    connection_actions.undo_add_address,
)
bind_page(channels.REMOVE_CHAT_ADDRESS, connection_actions.do_remove_address)
bind_page(channels.APPROVE_PERSON, connection_actions.do_approve_person)
bind_page(channels.REMOVE_PERSON, connection_actions.do_remove_person)
bind_page(
    channels.REVIEW_ARTIFACT,
    connection_actions.do_review_artifact,
    connection_actions.undo_review_artifact,
)
bind_page(channels.PROMOTE_ARTIFACT, connection_actions.do_promote)
bind_page(
    preferences.SET_TIMEZONE,
    cofounder_prefs.DOES["set_timezone"],
    cofounder_prefs.UNDOES["set_timezone"],
)
bind_page(
    preferences.SET_NOTIFICATIONS,
    cofounder_prefs.DOES["set_notifications"],
    cofounder_prefs.UNDOES["set_notifications"],
)
bind_page(
    preferences.MARK_ERROR_FIXED,
    cofounder_prefs.DOES["mark_error_fixed"],
    cofounder_prefs.UNDOES["mark_error_fixed"],
)
bind_page(
    preferences.REOPEN_ERROR,
    cofounder_prefs.DOES["reopen_error"],
    cofounder_prefs.UNDOES["reopen_error"],
)
bind_page(
    preferences.SET_FLAG, cofounder_prefs.DOES["set_flag"], cofounder_prefs.UNDOES["set_flag"]
)
bind_page(
    preferences.SET_TRUSTED_APPS,
    cofounder_prefs.DOES["set_trusted_apps"],
    cofounder_prefs.UNDOES["set_trusted_apps"],
)
bind_page(
    preferences.SET_BACKUP_SCHEDULE,
    settings_actions.do_backup_schedule,
    settings_actions.undo_backup_schedule,
)
bind_page(preferences.RUN_BACKUP, settings_actions.do_run_backup)
bind_page(preferences.REHEARSE_RESTORE, settings_actions.do_rehearse)
bind_page(preferences.CHECK_HERMES_UPDATE, settings_actions.do_check_update)
bind_page(preferences.RUN_HERMES_UPDATE, settings_actions.do_run_update)
bind_page(preferences.UNDO_LEARNED, settings_actions.undo_learned)
bind_page(folders.CREATE_FOLDER, folder_actions.do_create_folder, folder_actions.undo_create_folder)
bind_page(
    folders.RENAME_FOLDER, folder_actions.do_rename_folder_of, folder_actions.undo_rename_folder_of
)
bind_page(folders.DELETE_FOLDER, folder_actions.do_delete_folder, folder_actions.undo_delete_folder)
bind_page(
    folders.MOVE_TO_FOLDER, folder_actions.do_move_to_folder, folder_actions.undo_move_to_folder
)
