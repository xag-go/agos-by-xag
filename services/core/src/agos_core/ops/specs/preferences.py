"""The Co-Founder's kinds for the owner's preferences (timezone, notifications, Errors, Labs
flags, trusted apps), backups and Learned (actions/workspace_admin_ops.py
binds them to the page actions).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class SetTimezone(CofounderFields):
    timezone: Any


SET_TIMEZONE: OperationSpec[SetTimezone] = OperationSpec(
    name="set_timezone",
    input_model=SetTimezone,
    audit_title="Your timezone: {timezone}",
    gate="undo",
    agent_tool=None,
    web_action="saveTimezone",
    cofounder_domain=WORKSPACE,
    cofounder_fields="timezone",
)


class SetNotifications(CofounderFields):
    rules: Any


SET_NOTIFICATIONS: OperationSpec[SetNotifications] = OperationSpec(
    name="set_notifications",
    input_model=SetNotifications,
    audit_title="Notifications",
    gate="undo",
    agent_tool=None,
    web_action="saveNotifications",
    cofounder_domain=WORKSPACE,
    cofounder_fields="rules (object: event -> delivery, as Settings → Notifications)",
    cofounder_structured=("rules",),
)


class MarkErrorFixed(CofounderFields):
    error: Any


MARK_ERROR_FIXED: OperationSpec[MarkErrorFixed] = OperationSpec(
    name="mark_error_fixed",
    input_model=MarkErrorFixed,
    audit_title="Mark AGOS error #{error} fixed",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="markErrorFixed",
    cofounder_domain=WORKSPACE,
    cofounder_fields="error (its number in Settings → Errors): it opens again by itself if it happens again",
)


class ReopenError(CofounderFields):
    error: Any


REOPEN_ERROR: OperationSpec[ReopenError] = OperationSpec(
    name="reopen_error",
    input_model=ReopenError,
    audit_title="Open AGOS error #{error} again",
    gate="undo",
    agent_tool=None,
    effect="work",
    web_action="reopenError",
    cofounder_domain=WORKSPACE,
    cofounder_fields="error (its number)",
)


class SetFlag(CofounderFields):
    flag: Any
    on: Any


SET_FLAG: OperationSpec[SetFlag] = OperationSpec(
    name="set_flag",
    input_model=SetFlag,
    audit_title="Labs switch {flag}: {on}",
    gate="undo",
    agent_tool=None,
    web_action="saveFlag",
    cofounder_domain=WORKSPACE,
    cofounder_fields="flag (its name in Settings → General → Labs), on (true = on, false = off)",
)


class SetTrustedApps(CofounderFields):
    apps: Any


SET_TRUSTED_APPS: OperationSpec[SetTrustedApps] = OperationSpec(
    name="set_trusted_apps",
    input_model=SetTrustedApps,
    audit_title="Trusted apps: {apps}",
    gate="owner",
    agent_tool=None,
    web_action="saveTrustedApps",
    cofounder_domain=WORKSPACE,
    cofounder_fields="apps (list of app / MCP server names whose answers don't count as untrusted; [] = none). Only the owner says yes to it: it lets those apps' words reach power actions without asking him",
    cofounder_structured=("apps",),
    undo_after_yes=True,
)


class SetBackupSchedule(CofounderFields):
    schedule: Any


SET_BACKUP_SCHEDULE: OperationSpec[SetBackupSchedule] = OperationSpec(
    name="set_backup_schedule",
    input_model=SetBackupSchedule,
    audit_title="Backups: {schedule}",
    gate="undo",
    agent_tool=None,
    web_action="setBackupSchedule",
    cofounder_domain=WORKSPACE,
    cofounder_fields="schedule (off | daily | weekly), keep",
)


class RunBackup(CofounderFields):
    pass


RUN_BACKUP: OperationSpec[RunBackup] = OperationSpec(
    name="run_backup",
    input_model=RunBackup,
    audit_title="Back up AGOS now",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="runBackup",
    cofounder_domain=WORKSPACE,
    cofounder_fields="(no fields)",
)


class RehearseRestore(CofounderFields):
    pass


REHEARSE_RESTORE: OperationSpec[RehearseRestore] = OperationSpec(
    name="rehearse_restore",
    input_model=RehearseRestore,
    audit_title="Rehearse a restore",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="rehearseRestore",
    cofounder_domain=WORKSPACE,
    cofounder_fields="name (a backup; leave out = the last)",
)


class UndoLearned(CofounderFields):
    entry: Any


UNDO_LEARNED: OperationSpec[UndoLearned] = OperationSpec(
    name="undo_learned",
    input_model=UndoLearned,
    audit_title="Undo a learned change ({entry})",
    gate="once",
    agent_tool=None,
    web_action="undoLearned",
    cofounder_domain=WORKSPACE,
    cofounder_fields="entry (from Learned)",
)


SPECS: tuple[OperationSpec[Any], ...] = (
    SET_TIMEZONE,
    SET_NOTIFICATIONS,
    MARK_ERROR_FIXED,
    REOPEN_ERROR,
    SET_FLAG,
    SET_TRUSTED_APPS,
    SET_BACKUP_SCHEDULE,
    RUN_BACKUP,
    REHEARSE_RESTORE,
    UNDO_LEARNED,
)
