"""Read vs act: which Co-Founder actions change its powers (pure rules).

A turn or a run that read untrusted content (a web page, an email, a webhook's body,
a Telegram message from someone who isn't the owner...) may not change what the
agents can do on the model's word alone: in that turn every POWER action waits for
the owner's yes (Hermes's own Allow / Deny card in a chat; its card in the
Co-Founder chat for a card's worker or an automation's run). WORK actions (the board,
notes, folders) and READ actions stay as they are. An owner's chat that read nothing
from outside is unchanged.

Every agos_action kind has its row here; tests/test_read_vs_act.py fails on a kind
with none, so a new action can't skip the decision.
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import Effect as Effect
from agos_core.ops import catalog
from agos_core.ops.specs import SPECS


def _words(text: str) -> list[str]:
    return text.split()


_POWER = _words(
    # automations and what starts work by itself
    "create_automation update_automation resume_automation delete_automation "
    "set_work_hours "
    # agents, skills, tools, MCP servers, apps
    "create_skill update_skill create_agent hire_agent update_agent create_mcp update_mcp "
    "undo_learned "
    # rules, docs the agents read (SOUL / rules files), the Brain
    "update_doc update_file add_owner_rule add_method edit_owner_rule delete_owner_rule "
    "edit_method delete_method set_method_here delete_doc restore_doc_version "
    "save_review_settings set_latin_only "
    # keys, Hermes's settings, approvals, people, channels, the workspace
    "change_hermes_setting reset_hermes_setting approve_held_write reject_held_write "
    "add_pool_key remove_pool_key move_pool_key set_pool_strategy approve_person "
    "remove_person add_chat_address remove_chat_address set_bot_reactions set_timezone "
    "set_notifications set_backup_schedule run_hermes_update set_flag set_trusted_apps"
)

_READ = _words(
    "list_held_writes list_pool_keys hermes_health secrets_check show_hermes_setting "
    "check_hermes_update"
)

_WORK = _words(
    "pause_automation run_automation rename assign_founder founder_done create_label "
    "update_label delete_label rename_label_folder save_board_view delete_board_view "
    "set_card_goal assign_card card_action hold_cards resume_hold bulk_cards watch_card "
    "estimate_card set_card_review restore_card_doc resolve_doc_comment "
    "create_status_card update_status_card delete_status_card refresh_status_card "
    "stay_on_today wake_now set_team_group review_artifact promote_artifact run_backup "
    "rehearse_restore mark_error_fixed reopen_error create_folder rename_folder "
    "delete_folder move_to_folder"
)

EFFECT: dict[str, Effect] = {
    **{k: "work" for k in _WORK},
    **{k: "read" for k in _READ},
    **{k: "power" for k in _POWER},
    **catalog.effects(SPECS),  # the registry's kinds (ops/specs), as declared
}
# Several changes in one card (actions/cofounder_actions BUNDLE): always the owner's.
EFFECT["bundle"] = "power"

# The agos_capability tool turns an app or a toolset on or off: always a power.
CAPABILITY = "agos_capability"


def is_power(kind: str) -> bool:
    """Unknown kinds count as powers (fail closed)."""
    return EFFECT.get(kind, "power") == "power"


def held_message(source: str, titles: str) -> str:
    """What the owner reads on Hermes's Allow / Deny card (and on the run's card)."""
    return f"⚠️ This came after reading {source}. {titles}"[:900]


# What the agents create that the owner hears about (the rogue-agent alert).
CREATES = frozenset(
    {
        "create_automation",
        "create_mcp",
        "create_skill",
        "duplicate_skill",
        "install_skill",
        "add_pool_key",
        "save_pipeline_rule",
        "set_heartbeat",
        "watch_tree",
    }
)
