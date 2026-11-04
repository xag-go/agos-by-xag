"""Every app_settings key (or `name.*` prefix) AGOS keeps, what a wildcard key's
`*` is, and the check for keys a database holds that nothing registers.

Owns: KEYS, WILDCARD_IDS, unregistered(). Must not: hold table or file entries
(tables.py, files.py).
"""

from __future__ import annotations

import sqlite3

from agos_core.db.ownership.base import Owned, agos, move
from agos_core.db.ownership.ops import OPS_KEYS

__all__ = ["KEYS", "WILDCARD_IDS", "unregistered"]

# app_settings keys. `name.*` = a fixed prefix + an id (workspace, chat, address).
KEYS: dict[str, Owned] = {
    # -- AGOS_ONLY: product and control data
    "push.vapid": agos(
        "the installed AGOS app's Web Push key pair (VAPID), made once, its private half "
        "sealed with AGOS's master key (actions/web_push.py); AGOS's own UI notifications",
    ),
    "usage": agos(
        "the owner's spending control (warn at / pause at): AGOS pauses through Hermes's "
        "own `hermes pause`/`resume` per workspace root (the ESTOP sentinel holds its "
        "cron, Kanban and new turns; actions/account_pause.py)",
        "H: cron/quota_hold.py:59 hold_active (a hold after provider quota failures, not "
        "a spend limit)",
    ),
    "notifications": agos("which AGOS events reach the owner where"),
    "hermes_update.check": agos(
        "the last Check Update's answer (installed release, offered release, whether "
        "AGOS fits it, its changes) — Hermes's own `update --plan` read by "
        "actions/hermes_update.run_check",
        "H: hermes_cli/update_inventory.py print_update_plan (the plan is printed, not kept)",
    ),
    "agos_update.check": agos(
        "the last Check Update's answer for AGOS itself (its release, the newer commits "
        "on the installer's branch, whether Hermes changes too) — actions/agos_update.py; "
        "Settings → General → Update AGOS",
    ),
    "hermes_update.state": agos(
        "the running (or last) Hermes update's progress and report "
        "(actions/hermes_update._run: backups → gateways off → `hermes update` → homes "
        "prepared → gateways on), what the maintenance card shows",
        "H: hermes_cli/update_cmd.py (its update runs in one command, no progress store)",
    ),
    "tabs": agos("the owner's order of the workspace tabs"),
    "workspace_order": agos("the owner's order of the workspaces on the rail"),
    "office.*": agos("the Office view's looks per workspace"),
    "skill_requests.*": agos(
        "a workspace's daily limit of find-skills requests (actions/skill_requests.py): "
        "how many hub skills its agents may ask for in one UTC day",
        "H: hermes_cli/skills_hub.py do_install (no request, quota or rate limit)",
    ),
    "work_hours.*": agos(
        "a workspace's work hours (Settings → Work hours, actions/work_hours.py): the "
        "owner's week (each day a range or OFF, on his timezone), on/off, and who stays "
        "on today with its end (the next check-in). Hermes's own switches carry the "
        "effect: kanban.dispatch_profiles, each cron job's pause, the cards' holds",
        "H: cron/jobs.py pause_job / resume_job and hermes_cli/kanban_db_dispatch.py "
        "_dispatch_profile_allowlist (on/off switches, no hours: no quiet or working hours "
        "anywhere in Hermes); agent/estop.py (ESTOP pauses a whole root and answers new "
        "turns 'Hermes is paused', no per-agent hours, no held messages)",
    ),
    "work_shift.*": agos(
        "what the work hours' loop last applied per agent of a workspace (on / closing "
        "/ off, since its check-out), so a check-out or a check-in is acted on once and a "
        "card finishing past check-out is parked at +2 h (actions/work_hours.py)",
        "H: hermes_cli/kanban_db.py schedule_task / unblock_task (the card's hold is "
        "Hermes's; nothing in Hermes knows a check-out time)",
    ),
    "review.*": agos(
        "a workspace's review defaults (the stages every card goes through, the round "
        "cap, plan first for cards with children, who accepts plans; actions/reviews.py). "
        "A card's own rules are a block in its Hermes body, each step a marker comment on "
        "it, the reviewer its assignee in Hermes's review column",
        "H: hermes_cli/kanban_db.py:3283 request_review (one reviewer per handoff, no "
        "stage list, no round cap, no plan to accept first); hermes_cli/config_defaults.py "
        "kanban.review_dispatch (on/off only)",
    ),
    "owner.name": agos(
        "the owner's name as he sets it in Settings → General (one for every "
        "workspace; copied once from the login AGOS had before, migration 141): the Founder's box, his cards' "
        "member slot, his Inbox items and phone notices, the Co-Founder's prompt",
        "H: hermes_cli/config_defaults.py (no owner / user name key; USER.md is a "
        "per-profile memory of facts, not a setting AGOS can read back as one value)",
    ),
    "founder.*": agos(
        "the owner's own box beside the Co-Founder (actions/founder.py): the title he "
        "gives himself in this workspace and the name it shows. His tasks are not here: "
        "they are Hermes cards assigned to `founder` (no profile has the name)",
        "H: hermes_cli/kanban_db_dispatch.py _dispatch_lane_task (a non-profile assignee "
        "is skipped_nonspawnable: a lane, no person record); hermes_cli/profiles.py "
        "write_profile_meta (profiles only, the owner is none)",
    ),
    "board.views.*": agos(
        "a workspace's saved Board views (name, filters, group-by, sort, layout, list "
        "columns), step 58: the owner's way of looking at the board, UI state Hermes "
        "has no notion of (actions/board_views.py)",
        "H: hermes_cli/kanban.py _cmd_list (filters per call: --mine, --assignee, "
        "--status; nothing saved); plugins/kanban/dashboard (no saved views)",
    ),
    "threads.seen.*": agos(
        "the last agent comments AGOS already acted on (ids of Hermes's task_comments), "
        "so a comment's @mentions wake once when its hook fires twice (actions/threads.py)",
        "H: hermes_cli/kanban_db.py add_comment (no mention, no wake; the gateway "
        "notifier wakes only on terminal events: gateway/kanban_watchers_notifier.py "
        "_WAKE_KINDS)",
    ),
    "cofounder.actions": agos("whether the Co-Founder asks before changing AGOS"),
    "hermes.tool_search": agos(
        "which of the Co-Founder's tools AGOS asks Hermes to keep eager or defer (the "
        "token-cost A/B switch), and whether AGOS wrote Hermes's keys for it; Hermes's "
        "own values live in each root's config.yaml (tools.tool_search.*), this is only "
        "the owner's one choice for every root and its Undo mark",
        "H: tools/tool_search.py:149-161 is_deferrable_tool_name (no per-tool never-defer "
        "for a plugin tool; config has only enabled and defer)",
    ),
    "card.tokens.answered.*": agos(
        "token-watch levels the owner already answered per card",
        "H: hermes_cli/kanban_db.py:937-961 task_runs has no token column",
    ),
    "digest.held.*": agos("AGOS's own phone cards waiting for the daily digest"),
    "errors.hermes_seen.*": agos(
        "the last Hermes errors.log entry already counted in Settings → Errors",
        "Hermes's own errors.log (hermes logs errors) has no read mark",
    ),
    **OPS_KEYS,
    "hooks.public_url": agos(
        "the public tunnel URL AGOS relays webhooks from",
        "H: hermes_cli/config_defaults.py:1066 dashboard.public_url (the dashboard's own)",
    ),
    "connectors.redirect_uri": agos("the sign-in callback URL AGOS's own OAuth flow uses"),
    "composio_key:*": agos(
        "a workspace's Composio key, sealed (Composio is AGOS's per-workspace app login)",
        "H: website/docs/user-guide/features/tool-gateway.md:124-142 (Nous-account wide)",
    ),
    "playbooks.written.*": agos("hashes of the playbook files AGOS last wrote (its own files)"),
    "general.env_names": agos("extra key names saved from General Settings (which keys it owns)"),
    "hermes_contract_told:*": agos(
        "which broken-Hermes-internals alerts the owner was already told (contract_alert)"
    ),
    "hermes.effort.*": agos(
        "a conversation's reasoning effort, which a restarted gateway forgets",
        "H: gateway/session_state.py:229, gateway/run_config_loaders.py:191 (memory only)",
    ),
    "hermes.own_command.*": agos(
        "when AGOS ran one of Hermes's commands in a conversation, so its answer isn't shown as the agent's"
    ),
    "group.next_to.*": agos("the member the owner's next group message goes to (15 minutes)"),
    "telegram.team_group.*": agos("the owner's choice of team group per workspace"),
    "moved.hook_guard": agos(
        "done-mark of the one move of plugins.hook_callback_timeout from 925047d's 0 to "
        "Hermes's cap (actions/hermes_managed.move_hook_guard), so his own later choice stays",
        "H: hermes_cli/config.py (a config value carries no record of who wrote it)",
    ),
    "moved.spill_cap": agos(
        "done-mark of the one unset of the hooks.output_spill.max_chars AGOS forced "
        "(actions/library.move_spill_cap), so a value the owner sets later stays",
        "H: tools/hook_output_spill.py:24 (Hermes's default, 10,000)",
    ),
    # -- MOVE_ONCE: read only to move into Hermes (or drop), then deleted
    "telegram.groups.*": move(
        "AGOS's old note of group and topic names Hermes's directory lacked, moved into "
        "the root's channel_aliases.json by hermes_channel.move_group_names at start "
        "(and by the Channels page's read)",
        "H: gateway/channel_directory.py:65 _apply_channel_aliases (channel_aliases.json)",
    ),
    "telegram.off.move.*": move(
        "a bot AGOS had turned off itself (the dropped channel_connections.enabled), moved "
        "by hermes_channel.move_old_switches",
        "config.yaml platforms.telegram.enabled (H: gateway/config_env.py:184 _enable_from_env)",
    ),
    "tools.services": move(
        "the old per-toolset service choice, moved by tool_services.move_old_setting",
        "each profile's config.yaml (H: hermes_cli/tools_config_providers.py:799)",
    ),
    "models.fallback_providers": move(
        "the old fallback chain, moved by hermes_fallback.move_old_setting",
        "config.yaml fallback_providers",
    ),
    "hermes.model.*": move(
        "the old /model told per conversation, moved by hermes_channel.move_old_models",
        "H: gateway/session.py:467 PERSISTABLE_MODEL_OVERRIDE_KEYS",
    ),
    "chats.model.move.*": move(
        "the old chats.model picks, moved by hermes_channel.move_old_models",
        "H: gateway/session.py:467 /model --session",
    ),
    "owner.timezone": move(
        "read only by the leftovers archive before migration 101 deleted it",
        "config.yaml timezone (actions/owner_time.py)",
    ),
    "channels.hermes_replies_since": move(
        "the old relay's start mark, deleted by member_topics.sync_all",
        "gateway.profile_routes (Hermes routes the member topics)",
    ),
    "workspace.name.move.*": move(
        "a workspace's name Hermes hasn't taken yet (a new workspace before its first "
        "sync, a rename, or an old row), moved and deleted by actions/engine.move_name",
        "the root profile's profile.yaml display_name (H: hermes_cli/profiles.py:958 "
        "write_profile_meta; :2415 rename_profile sets it for a root's own profile)",
    ),
    "workspace.description.move.*": move(
        "a workspace's description Hermes hasn't taken yet (an old row, or the engine "
        "was off), moved and deleted by actions/engine.move_description",
        "the root profile's profile.yaml description (H: hermes_cli/profiles.py:958 "
        "write_profile_meta)",
    ),
    "mcp_token:*": agos(
        "a workspace's MCP token (Settings → Connections, step 59), sealed with AGOS's "
        "master key: an outside assistant (Claude Desktop, Codex) calls this workspace's "
        "tools over MCP with it, and with it only this workspace",
        "H: mcp_serve.py (`hermes mcp serve`: stdio only, conversations and approvals, no "
        "plugin tools, no token)",
    ),
    "tool_keys.*": agos(
        "Workspace → Keys: per key NAME only the app's name as the owner typed it and "
        "when it was saved and last tested (display data). The key itself is one line "
        "of the root's .env (Hermes's save_env_value), the list of names is the root's "
        "terminal.env_passthrough; AGOS keeps neither the value nor any part of it",
        "H: hermes_cli/config.py save_env_value (the value); tools/env_passthrough.py "
        "_load_config_passthrough (the names); no label or date per .env line",
    ),
    "folders.move.*": move(
        "the dropped workspace_folders rows, put into Hermes by the next sync and deleted",
        "config.yaml terminal.docker_volumes (actions/engine.py _grants)",
    ),
}

# What a wildcard key's `*` is. Every `*` key above is classified, so a purged
# workspace takes every key of itself and of its chats with it
# (db/workspaces.purge_deleted), and keys whose id no longer exists are moved to
# the backups folder at start (db/orphan_keys.sweep). A chat key's id may carry
# the `agos:` session prefix (actions/hermes_channel.py EFFORT_KEY and friends).
# tests/test_ownership.py fails when a `*` key is missing here.
WILDCARD_IDS: dict[str, str] = {
    "office.*": "workspace",
    "skill_requests.*": "workspace",
    "review.*": "workspace",
    "work_hours.*": "workspace",
    "work_shift.*": "workspace",
    "board.views.*": "workspace",
    "founder.*": "workspace",
    "threads.seen.*": "workspace",
    "card.tokens.answered.*": "workspace",
    "digest.held.*": "workspace",
    "errors.hermes_seen.*": "workspace",
    "composio_key:*": "workspace",
    "playbooks.written.*": "workspace",
    "hermes_contract_told:*": "global",  # a contract entry's name, never a row's id
    "hermes.effort.*": "chat",
    "hermes.own_command.*": "chat",
    "group.next_to.*": "chat",
    "telegram.team_group.*": "workspace",
    "telegram.groups.*": "workspace",
    "telegram.off.move.*": "workspace",
    "hermes.model.*": "chat",
    "chats.model.move.*": "chat",
    "workspace.name.move.*": "workspace",
    "workspace.description.move.*": "workspace",
    "folders.move.*": "workspace",
    "tool_keys.*": "workspace",
    "mcp_token:*": "workspace",
}


def unregistered(db: sqlite3.Connection) -> list[str]:
    """The app_settings keys a database holds that KEYS doesn't register (a key
    no code names any more, e.g. a live install's leftover): shown at core start and
    caught by tests/test_ownership.py on any database it is given."""
    exact = {k for k in KEYS if not k.endswith("*")}
    prefixes = tuple(k[:-1] for k in KEYS if k.endswith("*"))
    found = [str(r[0]) for r in db.execute("SELECT key FROM app_settings ORDER BY key")]
    return [k for k in found if k not in exact and not k.startswith(prefixes)]
