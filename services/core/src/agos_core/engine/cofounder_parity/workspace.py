"""The Co-Founder's workspace kinds still written by hand: work hours, docs, agent
rules and methods, channels and people, artifacts, backups, Hermes update, folders.
The Vision, Settings, Connector, Portability and Team services' kinds of this domain
are declared operations (ops/specs).

Part of the Co-Founder's KINDS (merged in DOMAINS order by
cofounder_parity/catalog.py).

Must not: run a kind (actions/cofounder_more.py) or merge the catalogue (catalog.py).
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import WORKSPACE, Kind
from agos_core.engine.cofounder_parity.prefs import PREFS_KINDS

__all__ = [
    "WORKSPACE_KINDS",
]

WORKSPACE_KINDS: dict[str, Kind] = {
    # ---- workspace --------------------------------------------------------------------
    "set_work_hours": Kind(
        WORKSPACE,
        (),
        "Work hours: {on}",
        "on (true = the hours hold; false = always on), days (an object mon..sun, each "
        "{from: HH:MM, to: HH:MM} on the owner's timezone, to before from = ends the next "
        "morning, null = OFF that day; leave out = keep the days)",
        structured=("days",),
    ),
    "stay_on_today": Kind(
        WORKSPACE,
        (),
        "Who stays on today",
        "agents (a list of member names, cofounder = you; [] = nobody): they keep working "
        "until the next check-in, then it clears by itself",
        structured=("agents",),
    ),
    "wake_now": Kind(
        WORKSPACE,
        ("agent",),
        "Wake {agent} now (on for today)",
        "agent (a member's name, or cofounder): on until the next check-in",
    ),
    "delete_doc": Kind(
        WORKSPACE, ("path", "why"), "Delete the rule file “{path}”", "path, why", "owner"
    ),
    "restore_doc_version": Kind(
        WORKSPACE,
        ("version", "why"),
        "Rule file back to version {version}",
        "version (from the doc's history), why",
    ),
    "set_latin_only": Kind(WORKSPACE, (), "Docs in Latin letters only: {on}", "on (true/false)"),
    "edit_owner_rule": Kind(
        WORKSPACE,
        ("rule", "text"),
        "Change your rule: “{text}”",
        "rule (its number), text",
        "owner",
    ),
    "delete_owner_rule": Kind(WORKSPACE, ("rule",), "Delete your rule {rule}", "rule", "owner"),
    "edit_method": Kind(
        WORKSPACE, ("method", "text"), "Change Brain method {method}", "method, text", "owner"
    ),
    "delete_method": Kind(
        WORKSPACE, ("method",), "Delete Brain method {method}", "method", "owner"
    ),
    "set_method_here": Kind(
        WORKSPACE,
        ("method",),
        "Brain method {method} here: {used}",
        "method, used (true/false: in this workspace)",
    ),
    "set_team_group": Kind(
        WORKSPACE, (), "Telegram team group: {group}", 'group (its id, -100...; "" = none)'
    ),
    "set_bot_reactions": Kind(WORKSPACE, (), "Bot reactions on Telegram: {on}", "on (true/false)"),
    "add_chat_address": Kind(
        WORKSPACE,
        ("chat",),
        "Link chat {chat} to Telegram",
        "chat (its number), address (a group/topic from the Telegram places) or create_topic "
        "(a group id: a new topic), notify",
    ),
    "remove_chat_address": Kind(
        WORKSPACE,
        ("chat", "address"),
        "Unlink a Telegram place from chat {chat}",
        "chat, address",
        "owner",
    ),
    "approve_person": Kind(
        WORKSPACE,
        ("request",),
        "Let {request} talk to the bot",
        "request (the pairing code)",
        "owner",
    ),
    "remove_person": Kind(
        WORKSPACE,
        ("user",),
        "The bot stops listening to {user}",
        "user (Telegram user id)",
        "owner",
    ),
    "review_artifact": Kind(
        WORKSPACE,
        ("artifact",),
        "Review {artifact}: {state}",
        'artifact, state (approved | changes | "" = take back), note',
    ),
    "promote_artifact": Kind(
        WORKSPACE,
        ("card", "attachment"),
        "Attachment {attachment} becomes a document of card {card}",
        "card, attachment (its number), key",
        "once",
    ),
    **PREFS_KINDS,  # set_timezone, set_notifications, errors, set_flag
    "set_backup_schedule": Kind(
        WORKSPACE, ("schedule",), "Backups: {schedule}", "schedule (off | daily | weekly), keep"
    ),
    "run_backup": Kind(WORKSPACE, (), "Back up AGOS now", "(no fields)", "once"),
    "rehearse_restore": Kind(
        WORKSPACE, (), "Rehearse a restore", "name (a backup; leave out = the last)", "once"
    ),
    "check_hermes_update": Kind(WORKSPACE, (), "Check for a Hermes update", "(no fields)", "once"),
    "run_hermes_update": Kind(WORKSPACE, (), "Update Hermes now", "(no fields)", "owner"),
    "undo_learned": Kind(
        WORKSPACE, ("entry",), "Undo a learned change ({entry})", "entry (from Learned)", "once"
    ),
    # ---- folders (the Automations, Skills and Projects lists) ----------------------------
    "create_folder": Kind(
        WORKSPACE,
        ("kind", "name"),
        "New {kind} folder “{name}”",
        "kind (automation | skill | project), name",
    ),
    "rename_folder": Kind(
        WORKSPACE,
        ("kind", "folder", "new"),
        "Rename {kind} folder “{folder}” → “{new}”",
        "kind, folder (its name or number), new",
    ),
    "delete_folder": Kind(
        WORKSPACE,
        ("kind", "folder"),
        "Delete {kind} folder “{folder}” (its items go back to No folder)",
        "kind, folder: only the folder goes, never what is in it",
    ),
    "move_to_folder": Kind(
        WORKSPACE,
        ("kind", "item"),
        "Move {kind} “{item}” to {folder}",
        'kind, item (its name, title or number), folder (its name; "" = No folder)',
    ),
}
