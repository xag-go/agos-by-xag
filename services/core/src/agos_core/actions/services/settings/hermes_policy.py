"""What AGOS does with each Hermes setting: forced, locked, shown on a card, a choice, recommended.
Must not: read or write a workspace's Hermes.

Split out of agos_core.actions.hermes_all_settings (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.services.settings.hermes_targets import _norm
from agos_core.context import Core

__all__ = [
    "CARD_LABELS",
    "FORCED_ENV_WHY",
    "FORCED_WHY",
    "LOCKED_WHY",
    "card_keys",
    "choice_keys",
    "forced_env",
    "forced_keys",
    "locked_env",
    "locked_keys",
    "recommended",
]

# Why AGOS writes each key it forces (the owner reads these on the page). A test
# checks this is exactly the set AGOS's writers force: a new forced key without a
# reason, or a reason left for a key no longer forced, fails.
FORCED_WHY: dict[str, str] = {
    # A run missed while the server was off (actions/catch_up.py): one value for every
    # workspace in Hermes's managed scope; AGOS runs it once or skips it per automation.
    "cron.catch_up_missed": "A run missed while the server was off is AGOS's choice per "
    "automation (its editor → If a run was missed): run it once when AGOS is back, or skip it.",
    # The sandbox (engine/rules.py profile_config, engine/network.py). Hermes reads each
    # into its docker backend (H: gateway/run.py:1993-2016 TERMINAL_DOCKER_* bridge,
    # tools/terminal_tool.py:729-773): another value runs commands outside the
    # workspace's sandbox, as the host user, with this machine's env or files.
    "terminal.backend": "Every command runs in the workspace's own Docker sandbox, never on this machine.",
    "terminal.docker_image": "AGOS's sandbox image, with the screen for browser and computer use.",
    "terminal.docker_mount_cwd_to_workspace": "The sandbox sees only the folders AGOS mounts (Folders card), not Hermes's own working folder.",
    "terminal.docker_run_as_host_user": "The sandbox never runs as your user on this machine.",
    "terminal.docker_forward_env": "No environment variable of this machine (keys, tokens) is passed into the sandbox.",
    "terminal.docker_env": "Only the sandbox's own settings: the egress proxy and your timezone (TZ).",
    "terminal.docker_extra_args": "The sandbox's own internal network, behind AGOS's egress proxy.",
    "terminal.cwd": "Commands start in /workspace, the workspace's own files.",
    "terminal.credential_files": "No credential file of this machine is copied into the sandbox.",
    "terminal.docker_volumes": "Exactly the workspace's folders and the ones you shared (Folders card); nothing else of this machine.",
    "terminal.docker_shared_container_key": "One sandbox per workspace, named after it, shared by its Co-Founder and members (Hermes: tools/terminal_tool.py:217).",
    "auth.adopt_external_logins": "Each workspace's Hermes uses only the logins it holds itself, never one borrowed from another program (Hermes: agent/credential_pool.py:2620).",
    "gateway.standalone": "One Hermes gateway per workspace, serving its Co-Founder and members (Hermes: gateway/host_attach.py:345).",
    "bot_desktop.placement": "Browser and computer use run on the workspace's own screen inside its sandbox, never on this machine (Hermes's \"auto\" may use this machine: tools/bot_desktop/placement.py:41).",
    # The workspace's capabilities and chats (actions/library.py profile_settings)
    "context_file_max_chars": "SOUL.md (AGOS's rules, the Co-Founder's chat actions and its view of the workspace) is loaded whole; Hermes's own cap (6% of the window, at least 20,000 characters) cuts its middle out (Hermes: agent/prompt_builder.py:1155-1180).",
    "plugins.entries.agos-guard.granted_capabilities": "AGOS's plugin may react to room messages through Hermes's own platform actions (Hermes: hermes_cli/plugin_capabilities.py:112).",
    "display.platforms.agos.tool_progress": "AGOS's chats are its plugin's platform, where every message Hermes sends becomes a chat message (no edits: bridge.py edit_message keeps the first one). AGOS shows its own \"Working…\"; progress lines would land as answers.",
    "display.platforms.agos.long_running_notifications": 'AGOS\'s chats show their own "Working…" (each Hermes notice would be a chat message).',
    "display.platforms.agos.interim_assistant_messages": "AGOS's chats get only the answer (each interim message would be a chat message).",
    "display.platforms.agos.busy_ack_detail": "AGOS's chats show their own busy state.",
    "display.platforms.agos.streaming": "AGOS's chats take the answer when it is complete: the platform keeps no edits, so a streamed answer would stop at its first piece.",
    "display.platforms.agos.busy_steer_ack_enabled": "AGOS's chats show your correction themselves.",
    "platforms.webhook.host": "Webhooks reach Hermes on this machine only; AGOS's public relay passes them on. Hermes's default binds every interface (Hermes: gateway/platforms/webhook.py:59,209; gateway/config.py:448).",
    "approvals.mcp_reload_confirm": "AGOS reloads an edited app/MCP server with Hermes's own /reload-mcp, where nobody answers a confirm: with it on the reload waits for ever (Hermes: gateway/slash_commands.py:1058).",
    # The team's board (actions/agent_profiles.py kanban_pairs; actions/account_pause.py)
    "kanban.dispatch_in_gateway": "Only the Co-Founder's Hermes starts cards (for itself and its members) (Hermes: gateway/kanban_watchers.py:231).",
    "kanban.dispatch_profiles": "The Co-Founder starts cards only for this workspace's agents; empty while your account-limit pause holds the board (Usage & limits) (Hermes: hermes_cli/kanban_db_dispatch.py:1693).",
    # The members' commands in Telegram (actions/hermes_channel.py sync_member_menus)
    "platforms.telegram.extra.command_menu.priority": "The members' own commands come first in the bot's \"/\" menu (Hermes's menu holds 60); AGOS keeps it in step with the members.",
}

# Keys AGOS doesn't write but that must stay as they are while AGOS's own egress
# proxy is the sandbox's way out (engine/network.py sandbox_settings puts
# HTTPS_PROXY/HTTP_PROXY into terminal.docker_env). Verified in Hermes v0.22.2:
# with proxy.enabled, tools/environments/docker.py _egress_and_env_args (:767) runs
# docker_egress.check_docker_env_collisions (:237), which finds AGOS's HTTPS_PROXY
# in docker_env; under proxy.enforce_on_docker (default true, :47) _collision_guard
# (:214) raises and NO sandbox starts; with it off Hermes warns and drops its own
# proxy. Shown read-only with the reason.
_PROXY_WHY = (
    "AGOS's own egress proxy is every sandbox's only way out (its HTTPS_PROXY is in "
    "terminal.docker_env). Hermes's iron-proxy would collide with it: with "
    "proxy.enforce_on_docker on (Hermes's default) Hermes then refuses to start any "
    "sandbox (tools/environments/docker_egress.py check_docker_env_collisions), and "
    "with it off Hermes's proxy is dropped anyway. Kept as Hermes's default while AGOS's "
    "proxy runs."
)
LOCKED_WHY: dict[str, str] = {
    "proxy.enabled": _PROXY_WHY,
    "proxy.enforce_on_docker": _PROXY_WHY,
}


def locked_keys() -> dict[str, str]:
    """Keys kept at Hermes's default (read-only) and why, while the condition holds."""
    from agos_core.engine import network

    env = json.loads(network.sandbox_settings("agos-x")["terminal.docker_env"])
    return dict(LOCKED_WHY) if "HTTPS_PROXY" in env else {}


# The .env lines AGOS writes on every sync of a profile (a name ending in "*" is a
# prefix). Shown read-only with the reason; a test checks each is written in AGOS's
# source.
FORCED_ENV_WHY: dict[str, str] = {
    "API_SERVER_ENABLED": "AGOS talks to each workspace's Hermes through Hermes's own API server (engine/hermes.py _write_api_env).",
    "API_SERVER_HOST": "The API answers on this machine only (loopback).",
    "API_SERVER_PORT": "A free port AGOS picks for this profile's API.",
    "API_SERVER_KEY": "A fresh key AGOS keeps for this profile's API (never shown).",
    "GATEWAY_ALLOW_ALL_USERS": "Kept unset: Hermes would then let anyone write to the bots (gateway/authz_mixin.py); who may write is on Workspace → Telegram.",
    "AGOS_PLATFORM_*": "AGOS's chats are this Hermes's conversations (AGOS's plugin platform \"agos\"): on, the owner only, and the Co-Founder chat as its home.",
    "WEBHOOK_ENABLED": "Hermes's webhook platform, on this machine only; AGOS's public relay passes webhooks on to it.",
    "WEBHOOK_PORT": "The port of this workspace's webhook platform (one per workspace).",
    "AGOS_MCP_*": "The keys of the workspace's apps (MCP servers), which its Hermes MCP config refers to.",
}

# .env lines AGOS doesn't write but that must stay off: `<PLATFORM>_ALLOW_ALL_USERS`
# (gateway/authz_mixin.py: a truthy one admits every user of that platform before
# any allowlist or pairing is read).
_ALLOW_ALL_WHY = (
    "Kept off: Hermes then lets anyone on this platform command the agents "
    "(gateway/authz_mixin.py, before its allowlist and pairing). Who may write to the "
    "bot is on Workspace → Telegram (people)."
)


def forced_env(name: str) -> str | None:
    for key, why in FORCED_ENV_WHY.items():
        if name == key or (key.endswith("*") and name.startswith(key[:-1])):
            return why
    return None


def locked_env(name: str) -> str | None:
    if name.endswith("_ALLOW_ALL_USERS") and forced_env(name) is None:
        return _ALLOW_ALL_WHY
    return None


# AGOS cards that show and change these keys (web: features/settings/hermes-settings.tsx).
CARD_LABELS: dict[str, str] = {
    "time-limits": "General → Time limits",
    "limits": "General → Loop detector & limits",
    "fallback": "General → Fallback models",
    "timezone": "General → Your timezone",
    "tool-search": "AGOS's Tool Search switch for the Co-Founder (/preferences/tool-search)",
    "voice": "General → Voice notes",
    "access": "Workspace → Access",
    "autonomy": "Workspace → Autonomy (Learn: Ask me)",
    "workspace-settings": "Workspace → Settings",
    "models": "Workspace → Default model",
    "capabilities": "Workspace → Capabilities",
    "member-topics": "Workspace → Member topics",
    "bot": "Workspace → Channels (Telegram bot)",
    "telegram-people": "Workspace → Telegram (people who may write)",
    "pools": "Settings → Models (several keys per provider)",
    "helper-models": "Settings → Helper models",
    "keys": "Workspace → Keys",
}

# The keys of actions/library.py profile_settings that the Capabilities pages set
# (the rest of that function's keys are forced).
_CAPABILITY_KEYS = (
    "mcp_servers",
    "plugins.enabled",
    "agent.disabled_toolsets",
    "skills.external_dirs",
    "skills.disabled",
)


def card_keys() -> dict[str, str]:
    """Key → the AGOS card that changes it, taken from those cards' own modules."""
    from agos_core.actions import (
        access,
        hermes_channel,
        hermes_limits,
        hermes_settings,
        member_topics,
        owner_time,
        telegram_people,
    )
    from agos_core.engine import fallback, rules, stt, time_limits

    out: dict[str, str] = {}
    for limit in time_limits.TIME_LIMITS:
        out[limit.key] = "time-limits"  # an UPPER key is a .env line (Hermes settings' .env rows)
    from agos_core.engine import helper_models

    # Settings → Helper models: the image mode here; every auxiliary task's routing
    # fields (Hermes's own list, read at run time) by their shape in _rule.
    out[helper_models.IMAGE_MODE] = "helper-models"
    for key in hermes_limits.KEYS:
        out[key] = "limits"
    out[fallback.KEY] = "fallback"
    out[fallback.LEGACY] = "fallback"
    out[owner_time.CONFIG_KEY] = "timezone"
    for key in stt.card_keys():  # who hears the voice notes (Hermes's managed scope)
        out[key] = "voice"
    out["approvals.mode"] = "access"
    from agos_core.actions import autonomy

    for key in autonomy.WRITE_GATES:  # an agent's Learn "Ask me"
        out[key] = "autonomy"
    for key in access.LISTS.values():  # its deny and allow rules
        out[key] = "access"
    for key in hermes_settings.SETTINGS:
        out[key] = "workspace-settings"
    for key in rules.model_pairs("anthropic", "x", "medium"):
        out[key] = "models"
    for key in _CAPABILITY_KEYS:
        out[key] = "capabilities"
    out[member_topics.ROUTES_KEY] = "member-topics"
    # The bot's card (Channels): its on/off and Hermes's 👀 / ✅ / ❌ reactions.
    out[hermes_channel.BOT_SWITCH] = "bot"
    out[hermes_channel.REACTIONS] = "bot"
    out[telegram_people.ENV] = "telegram-people"  # a .env line
    from agos_core.actions import key_pools

    out[key_pools.STRATEGY_KEY] = "pools"  # how Hermes picks among a provider's keys
    out[hermes_channel.TOKEN_LINE.rstrip("=")] = "bot"  # the bot's token (.env)
    # An old TELEGRAM_REACTIONS line: the bot card moves it into telegram.reactions.
    out[hermes_channel._OLD_REACTIONS.rstrip("=")] = "bot"
    from agos_core.engine import tool_keys

    # The names Hermes passes into the tools (each name's .env line: _env_rows).
    out[tool_keys.PASSTHROUGH] = "keys"
    from agos_core.actions import tool_search

    # The Co-Founder's Tool Search switch (eager / extra deferred tools).
    out[tool_search.ENABLED] = "tool-search"
    out[tool_search.DEFER] = "tool-search"
    return out


def _is_capability(key: str) -> bool:
    return key.startswith("platform_toolsets.") or key == "platform_toolsets"


def _written() -> dict[str, str]:
    """Every key AGOS's own writers set on each sync (not just once), with the value
    they write (the Co-Founder's, for a workspace on its own root)."""
    from agos_core.actions import access, agent_profiles, hermes_channel, library
    from agos_core.engine import network, rules

    config = rules.profile_config(
        image="agos-sandbox:1",
        mounts=[],
        network=network.sandbox_settings("agos-x"),
        container_key="agos-x",
    )
    out = {
        k: v for k, v in config.items() if k not in rules.seeded_config() and k != "approvals.mode"
    }
    out.update(library.profile_settings([]))
    out.update(
        {
            "kanban.dispatch_in_gateway": "true",
            "kanban.dispatch_profiles": "[]",
            # The value kanban_pairs writes (it needs no workspace for this one).
            **agent_profiles.KANBAN_TRIAGE,
        }
    )
    out[hermes_channel.MENU_FIRST] = ""
    if access.CRON_MODE:
        out["approvals.cron_mode"] = access.CRON_MODE
    from agos_core.actions import catch_up

    out[catch_up.HERMES_KEY] = "false"  # Hermes's managed scope (catch_up.pin_hermes)
    return out


def forced_keys(core: Core | None = None) -> set[str]:
    """Every key AGOS's own writers set on each sync (not just once), minus the
    ones a card changes, the owner's choices (engine/owner_choices.py) and the ones
    only a new profile starts with."""
    from agos_core.engine import owner_choices

    cards = card_keys()
    return {
        k
        for k in _written()
        if k not in cards and not _is_capability(k) and k not in owner_choices.WHY
    }


def choice_keys() -> dict[str, str]:
    """The owner's choices AGOS writes into a new profile → AGOS's recommended value."""
    from agos_core.engine import owner_choices

    return {k: v for k, v in _written().items() if k in owner_choices.WHY}


def recommended(text: str) -> Any:
    """A writer's `hermes config set` text as the value Hermes reads back."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _rule(
    key: str,
    forced: set[str],
    cards: dict[str, str],
    seeded: dict[str, str],
    choices: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """What AGOS does with this key (None: nothing, the owner changes it here). A
    mapping AGOS writes part of (e.g. `model`, whose `model.default` the model card
    sets) counts as that part."""
    below = [k for k in (*cards, *forced) if k.startswith(f"{key}.")]
    from agos_core.engine import helper_models

    card = cards.get(key) or ("capabilities" if _is_capability(key) else None)
    if card is None and helper_models.owns(key):
        card = "helper-models"  # one value for every workspace (Hermes's managed scope)
    if card is None:
        card = next((cards[k] for k in below if k in cards), None)
    if card is not None:
        from agos_core.actions import hermes_managed

        one = (
            " One value for every workspace (Hermes's managed scope)."
            if key in hermes_managed.by_card() or card == "helper-models"
            else ""
        )
        return {"kind": "card", "card": card, "reason": f"Changed on {CARD_LABELS[card]}.{one}"}
    if key in forced:
        return {"kind": "forced", "card": None, "reason": FORCED_WHY.get(key, "")}
    if choices and key in choices:
        from agos_core.engine import owner_choices

        value = recommended(choices[key])
        return {
            "kind": "choice",
            "card": None,
            "reason": f"Your choice. AGOS recommends {_norm(value)}: {owner_choices.WHY[key]} "
            "A new workspace or agent starts on it; AGOS never resets yours (Hermes's default "
            "is written as a value when you go back to it).",
            "recommended": value,
        }
    locked = locked_keys().get(key)
    if locked is not None:
        return {"kind": "locked", "card": None, "reason": locked}
    part = next((k for k in below if k in forced), None)
    if part is not None:
        return {
            "kind": "forced",
            "card": None,
            "reason": f"AGOS writes {part} inside it: {FORCED_WHY.get(part, '')}",
        }
    if key in seeded:
        return {
            "kind": "seeded",
            "card": None,
            "reason": f"A new workspace or agent starts on {seeded[key]} (AGOS's start value); "
            "afterwards it is yours to change.",
        }
    return None
