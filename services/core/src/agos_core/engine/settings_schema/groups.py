"""The groups the Hermes settings page shows (safety, cost, memory, Kanban, chats, runtime, .env, not used) and each key's group.
Must not: read Hermes.

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from agos_core.engine.fallback import KEY as _FALLBACK_KEY

__all__ = [
    "CHATS",
    "COST",
    "ENV",
    "GROUPS",
    "GROUP_BY_PREFIX",
    "KANBAN",
    "MEMORY",
    "NOT_USED",
    "NOT_USED_WHY",
    "RUNTIME",
    "SAFETY",
    "group_of",
]

SAFETY = "Safety & secrets"
COST = "Cost & quality"
MEMORY = "Memory & learning"
KANBAN = "Kanban & automations"
CHATS = "What shows in chats"
RUNTIME = "Runtime"
ENV = "Engine .env"
NOT_USED = "Not used by AGOS"
GROUPS = (SAFETY, COST, MEMORY, KANBAN, CHATS, RUNTIME, ENV, NOT_USED)

# Where a key is listed, by its section (Hermes's own dotted path). The longest
# prefix that matches wins; a section not here is "Runtime", so nothing is lost.
# Grouped like docs/audits (STEP27 area 3 (c)): what can hurt (safety), what costs
# money or changes answers, what the team learns, the board and schedules, what
# the owner sees in a chat, and how Hermes runs.
GROUP_BY_PREFIX: dict[str, str] = {
    # Safety, permissions and secrets
    "approvals": SAFETY,
    "command_allowlist": SAFETY,
    "security": SAFETY,
    "privacy": SAFETY,
    "secrets": SAFETY,
    "vault": SAFETY,
    "proxy": SAFETY,
    "auth": SAFETY,
    "plugins": SAFETY,
    "hooks_auto_accept": SAFETY,
    "hooks": SAFETY,
    "terminal": SAFETY,
    "network": SAFETY,
    "browser.allow_private_urls": SAFETY,
    "browser.auto_local_for_private_urls": SAFETY,
    "browser.allow_unsafe_evaluate": SAFETY,
    "browser.restrict_evaluate": SAFETY,
    "browser.use_real_profile": SAFETY,
    "delegation.subagent_auto_approve": SAFETY,
    "memory.write_approval": SAFETY,
    "skills.write_approval": SAFETY,
    "skills.guard_agent_created": SAFETY,
    "skills.inline_shell": SAFETY,
    "skills.inline_shell_timeout": SAFETY,
    "skills.trusted_project_dirs": SAFETY,
    "gateway.allow_all_users": SAFETY,
    "gateway.bot_loop_guard": SAFETY,
    "gateway.trust_env": SAFETY,
    "gateway.strict": SAFETY,
    "gateway.media_delivery_allow_dirs": SAFETY,
    "gateway.trust_recent_files": SAFETY,
    "gateway.trust_recent_files_seconds": SAFETY,
    "telegram.allowed_chats": SAFETY,
    "unauthorized_dm_behavior": SAFETY,
    "group_sessions_per_user": SAFETY,
    "platforms.telegram.extra.unauthorized_dm_behavior": SAFETY,
    "platforms.webhook": SAFETY,
    "computer_use.permission_mode": SAFETY,
    "computer_use.allow_unsigned_driver": SAFETY,
    # Models, cost and quality
    "model": COST,
    "model_context_length": COST,
    "providers": COST,
    "custom_providers": COST,
    "fallback": COST,
    _FALLBACK_KEY: COST,
    "credential_pool_strategies": COST,
    "model_overrides": COST,
    "provider_routing": COST,
    "prompt_caching": COST,
    "compression": COST,
    "auxiliary": COST,
    "delegation": COST,
    "agent": COST,
    "tool_loop_guardrails": COST,
    "tools": COST,
    "toolsets": COST,
    "platform_toolsets": COST,
    "tool_output": COST,
    "file_read_max_chars": COST,
    "web": COST,
    "x_search": COST,
    "moa": COST,
    "openrouter": COST,
    "bedrock": COST,
    "vertex": COST,
    "nous": COST,
    "model_catalog": COST,
    "models_dev": COST,
    "local_runtime": COST,
    "vision": COST,
    "mcp_servers": COST,
    # Memory, skills and learning
    "memory": MEMORY,
    "curator": MEMORY,
    "skills": MEMORY,
    "context": MEMORY,
    "context_file_max_chars": MEMORY,
    "context_file_read_timeout": MEMORY,
    "prefill_messages_file": MEMORY,
    "honcho": MEMORY,
    "personalities": MEMORY,
    # Team, Kanban and automations
    "kanban": KANBAN,
    "cron": KANBAN,
    "goals": KANBAN,
    "loops": KANBAN,
    "quick_commands": KANBAN,
    # What the owner sees on his channels
    "display": CHATS,
    "stt": CHATS,
    "tts": CHATS,
    "voice": CHATS,
    "streaming": CHATS,
    "human_delay": CHATS,
    "telegram": CHATS,
    "platform_hints": CHATS,
    "attachments": CHATS,
    "gateway.message_timestamps": CHATS,
    "gateway.max_inbound_media_bytes": CHATS,
    "hooks.output_spill": CHATS,
    "platforms.telegram": CHATS,
    # Runtime and operations (and every section not named here)
    "agent.agent_cache": RUNTIME,
    "agent.restart_drain_timeout": RUNTIME,
    "agent.cron_drain_timeout": RUNTIME,
    "agent.gateway_startup_restore_drain_timeout": RUNTIME,
    "agent.gateway_startup_warmup_timeout": RUNTIME,
    "gateway": RUNTIME,
    "sessions": RUNTIME,
    "checkpoints": RUNTIME,
    "bot_desktop": RUNTIME,
    "browser": RUNTIME,
    "computer_use": RUNTIME,
    "code_execution": RUNTIME,
    "lsp": RUNTIME,
    "logging": RUNTIME,
    "updates": RUNTIME,
    "monitoring": RUNTIME,
    "telemetry": RUNTIME,
    "database": RUNTIME,
    "runtime": RUNTIME,
    "timezone": RUNTIME,
    "mcp": RUNTIME,
    "max_live_sessions": RUNTIME,
    "max_concurrent_sessions": RUNTIME,
    # Hermes's other front ends and chat platforms: AGOS runs Hermes as a gateway
    # behind its own web app and Telegram, so these never take effect here. They
    # are still listed (nothing of Hermes is hidden).
    "discord": NOT_USED,
    "slack": NOT_USED,
    "matrix": NOT_USED,
    "mattermost": NOT_USED,
    "whatsapp": NOT_USED,
    "desktop": NOT_USED,
    "dashboard": NOT_USED,
    "onboarding": NOT_USED,
    "wake_word": NOT_USED,
    "session": NOT_USED,
    "paste_collapse_threshold": NOT_USED,
    "paste_collapse_threshold_fallback": NOT_USED,
    "paste_collapse_char_threshold": NOT_USED,
    "bot_mode": NOT_USED,
    "doctor": NOT_USED,
}

NOT_USED_WHY = (
    "The engine's own desktop, terminal and dashboard screens and its other chat apps "
    "(Discord, Slack, Matrix...): AGOS runs the engine behind its own app and Telegram, "
    "so these don't change anything here."
)


def group_of(key: str) -> str:
    parts = key.split(".")
    for size in range(len(parts), 0, -1):
        found = GROUP_BY_PREFIX.get(".".join(parts[:size]))
        if found is not None:
            return found
    return RUNTIME
