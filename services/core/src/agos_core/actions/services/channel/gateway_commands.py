"""Slash commands in a Hermes-served chat: Hermes's own, AGOS's own (/undo, /title,
/yolo), their answers, the MCP reload and the bot's command list.

Owns: which command goes where and how its answer is recognised.
Must not: change the team menu (telegram_menu) or models (gateway_models).

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from agos_core.actions.services.channel import gateway_platform, hermes_addresses
from agos_core.actions.services.chat import chat_writes
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import chat_turns, hermes_inbox
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.engine import doorbell

__all__ = [
    "AGOS_COMMANDS",
    "CONTROL_CHAT",
    "OWN_COMMAND_KEY",
    "command_in",
    "command_out",
    "commands",
    "hand_over_command",
    "is_hermes_command",
    "mark_own_command",
    "own_command",
    "read_ahead",
    "reload_mcp",
]

log = logging.getLogger("agos.hermes_channel")


# A /command is Hermes's control, not a request: Hermes runs it and answers it itself.
# AGOS shows the command and Hermes's answer in the chat (one conversation), and
# never waits for an agent's answer to it.

AGOS_COMMANDS = ("/start ",)  # the link to his account (/task is Hermes's skill command)
# AGOS's old copy of Hermes's menu (an app setting per workspace) is deleted
# by a migration: the menu is read from Hermes each time (commands).


def is_hermes_command(text: str) -> bool:
    text = text.strip()
    return (
        text.startswith("/")
        and not text.startswith(AGOS_COMMANDS)
        and bool(re.fullmatch(r"/[A-Za-z0-9_]{1,40}(@\w+)?(\s[\s\S]*)?", text))
    )


def _answered_by_hermes(core: Core, workspace_id: str, chat_id: int, message_id: int) -> None:
    """A room's command line counts as answered: never handed to its members."""

    kind = chats_repo.any_row(core.db, chat_id)
    if kind is None or kind["kind"] != "group":
        return  # a Hermes chat: Hermes answers its commands itself
    # Made already ended: as a live turn it was refused while the room was answering
    # (one live turn per chat), and his command was lost.
    turn_id = chat_writes.insert_turn(
        core.db,
        chat_id=chat_id,
        workspace_id=workspace_id,
        asked_up_to=message_id,
        status="completed",
    )
    chat_turns.ended_by(core.db, turn_id, gateway_platform.ENGINE_HERMES)
    doorbell.ring(doorbell.SEND)


def command_in(
    core: Core, workspace_id: str, address: str, sender: str, text: str, authorized: bool = False
) -> bool:
    """He typed a Hermes command in Telegram: the AGOS chat shows it too (only from
    someone Hermes's own allowlist lets in)."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None or not text.strip() or not authorized:
        return False
    del sender  # who it is was Hermes's to check
    target = hermes_addresses._target(core, row, address)
    if target is None or str(target["workspace_id"]) != workspace_id:
        return False
    from agos_core.db import chats as repo

    chat_id = int(target["chat_id"])
    with transaction(core.db):
        # Hermes keeps no transcript of its commands: the chat shows it as AGOS's line.
        saved = chat_writes.add_chat_message(core.db, workspace_id, chat_id, "owner", text.strip())
        if saved is not None and repo.live_turn(core.db, chat_id) is None:
            _answered_by_hermes(core, workspace_id, chat_id, saved)
    return True


def command_out(core: Core, workspace_id: str, address: str, text: str) -> bool:
    """Hermes's own answer to a command (sent to Telegram by Hermes): shown in AGOS."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None or not text.strip():
        return False
    target = hermes_addresses._target(core, row, address)
    if target is None or str(target["workspace_id"]) != workspace_id:
        return False

    with transaction(core.db):
        saved = chat_writes.add_chat_message(
            core.db, workspace_id, int(target["chat_id"]), "agent", text.strip()
        )
        if saved is not None:  # already in Telegram: never sent there again
            outbox.queue_sent(
                core.db, int(row["id"]), hermes_addresses.address_of(address), "", f"msg:{saved}"
            )
    return True


def hand_over_command(
    core: Core, workspace_id: str, chat_id: int, message_id: int, text: str
) -> bool:
    """He typed a Hermes command in AGOS: Hermes runs it in the same conversation."""
    where = hermes_addresses.chat_on_hermes(core, chat_id)
    if where is None:
        return False
    from agos_core.actions.channels import _queue

    with transaction(core.db):
        _answered_by_hermes(core, workspace_id, chat_id, message_id)
        hermes_inbox.put(core.db, workspace_id, str(where["address"]), text.strip(), "command")
        doorbell.ring(doorbell.INBOX, workspace_id)
        if where["connection_id"] is None:
            return True  # an AGOS conversation: Hermes answers right there
        _queue(
            core,
            int(where["connection_id"]),
            str(where["address"]),
            f"{hermes_addresses.MIRROR_MARK}\n{text.strip()}",
            f"mirror:{message_id}",
        )
    return True


def own_command(core: Core, workspace_id: str, chat_id: int, command: str) -> bool:
    """One of Hermes's own commands (/retry, /undo) on the chat's conversation, so
    the conversation the agent works from is changed by Hermes itself: an AGOS
    conversation, or one that lives in Telegram (it goes in there as his own
    command, through the same hand-over as a command he types: the plugin's
    `_run_command`, a MessageType.COMMAND event into Hermes's Telegram adapter, so
    Hermes's /retry and /undo run there: H: hermes_cli/commands.py). Only a chat
    with one Hermes conversation (a group's members each have their own): False
    otherwise, and the caller does it the AGOS way."""
    where = hermes_addresses.chat_on_hermes(core, chat_id)
    if where is None:
        return False
    kind = chats_repo.any_row(core.db, chat_id)
    if kind is not None and kind["kind"] == "group":
        return False
    address = str(where["address"])
    # He already said yes in AGOS: Hermes's own confirm for /undo is answered with
    # its text reply (/approve), and those notes aren't shown in the chat.
    said = [command, "/approve"] if command == "/undo" else [command]
    if command.startswith("/title "):
        said = [command]
    for text in said:
        hermes_inbox.put(core.db, workspace_id, address, text, "command")
    doorbell.ring(doorbell.INBOX, workspace_id)
    mark_own_command(core, address)
    if where["connection_id"] is not None and not command.startswith("/title "):
        # In Telegram he sees what was done from AGOS (as for a command he types).
        from agos_core.actions.channels import _queue

        _queue(
            core,
            int(where["connection_id"]),
            address,
            f"{hermes_addresses.MIRROR_MARK}\n{command}",
            f"mirror:own:{command}:{now()}",
        )
    return True


def mark_own_command(core: Core, address: str) -> None:
    """AGOS just sent one of Hermes's commands here for the owner (his switch, his
    rename): Hermes's short confirmation of it is not shown (`_OWN_NOTES`)."""
    from agos_core.db.app_settings import set_setting

    set_setting(core.db, OWN_COMMAND_KEY + address, now())


OWN_COMMAND_KEY = "hermes.own_command."
# AGOS's control conversation in each profile of a root (no AGOS chat has id 0):
# where AGOS runs Hermes's own commands that are not about a chat (/reload-mcp).
CONTROL_CHAT = 0


def reload_mcp(core: Core, workspace_id: str) -> int:
    """Hermes's own /reload-mcp in the root and in each member's profile, so the
    running gateway reconnects an MCP server whose entry was edited and rebuilds
    its cached agents (gateway/slash_commands.py `_handle_reload_mcp_command`).
    Only for an edited entry: an added, removed, enabled or disabled server is
    Hermes's own MCP reconcile (gateway/run.py "MCP config reconcile"). Every
    profile has `approvals.mcp_reload_confirm: false` (library.profile_settings),
    so Hermes asks no confirm and AGOS never answers one. Nothing is stopped:
    Kanban workers, cron runs and rooms keep going. A gateway that isn't running
    reads the config when it starts: nothing to do. Returns how many profiles
    were asked."""
    engine = core.engine
    if engine is None or not engine.is_running(workspace_id):
        return 0
    from agos_core.actions import agent_profiles

    members = [
        m
        for m in agent_profiles.team_names(core, workspace_id)
        if agent_profiles.ready(core, workspace_id, m)
    ]
    addresses = [f"{hermes_addresses.AGOS_PREFIX}{CONTROL_CHAT}"] + [
        f"{hermes_addresses.AGOS_PREFIX}{CONTROL_CHAT}.{m}" for m in members
    ]
    with transaction(core.db):
        for address in addresses:
            hermes_inbox.put(core.db, workspace_id, address, "/reload-mcp", "command")
    doorbell.ring(doorbell.INBOX, workspace_id)
    return len(addresses)


# Hermes's confirmations of the commands AGOS sends for the owner (/undo and its
# confirm, /title, /yolo): not shown, the chat already shows what changed. A
# refusal (a title already in use: "⚠️ Title '…' is already in use") is shown.
_OWN_NOTES = (
    "⚠️ **Confirm /undo**",
    "↩️ Undid",
    "Nothing to undo.",
    "✅ Approved",
    "✏️ Session title set",
    "⚡ YOLO mode **ON**",
    "⚠️ YOLO mode **OFF**",
    "No pending command to approve.",
)


def _own_command_note(core: Core, address: str, text: str) -> bool:
    from agos_core.db.app_settings import get_setting

    at = str(get_setting(core.db, OWN_COMMAND_KEY + address, "") or "")
    if not at or not text.startswith(_OWN_NOTES):
        return False
    try:
        since = datetime.now(UTC) - datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return since.total_seconds() < 300


def commands(core: Core, workspace_id: str) -> list[dict[str, str]]:
    """Hermes's command menu (what Telegram shows when he types "/"), read from
    Hermes's own registry each time (engine command_menu); AGOS keeps no copy."""
    if core.engine is None:
        return []
    try:
        found = core.engine.command_menu(workspace_id)
    except Exception as error:  # noqa: BLE001 - no menu: the composer lists nothing
        log.info("Hermes's command menu not read for %s: %s", workspace_id, error)
        return []
    return [
        {"command": c["command"][:40], "description": c["description"][:200]}
        for c in found[:200]
        if re.fullmatch(r"[a-z0-9_]{1,40}", c["command"])
    ]


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): the command menu of each
    workspace whose root runs on Hermes (the chat composer's "/" list), one Hermes
    run at a time."""
    from agos_core.db.workspaces import list_workspaces

    engine = core.engine
    if engine is None:
        return
    for w in list_workspaces(core.db):
        if (engine.root(w.id) / "config.yaml").is_file():
            commands(core, w.id)
