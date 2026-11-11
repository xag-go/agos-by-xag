"""Hermes contract entries: the agos-guard plugin: its guard, the plugin context and the hooks it registers.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _ASK,
    _CHATS,
    _EST,
    _EYES,
    _FOUNDER,
    _HOLD,
    _KAN,
    _MENU,
    _ONLY_IF,
    _PROPOSE,
    _QUESTION,
    _REVIEW,
    _ROOMS,
    _RULES,
    _TG,
    _USAGE,
    _VOICE,
    Use,
    _hooks,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # ---- guard: agos_guard/__init__.py (inside Hermes, before every tool call) ----
    _u("hermes_constants", "get_hermes_home", "function", "guard", _RULES),
    _u("hermes_constants", "get_default_hermes_root", "function", "voice", _VOICE),
    _u(
        "tools.file_tools_read_tracking",
        "notify_other_tool_call",
        "function",
        "guard",
        "every read sees the real file (no stale 'not found' / 'not changed')",
        pos=1,
    ),
    _u(
        "agent.skill_utils",
        "is_external_skill_path",
        "function",
        "guard",
        "shared library skills stay unchanged",
        pos=1,
    ),
    _u(
        "tools.skill_manager_tool",
        "_find_skill",
        "function",
        "guard",
        "shared library skills stay unchanged",
        pos=1,
    ),
    _u("tools.approval", "", "module", "guard", _ASK),
    _u("tools.approval", "is_approval_bypass_active", "function", "guard", _ASK),
    _u("tools.approval", "get_current_session_key", "function", "guard", _ASK),
    _u("tools.approval", "is_approved", "function", "guard", _ASK, pos=2),
    _u("tools.approval", "_presence", "function", "guard", _ASK, pos=1),
    _u(
        "tools.approval",
        "_human_decision",
        "function",
        "guard",
        _ASK,
        pos=1,
        kw="command description pattern_key pattern_keys session_key approval_callback is_cli is_gateway is_ask",
    ),
    _u("tools.approval", "_ACTION_GATE", "constant", "guard", _ASK),
    _u(
        "tools.approval",
        "resolve_gateway_approval",
        "function",
        "bridge",
        "Allow / Deny answered in AGOS",
        pos=2,
    ),
    _u(
        "gateway.session_context",
        "get_session_env",
        "function",
        "guard",
        "which chat / cron run a tool call is in",
        pos=2,
    ),
    _u(
        "hermes_cli.profiles",
        "get_active_profile_name",
        "function",
        "guard",
        "session_search stays in its own workspace",
    ),
    _u(
        "agent.runtime_cwd",
        "",
        "text",
        "guard",
        "the sandbox's /workspace warning stays out of the log",
        text="%s does not exist: %s",
    ),
    # ---- the plugin context Hermes gives register(ctx) ----
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_hook",
        "method",
        "plugin",
        "every AGOS hook in Hermes",
        pos=2,
    ),
    _u("hermes_cli.plugins", "PluginContext.register_cli_command", "method", "kanban", _EST, pos=4),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_middleware",
        "method",
        "plugin",
        "the owner's yes under Full access, asked outside Hermes's hook timeout",
        pos=2,
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_system_prompt_section",
        "method",
        "plugin",
        "the owner's rules for every workspace in each session's prompt",
        pos=2,
        kw="max_chars",
    ),
    # Made from Hermes's _SCOPED_PROVIDER_REGISTRARS table (no def to read).
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_transcription_provider",
        "text",
        "voice",
        _VOICE,
        text='("register_transcription_provider", "transcription_provider"',
    ),
    # A group or topic name Hermes's directory lacks: its own aliases file, laid over
    # the directory on every build and read (engine/hermes_directory.write_aliases).
    # The Dashboard's usage: Hermes's own usage analytics (the dashboard's
    # GET /api/analytics/usage) of the root and each member (engine.hermes_usage).
    # SessionDB read-only: also a chat's routing entry (engine.hermes_lanes).
    _u("hermes_state", "SessionDB", "class", "engine", _USAGE, kw="db_path read_only"),
    _u("agent.insights", "InsightsEngine", "class", "engine", _USAGE),
    _u(
        "hermes_cli.web_server_sessions",
        "_open_session_db_for_profile",
        "function",
        "engine",
        _USAGE,
        pos=1,
        kw="read_only",
    ),
    _u(
        "hermes_cli.web_routers.analytics",
        "_get_usage_analytics",
        "function",
        "engine",
        _USAGE,
        pos=2,
    ),
    # A chat hidden in AGOS: Hermes's own public per-session route (engine.archive_sessions).
    _u(
        "gateway.platforms.api_server",
        "",
        "text",
        "engine",
        "a chat hidden in AGOS (Hermes's PATCH /api/sessions/{id})",
        text='("PATCH", "/api/sessions/{session_id}", self._handle_patch_session)',
    ),
    _u(
        "gateway.channel_directory",
        "_apply_channel_aliases",
        "function",
        "channels",
        "Telegram group and topic names Hermes's directory lacks (channel_aliases.json)",
        pos=1,
    ),
    _u(
        "gateway.channel_directory",
        "_aliases_path",
        "text",
        "channels",
        "Telegram group and topic names Hermes's directory lacks (channel_aliases.json)",
        text='"channel_aliases.json"',
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.current_cron_execution",
        "method",
        "guard",
        "'Ask me' refused in a scheduled run",
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_tool",
        "method",
        "plugin",
        "the Co-Founder's agos_action / agos_capability tools",
        kw="name toolset schema handler description emoji",
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_platform",
        "method",
        "bridge",
        _CHATS,
        kw="name label adapter_factory check_fn is_connected env_enablement_fn allowed_users_env "
        "cron_deliver_env_var emoji display_tier platform_hint",
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_command",
        "method",
        "bridge",
        _MENU,
        pos=2,
        kw="description",
    ),
    _u(
        "hermes_cli.plugins",
        "PluginContext.register_telegram_handler",
        "method",
        "bridge",
        _TG,
        pos=1,
    ),
    _u("hermes_cli.plugins", "PluginContext.platform_actions", "attr", "bridge", _EYES),
    _u("hermes_cli.plugins_ledger", "PluginRegistration.dispose", "method", "bridge", _MENU),
    _u(
        "hermes_cli.platform_actions",
        "PlatformActions.add_reaction",
        "method",
        "bridge",
        _EYES,
        pos=4,
    ),
    # ---- hooks the plugin registers (Hermes's VALID_HOOKS) ----
    *_hooks("pre_tool_call post_tool_call", _RULES + "; the live view of a tool call"),
    *_hooks(
        "pre_llm_call post_llm_call on_session_end agent_loop_stopped",
        "an answer's turn in the AGOS chat",
    ),
    *_hooks(
        "on_stream_delta on_stream_end post_api_request", "the live answer; a card's token count"
    ),
    *_hooks("pre_gateway_dispatch post_gateway_admission transform_llm_output", _TG),
    *_hooks("pre_approval_request post_approval_response", "Allow / Deny cards shown in AGOS"),
    *_hooks("kanban_task_claimed kanban_task_completed", _KAN),
    # A card blocked for the owner (an Autonomy ask, a proposal) is told to AGOS
    # (agos_guard blocked_for_owner -> kanban_asks.settle / proposals.arrived).
    *_hooks("kanban_task_blocked", _PROPOSE),
    # Proposals: a second needs_input block of the SAME card routes it to triage
    # (the unblock-loop breaker), so a revised proposal is a NEW card
    # (engine/proposals.py); the agent blocks with `kanban block --kind needs_input`.
    _u("hermes_cli.kanban_db", "BLOCK_RECURRENCE_LIMIT", "constant", "kanban", _PROPOSE),
    _u(
        "hermes_cli.kanban_db",
        "_route_block",
        "text",
        "kanban",
        _PROPOSE,
        text="recurrences = prev_recurrences + 1 if prev_kind == kind else 1",
    ),
    _u(
        "hermes_cli.kanban_parser",
        "block",
        "text",
        "kanban",
        _PROPOSE,
        text='_arg("--kind", choices=sorted(kb.VALID_BLOCK_KINDS),',
    ),
    _u(
        "hermes_cli.kanban_db",
        "unblock_task",
        "text",
        "kanban",
        _PROPOSE,
        text="# ``block_kind``/``block_recurrences`` deliberately survive the unblock:",
    ),
    # Step 45, a typed question asked while working a card (agos_guard/asks.py): the
    # owning run links the question card as its parent (Hermes refuses the link from
    # anyone else while the child runs), then blocks as a `dependency` (never counted
    # by the loop breaker); Hermes wakes the card when the parent completes and shows
    # the parent's result in the worker's context.
    _u(
        "hermes_cli.kanban_db",
        "link_tasks",
        "function",
        "kanban",
        _QUESTION,
        pos=3,
        kw="expected_child_run_id",
    ),
    _u(
        "hermes_cli.kanban_db",
        "link_tasks",
        "text",
        "kanban",
        _QUESTION,
        text='or child["current_run_id"] != expected_child_run_id',
    ),
    # (one pinned line: the dependency re-kind; the classify-in-place of a born-blocked
    # card is the same function's `status == "blocked"` branch.)
    _u(
        "hermes_cli.kanban_db",
        "block_task",
        "text",
        "kanban",
        _QUESTION,
        text='if kind == "dependency" and _parents_satisfied(conn, task_id):',
    ),
    _u("hermes_cli.kanban_db", "_ctx_parent_results", "function", "kanban", _QUESTION, pos=4),
    # AGOS makes a proposal / question card born blocked (`create --initial-status
    # blocked`, untyped) so the dispatcher never claims it, then types it in place
    # with `kanban block --kind needs_input <reason>` (block_task's classify path).
    _u(
        "hermes_cli.kanban_parser",
        "create",
        "text",
        "kanban",
        _QUESTION,
        text='_arg("--initial-status", choices=sorted(kb.VALID_INITIAL_STATUSES), default="running",',
    ),
    _u("hermes_cli.kanban_db", "VALID_INITIAL_STATUSES", "constant", "kanban", _QUESTION),
    _u(
        "hermes_cli.kanban_db",
        "block_task",
        "function",
        "kanban",
        _PROPOSE,
        pos=2,
        kw="reason kind expected_run_id",
    ),
    _u("hermes_cli.kanban", "_cmd_link", "function", "kanban", _QUESTION, pos=1),
    # The owner's items of plans accepted before they became Founder tasks
    # (actions/today.py) are cards with no assignee: Hermes's dispatcher leaves an
    # unassigned ready card alone.
    _u(
        "hermes_cli.kanban_db_dispatch",
        "_dispatch_ready.unassigned",
        "text",
        "kanban",
        "Vision: the owner's You list (unassigned cards) is never run by a worker",
        text='result.skipped_unassigned.append(row["id"])',
    ),
    # Subtree holds (actions/holds.py): `kanban schedule` parks a todo / ready card
    # (not dispatchable until `kanban unblock`); `kanban archive` ends open cards.
    _u("hermes_cli.kanban", "_cmd_schedule", "function", "kanban", _HOLD, pos=1),
    _u(
        "hermes_cli.kanban_db",
        "schedule_task.statuses",
        "text",
        "kanban",
        _HOLD,
        text="AND status IN ('todo', 'ready', 'running', 'blocked')",
    ),
    _u("hermes_cli.kanban_db", "unblock_task", "function", "kanban", _HOLD, pos=2),
    # A card blocked for a teammate is handed over with `kanban assign` + `kanban unblock`.
    _u("hermes_cli.kanban", "_cmd_assign", "function", "kanban", _QUESTION, pos=1),
    # Step 52, review stages / plan first (agos_guard/review.py takes each step on the
    # board with the agent's own run; actions/reviews.py the owner's, by the CLI).
    _u(
        "hermes_cli.kanban_db",
        "request_review",
        "function",
        "kanban",
        _REVIEW,
        pos=2,
        kw="summary reviewer expected_run_id with_reason",
    ),
    # The review handoff records the run's profile as the implementer: a reviewer's
    # run hands the card back to the implementer before the next stage.
    _u(
        "hermes_cli.kanban_db",
        "request_review.implementer",
        "text",
        "kanban",
        _REVIEW,
        text='implementer = arow["profile"] if arow else None',
    ),
    _u(
        "hermes_cli.kanban_db",
        "request_changes",
        "function",
        "kanban",
        _REVIEW,
        pos=2,
        kw="reason expected_run_id",
    ),
    _u(
        "hermes_cli.kanban_db",
        "complete_task",
        "function",
        "kanban",
        _REVIEW,
        pos=2,
        kw="summary result expected_run_id",
    ),
    _u(
        "hermes_cli.kanban_db",
        "schedule_task",
        "function",
        "kanban",
        _REVIEW,
        pos=2,
        kw="reason expected_run_id",
    ),
    _u("hermes_cli.kanban_db", "assign_task", "function", "kanban", _REVIEW, pos=3),
    _u("hermes_cli.kanban_db", "add_comment", "function", "kanban", _REVIEW, pos=4),
    # The owner's stage: the card in review assigned to `owner`, a name no profile
    # has, which the dispatcher never spawns.
    _u(
        "hermes_cli.kanban_db_dispatch",
        "_dispatch_lane_task",
        "text",
        "kanban",
        _REVIEW,
        text="result.skipped_nonspawnable.append(task_id)",
    ),
    _u("hermes_cli.kanban", "_cmd_reopen_review", "function", "kanban", _REVIEW, pos=1),
    # The Founder (actions/founder.py): a card assigned to `founder`, a name no
    # profile has, is skipped by the dispatcher (never claimed, never reclaimed or
    # stale) and still counts as tick activity, so the tick hook fires and AGOS tells
    # him once its parents are done. The Co-Founder's kanban_create takes any assignee.
    _u(
        "hermes_cli.kanban_db_dispatch",
        "_dispatch_lane_task.founder",
        "text",
        "kanban",
        _FOUNDER,
        text="if profile_exists is not None and not profile_exists(assignee):",
    ),
    _u(
        "hermes_cli.kanban_db",
        "_TICK_ACTIVITY_FIELDS.founder",
        "text",
        "kanban",
        _FOUNDER,
        text='"skipped_nonspawnable",',
    ),
    _u(
        "tools.kanban_tools",
        "_handle_create.founder",
        "text",
        "kanban",
        _FOUNDER,
        text="assignee=str(assignee)",
    ),
    # His Request changes rides on reopen-review's reason: the marker may follow this.
    _u(
        "hermes_cli.kanban",
        "_cmd_reopen_review.reason",
        "text",
        "kanban",
        _REVIEW,
        text='f"CHANGES REQUESTED: {reason}"',
    ),
    _u("hermes_cli.kanban", "_cmd_edit", "function", "kanban", _REVIEW, pos=1),
    *_hooks("on_room_member_activity", _ROOMS),
    # A step's "Only if" lines, before its worker's first model call (agos_guard
    # step_gate.py): the saved lines and the run's file beside the board, decided at
    # the card's first attempt only (its run history), a check in the worker's own
    # sandbox, then Hermes's pre_llm_call veto where it has one (newer Hermes; its
    # marker is looked up, not pinned) or the done card's worker ending itself.
    _u("hermes_cli.kanban_db", "kanban_db_path", "function", "kanban", _ONLY_IF),
    _u("hermes_cli.kanban_db", "list_runs", "function", "kanban", _ONLY_IF, pos=2),
    # (terminal_tool's command / timeout / task_id / workdir: uses_engine_apps.py)
    _u("agent.turn_context", "", "module", "hooks", _ONLY_IF),
    _u("tools.terminal_tool_lifecycle", "cleanup_vm", "function", "guard", _ONLY_IF, pos=1),
)
