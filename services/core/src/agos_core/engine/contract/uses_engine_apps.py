"""Hermes contract entries: helper scripts: masking, backups, MCP apps, pipelines, skills that grow.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _FIND,
    _GROW,
    _HOURS,
    _MCP,
    _PIPE,
    _SERVICES,
    Use,
    _hooks,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # A key's kind in the Secrets check is the head Hermes's own mask keeps (keys.py).
    _u(
        "agent.redact",
        "_mask_token.shape",
        "text",
        "engine",
        "the Secrets check names a key by the head Hermes's mask shows (sk-or-… key)",
        text="mask_secret(token, head=6, tail=4, floor=18)",
    ),
    # His Telegram message masked before Hermes keeps it: the plugin's
    # pre_gateway_dispatch answers {"action": "rewrite", "text": …}.
    _u(
        "gateway.run_inbound",
        "GatewayInboundMixin._hm_pre_gateway_dispatch_hook.rewrite",
        "text",
        "bridge",
        "a key in his Telegram message is masked before Hermes keeps it",
        text='if _action == "rewrite":',
    ),
    # No key in a backup: which files of a Hermes home hold credentials is Hermes's
    # own list (actions/backups.py hermes_private, engine/backup.py).
    _u(
        "hermes_cli.profiles",
        "profile_path_is_private",
        "function",
        "engine",
        "backups hold no key: Hermes's own credential stores are left out",
        pos=1,
    ),
    _u(
        "hermes_cli.profile_distribution",
        "EnvRequirement",
        "class",
        "templates",
        "a workspace bundle's env_requires (Settings → Import asks for each key; "
        "engine/bundle.py writes Hermes's distribution entry shape)",
        kw="name description required default",
    ),
    _u(
        "hermes_cli.profiles",
        "_EXPORT_CREDENTIAL_FILES",
        "constant",
        "templates",
        "Settings → Export reads none of the files Hermes's own profile export drops "
        "(auth.json, .env, …): only named fields (actions/portability.py)",
    ),
    _u("agent.account_usage", "", "module", "engine", "Settings → Usage: Claude's limits"),
    _u(
        "agent.estop",
        "SENTINEL_NAME",
        "constant",
        "engine",
        "the usage pause is `hermes pause`: AGOS reads a root's ESTOP sentinel to "
        "resume only its own pause (actions/account_pause.py)",
    ),
    _u(
        "agent.estop",
        "",
        "text",
        "engine",
        "the sentinel's body keeps the pause's reason (account_pause.paused_by_agos)",
        text='"reason"',
    ),
    _u(
        "hermes_cli.update_inventory",
        "print_update_plan",
        "function",
        "engine",
        "Check Update reads the release `hermes update --plan` names "
        "(engine/hermes_update.offered)",
        pos=1,
    ),
    _u(
        "hermes_cli.update_inventory",
        "",
        "text",
        "engine",
        "the plan's Install line names the release and its sha, the words "
        "engine/hermes_update._PLAN reads",
        text='"  Install: {plan.install_method}"',
    ),
    _u(
        "hermes_cli.banner",
        "",
        "text",
        "engine",
        "`hermes --version`'s line names the version and the local sha, the words "
        "engine/hermes_update._VERSION reads (also limits.py's probe)",
        text='"Hermes Agent v{get_version_info().derived_version} ({RELEASE_DATE})"',
    ),
    _u(
        "agent.account_usage",
        "_get_json",
        "function",
        "engine",
        "Settings → Usage: Claude's limits",
        pos=2,
        kw="timeout",
    ),
    _u(
        "agent.anthropic_credentials",
        "_is_oauth_token",
        "function",
        "engine",
        "Settings → Usage: Claude's limits",
        pos=1,
    ),
    _u(
        "agent.anthropic_credentials",
        "resolve_anthropic_token",
        "function",
        "engine",
        "Settings → Usage: Claude's limits",
    ),
    _u(
        "agent.credential_pool",
        "load_pool",
        "function",
        "engine",
        "Settings → Usage: Claude's limits",
        pos=1,
    ),
    _u(
        "agent.credential_pool",
        "CredentialPool.select",
        "method",
        "engine",
        "Settings → Usage: Claude's limits",
    ),
    _u(
        "agent.credential_pool",
        "PooledCredential.access_token",
        "attr",
        "engine",
        "Settings → Usage: Claude's limits",
    ),
    _u(
        "hermes_cli.mcp_catalog", "list_catalog", "function", "engine", "Apps: Hermes's MCP catalog"
    ),
    *[
        _u(
            "hermes_cli.mcp_catalog",
            f"CatalogEntry.{a}",
            "attr",
            "engine",
            "Apps: Hermes's MCP catalog",
        )
        for a in ("name", "description", "source", "transport", "auth", "manifest_path", "tools")
    ],
    _u(
        "hermes_cli.mcp_config",
        "_probe_single_server",
        "function",
        "engine",
        _MCP,
        pos=2,
        kw="connect_timeout",
    ),
    _u("hermes_cli.mcp_config", "_oauth_tokens_present", "function", "engine", _MCP, pos=1),
    _u(
        "tools.mcp_dashboard_oauth",
        "DashboardOAuthFlow",
        "class",
        "engine",
        _MCP,
        kw="flow_id server_name profile hermes_home redirect_uri",
    ),
    _u(
        "tools.mcp_dashboard_oauth",
        "DashboardOAuthFlow.publish_authorization_url",
        "override",
        "engine",
        _MCP,
        accepts="url",
    ),
    _u(
        "tools.mcp_dashboard_oauth",
        "DashboardOAuthFlow.mark_error",
        "method",
        "engine",
        _MCP,
        pos=1,
        kw="cancelled",
    ),
    _u(
        "tools.mcp_dashboard_oauth",
        "DashboardOAuthFlow.deliver_callback",
        "method",
        "engine",
        _MCP,
        kw="code state error iss",
    ),
    _u("tools.mcp_dashboard_oauth", "dashboard_oauth_flow", "function", "engine", _MCP, pos=1),
    _u("tools.mcp_oauth", "force_interactive_oauth", "function", "engine", _MCP),
    _u(
        "tools.connectors.gateway.config",
        "connectors_available",
        "function",
        "engine",
        "Apps: Nous hosted apps",
    ),
    _u(
        "hermes_cli.nous_account",
        "get_nous_portal_account_info",
        "function",
        "engine",
        "Apps: Nous hosted apps",
    ),
    _u(
        "hermes_cli.nous_account",
        "NousPortalAccountInfo.logged_in",
        "attr",
        "engine",
        "Apps: Nous hosted apps",
    ),
    # Step 59. Pipeline rules: every card move Hermes tells its plugins, and its
    # dispatcher's tick for the moves no hook tells (agos_guard kanban_moved /
    # kanban_tick -> actions/pipelines.py).
    *_hooks("on_kanban_task_updated on_kanban_dispatch_tick", _PIPE),
    # A card's services: Hermes's own background process (agos_guard services.py).
    _u(
        "tools.terminal_tool",
        "terminal_tool",
        "function",
        "guard",
        _SERVICES + "; a step's Only if check (agos_guard step_gate.py)",
        kw="command background task_id persist_on_release timeout workdir",
    ),
    _u("tools.process_registry", "process_registry", "constant", "guard", _SERVICES),
    _u("tools.process_registry", "ProcessRegistry.get", "method", "guard", _SERVICES, pos=1),
    _u(
        "tools.process_registry",
        "ProcessRegistry.kill_process",
        "method",
        "guard",
        _SERVICES,
        pos=1,
    ),
    _u(
        "tools.terminal_tool_background",
        "spawn_background_process.result",
        "text",
        "guard",
        _SERVICES + " (the started process's id and pid)",
        text='"session_id": proc_session.id,\n                       "pid": proc_session.pid,',
    ),
    # Voice history: a Telegram voice note's words as Hermes keeps them (quoted).
    _u(
        "gateway.run_inbound",
        "_transcribe_one_clip.quoted",
        "text",
        "voice",
        "the voice note history (Settings → Connections → Voice notes)",
        text="return transcript, f'\"{transcript}\"'",
    ),
    # Step 63, skills that grow. The week's evidence is read from each member's Hermes
    # session store (read only): its messages' tool calls (the skills a session used,
    # its tool errors) since a time; a card's loaded skills from the board.
    _u(
        "hermes_state_common",
        "messages.tool_calls",
        "text",
        "engine",
        _GROW,
        text="    tool_call_id TEXT,\n    tool_calls TEXT,\n    tool_name TEXT,",
    ),
    _u(
        "hermes_state_common",
        "messages.timestamp",
        "text",
        "engine",
        _GROW,
        text="    timestamp REAL NOT NULL,",
    ),
    _u(
        "hermes_cli.kanban_db",
        "schema.tasks.skills",
        "text",
        "kanban",
        _GROW,
        text="    skills               TEXT,",
    ),
    # Find-skills reads Hermes's scan report and its hard-block words (an agent's
    # request is never forced; a forceable block asks the owner).
    _u(
        "tools.skills_guard",
        "format_scan_report.verdict",
        "text",
        "engine",
        _FIND,
        text="Verdict: {result.verdict.upper()}",
    ),
    _u(
        "hermes_cli.skills_hub",
        "_scan_block_message.hard_block",
        "text",
        "engine",
        _FIND,
        text="even with --force.",
    ),
    # One curator pass after a week that changed skills (its consolidation merges).
    _u(
        "hermes_cli.curator",
        "register_cli.run_background",
        "text",
        "engine",
        _GROW,
        text='_arg("--background", dest="background"',
    ),
    # Work hours (actions/work_hours.py): Hermes's own switches, per agent.
    _u(
        "hermes_cli.kanban_db_dispatch",
        "_dispatch_profile_allowlist.present",
        "text",
        "kanban",
        _HOURS + " (an agent left out of kanban.dispatch_profiles gets no worker)",
        text='if not isinstance(kanban, Mapping) or "dispatch_profiles" not in kanban:',
    ),
    _u(
        "cron.jobs",
        "resume_job",
        "function",
        "engine",
        _HOURS + " (`hermes cron resume` at check-in)",
        pos=1,
    ),
    _u(
        "cron.jobs",
        "resume_job.elapsed_kept_due",
        "text",
        "engine",
        _HOURS + " (a slot that passed off-hours runs at check-in, not lost)",
        text="that elapsed while paused kept due",
    ),
    _u(
        "cron.jobs",
        "trigger_job.manual_run_prompt",
        "text",
        "engine",
        _HOURS + " (the heartbeat's check-in wake carries a one-time prompt)",
        text='"manual_run_prompt": (extra_prompt or None),',
    ),
    _u(
        "gateway.platforms.api_server",
        "_handle_run_job.prompt",
        "text",
        "engine",
        _HOURS + " (Run now with a prompt: POST /api/jobs/{id}/run {prompt})",
        text='raw_prompt = body.get("prompt")',
    ),
    _u(
        "hermes_cli.kanban_parser",
        "reclaim",
        "text",
        "kanban",
        _HOURS + " (`kanban reclaim --reason` ends the worker at check-out + 2 h)",
        text='_cmd("reclaim", [_TASK_ID, _RECLAIM_REASON]',
    ),
    _u(
        "hermes_cli.kanban_parser",
        "comment.author",
        "text",
        "kanban",
        _HOURS + " (AGOS's check-out / check-in comments carry their own author)",
        text='_arg("--author", help="Author name (default: $HERMES_PROFILE or \'user\')")',
    ),
    _u(
        "hermes_cli.kanban_db",
        "build_worker_context.comments",
        "text",
        "kanban",
        _HOURS + " (the next run reads the where-I-stopped note on its card)",
        text="_ctx_comments(lines, list_comments(conn, task_id), now)",
    ),
    _u(
        "agent.estop",
        "paused_reply",
        "text",
        "engine",
        _HOURS + " (why not ESTOP: it pauses a whole root and answers new turns)",
        text="New work is on hold; run `hermes resume` to pick things back up.",
    ),
)
