"""The team's members in the bot's "/" menu: their commands registered in Hermes
from the policy file AGOS writes, and the menu pushed to Telegram.

Owns: member commands in this gateway.
Must not: route a member's messages (Hermes's profile routes do).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "MEMBERS_EVERY_S",
]

try:
    from . import bridge_core
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]


# AGOS writes the members of the workspace's Telegram groups into this profile's
# policy file ("members": [{command, title}]); each becomes one of this plugin's
# commands, so Hermes's menu (every scope, forum topics too) lists them. In a group
# AGOS takes "/member …" first (pre_gateway_dispatch → member-command); anywhere
# else the command answers itself.

MEMBERS_EVERY_S = 20
_members: dict[str, str] = {}
_member_handles: dict[str, Any] = {}  # Hermes's PluginRegistration per member command


def _wanted_members() -> dict[str, str]:
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        policy = json.loads((Path(get_hermes_home()) / "agos-guard.json").read_text())
    except ImportError as error:
        bridge_core._broken("hermes_constants.get_hermes_home", error)
        return {}
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for m in policy.get("members") or []:
        if isinstance(m, dict) and re.fullmatch(r"[a-z0-9_]{1,32}", str(m.get("command") or "")):
            out[str(m["command"])] = str(m.get("title") or m["command"])[:256]
    return out


def _member_handler(command: str) -> Any:
    def handler(raw_args: str = "") -> str:
        name = command.replace("_", "-")
        return (
            f"/{command} talks to @{name} in a Telegram group they're in (or write to "
            "them in AGOS). Here, just tell me what you need."
        )

    return handler


def _sync_members() -> bool:
    """This plugin's member commands follow the policy file. True when they changed."""
    ctx = bridge_core._ctx.get("ctx")
    if ctx is None:
        return False
    wanted = _wanted_members()
    if wanted == _members:
        return False
    for gone in [c for c in _members if c not in wanted or wanted[c] != _members[c]]:
        # Hermes's own handle for that one command (PluginRegistration.dispose).
        handle = _member_handles.pop(gone, None)
        if handle is not None:
            with bridge_core._guard("hermes_cli.plugins_ledger.PluginRegistration.dispose"):
                handle.dispose()
        _members.pop(gone, None)
    for command, title in wanted.items():
        if command in _members:
            continue
        # a name Hermes keeps for itself: skipped (Hermes returns no handle)
        with bridge_core._guard("hermes_cli.plugins.PluginContext.register_command"):
            handle = ctx.register_command(command, _member_handler(command), description=title)
            if handle is not None:
                _member_handles[command] = handle
        _members[command] = title  # tried; not again until the policy changes
    return True


async def _members_menu(adapter: Any) -> None:
    """Hermes pushes its menu again whenever the members change."""
    while True:
        with bridge_core._guard(
            "plugins.platforms.telegram.adapter.TelegramAdapter._register_command_menu"
        ):
            if await asyncio.to_thread(_sync_members):
                push = getattr(adapter, "_register_command_menu", None)
                if push is not None:
                    await push()
        await asyncio.sleep(MEMBERS_EVERY_S)


async def _send_menu(native: Any) -> None:
    """The bot's @name → AGOS, once Hermes's Telegram knows it (Hermes keeps it only
    in its running adapter). Its "/" menu is not sent: AGOS reads it from Hermes's
    own registry (hermes_cli/commands_platforms.py telegram_menu_commands)."""
    for _ in range(10):
        await asyncio.sleep(15)
        with contextlib.suppress(Exception):
            name = str(getattr(native.bot, "username", "") or "")  # Hermes's own client
            if name:
                await asyncio.to_thread(bridge_core.post, "commands", {"bot": name}, 15)
                return
