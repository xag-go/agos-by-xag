"""Hermes contract entries: helper scripts AGOS runs in Hermes's runtime: keys, sandbox, settings, logins, lanes.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _ALIVE,
    _HELD,
    _KEYS,
    _MODELS,
    _ONE,
    _POOLS,
    _PROBE,
    _SETTINGS,
    _TOOL_SEARCH,
    _TOOLS,
    _WRITES,
    _WSKEYS,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # ---- engine: helper scripts AGOS runs in Hermes's runtime ----
    _u("hermes_cli.config", "save_env_value", "function", "engine", _KEYS, pos=2),
    _u("hermes_cli.config", "remove_env_value", "function", "engine", _KEYS, pos=1),
    _u(
        "hermes_cli.credential_lifecycle",
        "save_provider_env_credential",
        "function",
        "engine",
        _KEYS + " (.env + credential pool)",
        pos=2,
    ),
    _u(
        "hermes_cli.credential_lifecycle",
        "remove_provider_env_credential",
        "function",
        "engine",
        _KEYS + " (.env + credential pool)",
        pos=1,
    ),
    _u(
        "hermes_cli.web_routers.config_env",
        "validate_provider_credential",
        "function",
        "engine",
        _PROBE,
        pos=2,
    ),
    _u("hermes_cli.web_routers.config_env", "_CREDENTIAL_PROBES", "constant", "engine", _PROBE),
    _u("hermes_cli.web_models", "EnvVarUpdate", "class", "engine", _PROBE, kw="key value"),
    _u("hermes_cli.doctor_connectivity", "_probe_anthropic", "function", "engine", _PROBE),
    _u("hermes_cli.auth", "PROVIDER_REGISTRY", "constant", "engine", _MODELS + " (key names)"),
    _u("hermes_cli.config", "OPTIONAL_ENV_VARS", "constant", "engine", _MODELS + " (key names)"),
    # Workspace → Keys (engine/tool_keys.py SCRIPT): which names Hermes keeps for
    # itself, and whether its sandbox code hands a saved key to the tools.
    _u("hermes_cli.config", "env_write_refusal", "function", "engine", _WSKEYS, pos=2),
    # The sandbox broker (engine/sandboxd.py, ADR 0025 step 4) forwards exactly what
    # Hermes's docker backend asks for: its labels, its cap set, its container names
    # and its label filter. A change here = sandbox starts refused behind the broker.
    _u(
        "tools.environments.docker",
        "_BASE_SECURITY_ARGS",
        "constant",
        "engine",
        "the broker's allowed CapAdd set (sandboxd.ALLOWED_CAPS mirrors it)",
    ),
    _u(
        "tools.environments.docker",
        "_PRIVDROP_CAP_ARGS",
        "constant",
        "engine",
        "the broker's allowed CapAdd set (SETUID/SETGID when not run_as_host_user)",
    ),
    _u(
        "tools.environments.docker",
        "profile_label_filter",
        "text",
        "engine",
        "the broker scopes everything by Hermes's own hermes-profile container label",
        text='"--filter", f"label=hermes-profile=',
    ),
    _u(
        "tools.environments.docker",
        "sandbox_container_name",
        "text",
        "engine",
        "the broker allows only Hermes's own sandbox container names (hermes-<hex>)",
        text='container_name = f"hermes-',
    ),
    _u(
        "tools.environments.docker",
        "_build_security_args",
        "function",
        "engine",
        "what a Hermes create body carries (the broker's validate_create allows it)",
        pos=1,
        kw="run_exec snap_compat",
    ),
    _u(
        "tools.environments.local_env_policy",
        "_is_provider_env_blocklisted",
        "function",
        "engine",
        _WSKEYS + " (TOOLS_ names)",
        pos=1,
    ),
    _u(
        "tools.environments.local_env_policy",
        "_is_hermes_internal_secret",
        "function",
        "engine",
        _WSKEYS + " (TOOLS_ names)",
        pos=1,
    ),
    _u("tools.env_passthrough", "is_env_passthrough", "function", "engine", _WSKEYS, pos=1),
    _u(
        "tools.environments.remote_common",
        "resolve_passthrough_env",
        "function",
        "engine",
        _WSKEYS + " (the Test button)",
    ),
    _u("hermes_cli.config", "load_config", "function", "engine", _TOOLS + "; " + _MODELS),
    _u("hermes_cli.config", "save_config", "function", "engine", _TOOLS, pos=1),
    _u(
        "hermes_cli.profiles",
        "write_profile_meta",
        "function",
        "engine",
        "an agent's display name and a workspace's description in Hermes",
        pos=1,
        kw="display_name description description_auto",
    ),
    _u("toolsets", "TOOLSETS", "constant", "engine", _TOOLS),
    _u(
        "model_tools",
        "get_tool_definitions",
        "function",
        "engine",
        "which tools really work in a workspace",
        kw="enabled_toolsets quiet_mode",
    ),
    _u("hermes_cli.config_defaults", "", "module", "engine", _SETTINGS),
    _u("hermes_cli.kanban_workflow", "DEFAULT_WORKFLOW", "constant", "engine", _SETTINGS),
    _u("hermes_cli.kanban_workflow", "Workflow.to_dict", "method", "engine", _SETTINGS),
    _u(
        "hermes_cli.kanban_db_dispatch",
        "derive_default_max_in_progress",
        "function",
        "engine",
        _SETTINGS + " (members working at once while unset)",
    ),
    _u("hermes_cli.config", "DEFAULT_CONFIG", "constant", "engine", _SETTINGS),
    _u("agent.image_routing", "_VALID_MODES", "constant", "engine", _SETTINGS + " (image modes)"),
    # The token-cost switch for the Co-Founder's tools (actions/tool_search.py): Hermes's
    # Tool Search reads only `enabled` and `defer`, and a plugin tool always defers.
    _u(
        "tools.tool_search",
        "ToolSearchConfig.from_raw",
        "text",
        "engine",
        _TOOL_SEARCH,
        text='defer_raw = raw.get("defer")',
    ),
    _u(
        "tools.tool_search",
        "ToolSearchConfig.from_raw.enabled",
        "text",
        "engine",
        _TOOL_SEARCH,
        text='enabled=_tri_state(raw.get("enabled", "auto"))',
    ),
    _u(
        "tools.tool_search",
        "is_deferrable_tool_name",
        "text",
        "engine",
        _TOOL_SEARCH,
        text='toolset.startswith("mcp-") or toolset not in _DIRECT_SURFACE_TOOLSETS)',
    ),
    # The settings that are one value for every workspace: Hermes's managed scope,
    # a folder named per process (actions/hermes_managed.py).
    _u(
        "hermes_cli.managed_scope",
        "get_managed_dir",
        "text",
        "engine",
        _ONE,
        text='os.environ.get("HERMES_MANAGED_DIR"',
    ),
    _u("hermes_cli.managed_scope", "apply_managed_overlay", "function", "engine", _ONE, pos=1),
    _u("hermes_cli.managed_scope", "load_managed_env", "function", "engine", _SETTINGS + " (.env)"),
    _u(
        "utils",
        "fast_safe_load",
        "function",
        "engine",
        _SETTINGS + " (each profile as Hermes reads it)",
        pos=1,
    ),
    _u("hermes_cli.config", "_exit_if_key_managed", "function", "engine", _ONE, pos=2),
    # Several `hermes config set --force` / `config unset` in one Hermes process
    # (engine.config_writes, _CONFIG_WRITES): what the CLI runs around its writer.
    _u("hermes_cli._startup_fast", "", "module", "engine", _WRITES),
    _u("hermes_cli._startup_fast", "project_root_str", "function", "engine", _WRITES),
    _u("hermes_cli.config", "set_config_value", "function", "engine", _WRITES, pos=3),
    _u("hermes_cli.config", "unset_config_value", "function", "engine", _WRITES, pos=1),
    _u("hermes_cli.config", "_run_write_command", "function", "engine", _WRITES, pos=4),
    _u("hermes_cli.config", "_coerce_config_set_value", "function", "engine", _WRITES, pos=2),
    _u("hermes_cli.config", "_get_nested", "function", "engine", _WRITES, pos=2),
    _u("hermes_cli.config", "_MISSING", "constant", "engine", _WRITES),
    _u("hermes_cli.config", "_is_env_config_key", "function", "engine", _WRITES, pos=1),
    _u("hermes_cli.config", "_legacy_gateway_platforms_key", "function", "engine", _WRITES, pos=1),
    _u("hermes_cli.config", "_redirect_platform_display_key", "function", "engine", _WRITES, pos=1),
    _u("hermes_cli.config", "_terminal_env_value", "function", "engine", _WRITES, pos=1),
    _u(
        "hermes_cli.config", "terminal_config_env_var_for_key", "function", "engine", _WRITES, pos=1
    ),
    _u("hermes_cli.config", "get_config_path", "function", "engine", _WRITES),
    _u("hermes_cli.config", "is_managed", "function", "engine", _WRITES),
    _u(
        "hermes_cli.config",
        "require_readable_config_before_write",
        "function",
        "engine",
        _WRITES,
        pos=1,
    ),
    _u("hermes_cli.config_env_routing", "is_env_setting_key", "function", "engine", _WRITES, pos=1),
    # Step 32 (M2/P7): a root's sign-ins and pool, read by Hermes (engine.hermes_logins).
    _u(
        "hermes_cli.auth",
        "get_auth_status",
        "function",
        "engine",
        "whether a workspace's root can reach its model (`hermes auth status`)",
        pos=1,
    ),
    _u(
        "hermes_cli.auth",
        "read_credential_pool",
        "function",
        "engine",
        _POOLS + " (each entry's source and last status, every home)",
    ),
    _u(
        "hermes_cli.auth",
        "get_provider_auth_state",
        "function",
        "engine",
        "a root's own sign-ins (Hermes's saved provider state)",
        pos=1,
    ),
    _u(
        "agent.credential_persistence",
        "is_borrowed_credential_source",
        "function",
        "engine",
        "a root's own login vs one Hermes borrows from another program",
        pos=2,
    ),
    # Step 32 (P8): a chat's /yolo from Hermes's session routing index (engine.hermes_lanes).
    _u(
        "gateway.session",
        "SessionEntry.from_dict",
        "method",
        "engine",
        "a chat's own Full access (Hermes's /yolo on its routing entry)",
        pos=1,
    ),
    # What the lanes script reads, so AGOS asks it again only when it changed
    # (engine/hermes.py _routing_stamp: the rows read only).
    _u(
        "hermes_state_gateway",
        "SessionGatewayMixin.load_gateway_routing_entries",
        "text",
        "engine",
        "a chat's own Full access, asked from Hermes again when its routing changed",
        text='"SELECT session_key, entry_json FROM gateway_routing WHERE scope = ?"',
    ),
    _u(
        "hermes_state_common",
        "gateway_routing",
        "text",
        "engine",
        "a chat's own Full access, asked from Hermes again when its routing changed",
        text="CREATE TABLE IF NOT EXISTS gateway_routing (\n    scope TEXT NOT NULL DEFAULT '',\n"
        "    session_key TEXT NOT NULL,\n    entry_json TEXT NOT NULL,",
    ),
    # A bot's lamp asks Hermes's verdict again when the gateway's files say something
    # new; its heartbeat (the snapshot's updated_at, re-stamped by housekeeping) only
    # in the background (engine/hermes.py _gateway_files, gateway_shown).
    _u(
        "gateway.status",
        "runtime_status_is_stale",
        "text",
        "engine",
        _ALIVE + " (the lamps: asked again on the heartbeat in the background)",
        text='_marker_is_stale(record.get("updated_at") or "", ttl_s)',
    ),
    # Step 32 (C4): the voice providers' select Hermes defines but its walk skips.
    _u(
        "hermes_cli.web_server_config",
        "_SCHEMA_OVERRIDES",
        "constant",
        "engine",
        _SETTINGS + " (Voice notes: Hermes's speech-to-text providers)",
    ),
    _u(
        "hermes_cli.web_server_config",
        "_custom_provider_options",
        "function",
        "engine",
        _SETTINGS + " (Voice notes: Hermes's speech-to-text providers)",
        pos=3,
    ),
    # Step 32 (M1): which values are secrets is Hermes's own masker's answer.
    _u(
        "hermes_cli.config",
        "redact_config_value",
        "function",
        "engine",
        _SETTINGS + " (secrets hidden as Hermes hides them)",
        pos=1,
    ),
    _u(
        "hermes_cli.config",
        "_is_secret_config_key",
        "function",
        "engine",
        _SETTINGS + " (which keys and .env names are secrets)",
        pos=1,
    ),
    _u("hermes_cli.config", "_EXTRA_ENV_KEYS", "constant", "engine", _SETTINGS + " (.env)"),
    _u(
        "hermes_cli.web_routers.config_env",
        "_catalog_provider_env_metadata",
        "function",
        "engine",
        _SETTINGS + " (.env provider key names)",
    ),
    _u("tools.write_approval", "list_pending", "function", "engine", _HELD, pos=1),
    _u("tools.write_approval", "write_approval_enabled", "function", "engine", _HELD, pos=1),
    _u("tools.write_approval", "get_pending", "function", "engine", _HELD, pos=2),
    _u("tools.write_approval", "skill_pending_diff", "function", "engine", _HELD, pos=1),
    _u("tools.write_approval", "MEMORY", "constant", "engine", _HELD),
    _u("tools.write_approval", "SKILLS", "constant", "engine", _HELD),
)
