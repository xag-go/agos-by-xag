"""Hermes contract entries: helper scripts: the probe, gateways, cron jobs, the skills hub, catch-up.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _CATCH,
    _MODELS,
    _SETTINGS,
    _STOP,
    _TOOLS,
    _WRITES,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # The probe's YAML side starts in the profile's own home (a fresh one would make
    # Hermes build a dependency environment first) and points Hermes's gateway start
    # at the copy holding config.yaml alone inside the process: Hermes reads
    # HERMES_HOME when it is asked, never bound at its launch.
    _u(
        "hermes_constants",
        "get_process_hermes_home",
        "text",
        "engine",
        _SETTINGS + " (.env in use)",
        text='os.environ.get("HERMES_HOME", "").strip()',
    ),
    _u("hermes_cli.config", "load_env", "function", "engine", _SETTINGS + " (.env in use)"),
    # A probe run started while another start sets a brand-new root up is refused
    # with this line; it is asked again after the other run (engine.hermes
    # HERMES_SETTING_UP).
    _u(
        "pm.environments",
        "_require_own_dependencies",
        "text",
        "engine",
        _SETTINGS + " (.env in use, in a root not set up yet)",
        text='"no dependency environment is committed for this install"',
    ),
    _u(
        "hermes_cli.web_server_config",
        "_schema_with_dynamic_provider_options",
        "function",
        "engine",
        _SETTINGS,
    ),
    _u("hermes_cli.tools_config", "", "module", "engine", _TOOLS),
    _u(
        "hermes_cli.tools_config_post_setup", "_POST_SETUP_AUTH_READY", "constant", "engine", _TOOLS
    ),
    _u("hermes_cli.tools_config", "CONFIGURABLE_TOOLSETS", "constant", "engine", _TOOLS),
    _u("hermes_cli.tools_config", "TOOL_CATEGORIES", "constant", "engine", _TOOLS),
    _u("hermes_cli.tools_config", "_visible_providers", "function", "engine", _TOOLS, pos=2),
    _u(
        "hermes_cli.tools_config",
        "_detect_active_provider_index",
        "function",
        "engine",
        _TOOLS,
        pos=2,
    ),
    _u("hermes_cli.tools_config", "_is_provider_active", "function", "engine", _TOOLS, pos=2),
    _u("hermes_cli.tools_config", "_provider_env_ready", "function", "engine", _TOOLS, pos=1),
    _u("hermes_cli.tools_config", "apply_provider_selection", "function", "engine", _TOOLS, pos=3),
    _u(
        "hermes_cli.tools_config",
        "_post_setup_already_installed",
        "function",
        "engine",
        _TOOLS,
        pos=1,
    ),
    _u(
        "hermes_cli.commands_platforms",
        "telegram_menu_commands",
        "function",
        "engine",
        "AGOS's '/' list (what Telegram shows)",
        kw="max_commands",
    ),
    _u(
        "hermes_cli.commands_platforms",
        "telegram_menu_max_commands",
        "function",
        "engine",
        "AGOS's '/' list (what Telegram shows)",
    ),
    _u(
        "hermes_cli.webhook",
        "_mutate_subscriptions",
        "function",
        "engine",
        "an automation's webhook route and its 'Only if' lines",
        pos=1,
    ),
    # The heartbeat prompt (actions/heartbeat.py) tells a member to list its own
    # cards with `hermes kanban list --mine` ($HERMES_PROFILE as assignee).
    _u(
        "hermes_cli.kanban_parser",
        "list.mine",
        "text",
        "kanban",
        "a member's heartbeat: its own cards (actions/heartbeat.py)",
        text='_arg("--mine", action="store_true", help="Filter by $HERMES_PROFILE as assignee")',
    ),
    # The ticket on-ramp presets (actions/ticket_presets.py) rely on Hermes verifying
    # the senders' signatures: Linear's and GitHub's HMAC headers, a plain shared
    # secret header for a relay (Jira / Asana can't sign for Hermes).
    _u(
        "gateway.platforms.webhook",
        "_validate_signature.linear",
        "text",
        "engine",
        "ticket on-ramps: Linear's signed deliveries (actions/ticket_presets.py)",
        text='_header("linear-signature")',
    ),
    _u(
        "gateway.platforms.webhook",
        "_validate_signature.github",
        "text",
        "engine",
        "ticket on-ramps: GitHub's signed deliveries (actions/ticket_presets.py)",
        text='headers.get("X-Hub-Signature-256", "")',
    ),
    _u(
        "gateway.platforms.webhook",
        "_validate_signature.shared_secret",
        "text",
        "engine",
        "ticket on-ramps: a shared secret header for Jira / Asana relays",
        text='headers.get("X-Gitlab-Token", "")',
    ),
    _u(
        "gateway.drain_control",
        "write_drain_request",
        "function",
        "engine",
        "a quiet gateway stop (no 'restarting' note)",
        kw="principal suppress_notification",
    ),
    _u(
        "gateway.drain_control",
        "read_drain_request",
        "function",
        "engine",
        "a quiet gateway stop (no 'restarting' note)",
    ),
    _u(
        "gateway.drain_control",
        "clear_drain_request",
        "function",
        "engine",
        "a quiet gateway stop (no 'restarting' note)",
    ),
    # A mirrored /command's sender: Hermes's own public pairing check
    # (engine.pairing_approved, actions/telegram_people.lets_in).
    _u("gateway.pairing", "PairingStore", "class", "engine", "who may use the bot's /commands"),
    _u(
        "gateway.pairing",
        "PairingStore.is_approved",
        "method",
        "engine",
        "who may use the bot's /commands",
        pos=2,
    ),
    # AGOS's stop waits for Hermes's own stop budget (engine._QUIET_DRAIN; a broken
    # name only falls back to AGOS's STOP_WAIT_S).
    _u(
        "gateway.restart",
        "resolve_systemd_timeout_stop_sec",
        "function",
        "engine",
        _STOP,
        pos=2,
    ),
    _u("hermes_cli.gateway", "_get_restart_drain_timeout", "function", "engine", _STOP),
    _u("hermes_cli.gateway", "_get_cron_drain_timeout", "function", "engine", _STOP),
    _u(
        "hermes_cli.gateway",
        "get_service_name",
        "function",
        "engine",
        "starting / stopping a workspace's gateway service",
    ),
    _u(
        "hermes_cli.copilot_auth",
        "copilot_device_code_login",
        "function",
        "engine",
        "Copilot sign-in",
        kw="timeout_seconds",
    ),
    _u(
        "hermes_cli.auth",
        "clear_provider_auth",
        "function",
        "engine",
        "signing a provider out",
        pos=1,
    ),
    _u(
        "hermes_cli.inventory",
        "build_model_options_payload",
        "function",
        "engine",
        _MODELS,
        pos=1,
        kw="include_unconfigured refresh",
    ),
    _u("hermes_cli.inventory", "load_picker_context", "function", "engine", _MODELS),
    _u(
        "hermes_cli.main_provider_setup",
        "_main_model_reasoning_efforts",
        "function",
        "engine",
        _MODELS,
        pos=2,
    ),
    _u("hermes_cli.setup", "_current_reasoning_effort", "function", "engine", _MODELS, pos=1),
    _u(
        "agent.skill_utils",
        "parse_frontmatter",
        "function",
        "engine",
        "skills' name / description as Hermes reads them",
        pos=1,
    ),
    _u(
        "hermes_cli.env_loader",
        "load_hermes_dotenv",
        "function",
        "engine",
        "Settings → GitHub token status; " + _WRITES,
        kw="project_env",
    ),
    _u(
        "tools.skills_hub_github", "GitHubAuth", "class", "engine", "Settings → GitHub token status"
    ),
    _u(
        "tools.skills_hub_github",
        "GitHubAuth.auth_method",
        "method",
        "engine",
        "Settings → GitHub token status",
    ),
    _u(
        "tools.skills_hub_github",
        "GitHubAuth.rejected",
        "attr",
        "engine",
        "Settings → GitHub token status",
    ),
    _u(
        "tools.skills_hub_github",
        "GitHubSource",
        "class",
        "engine",
        "Settings → GitHub token status",
        pos=1,
    ),
    _u(
        "tools.skills_hub_github",
        "GitHubSource._github_get",
        "method",
        "engine",
        "Settings → GitHub token status",
        pos=1,
        kw="max_retries",
    ),
    # A hub skill lands in its workspace's own folder (skills/agos-library/<name>).
    _u(
        "hermes_cli.subcommands.skills",
        "",
        "text",
        "engine",
        "a workspace installs a skill from the web into its own folder",
        text='skills_install.add_argument("--category"',
    ),
    _u(
        "hermes_cli.telegram_managed_bot",
        "",
        "module",
        "engine",
        "making the workspace's Telegram bot from AGOS",
    ),
    _u(
        "hermes_cli.telegram_managed_bot",
        "create_pairing",
        "function",
        "engine",
        "making the workspace's Telegram bot from AGOS",
        kw="bot_name",
    ),
    _u(
        "hermes_cli.telegram_managed_bot",
        "poll_pairing_result_once",
        "function",
        "engine",
        "making the workspace's Telegram bot from AGOS",
        pos=2,
    ),
    _u(
        "hermes_cli.telegram_managed_bot",
        "TelegramPairing",
        "class",
        "engine",
        "making the workspace's Telegram bot from AGOS",
    ),
    _u("cron.jobs", "", "module", "engine", "an automation's runs, outputs and pause"),
    _u(
        "cron.jobs",
        "get_cron_output_dir",
        "function",
        "engine",
        "an automation's runs, outputs and pause",
    ),
    _u(
        "cron.jobs",
        "effective_job_state",
        "function",
        "engine",
        "an automation's runs, outputs and pause",
        pos=1,
    ),
    _u(
        "cron.jobs",
        "get_job",
        "function",
        "engine",
        "an automation's runs, outputs and pause",
        pos=1,
    ),
    _u(
        "cron.jobs",
        "pause_job",
        "function",
        "engine",
        "an automation paused with its reason",
        pos=1,
        kw="reason",
    ),
    _u(
        "cron.jobs",
        "parse_schedule",
        "function",
        "engine",
        "checking an automation's schedule",
        pos=1,
    ),
    # The post-hire review (actions/hire_review.py): a one-shot job made with an ISO
    # time as its schedule, delivered to the 'agos' platform; `[SILENT]` sends nothing.
    _u(
        "cron.jobs",
        "parse_schedule.once",
        "text",
        "engine",
        "the post-hire review is a one-shot job at an ISO time",
        text='"kind": "once",',
    ),
    _u(
        "cron.scheduler",
        "SILENT_MARKER",
        "text",
        "engine",
        "the post-hire review sends nothing when the member is gone ([SILENT])",
        text='SILENT_MARKER = "[SILENT]"',
    ),
    _u(
        "cron.jobs",
        "_normalize_failure_deliver",
        "text",
        "engine",
        "--deliver takes the same platform names as --failure-deliver ('agos')",
        text="failure_deliver shares deliver's value grammar",
    ),
    # A run missed while the server was off (actions/catch_up.py): Hermes's own switch,
    # its schedule math and grace, and the job fields AGOS tells a missed run from.
    _u(
        "cron.jobs",
        "_fast_forward_missed_recurring",
        "text",
        "engine",
        _CATCH,
        text='_cron_config_number("catch_up_missed", True',
    ),
    _u("cron.jobs", "compute_next_run", "function", "engine", _CATCH, pos=2),
    _u("cron.jobs", "_compute_grace_seconds", "function", "engine", _CATCH, pos=1),
    _u("cron.jobs", "_schedule_cadence_seconds", "function", "engine", _CATCH, pos=1),
    _u("cron.jobs", "last_dispatch", "text", "engine", _CATCH, text='"scheduled_at": next_run,'),
    _u(
        "cron.jobs",
        "trigger_job",
        "text",
        "engine",
        _CATCH,
        text='"manual_run_at": manual_run_at,',
    ),
    _u("cron.executions", "", "module", "engine", "an automation's runs, outputs and pause"),
    _u(
        "cron.executions",
        "list_executions",
        "function",
        "engine",
        "an automation's runs",
        kw="job_id limit",
    ),
    _u(
        "agent.redact",
        "redact_sensitive_text",
        "function",
        "engine",
        "secrets hidden in what AGOS shows; keys masked in the owner's own messages (web "
        "and Telegram, hermes_plugin/agos_guard/keys.py) and found by the Secrets check",
        pos=1,
        kw="force redact_url_credentials",
    ),
)
