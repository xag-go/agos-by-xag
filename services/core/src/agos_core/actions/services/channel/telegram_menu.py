"""The team's members in the bot's "/" menu: one command per member, the member his
next message goes to, and the members written into each workspace's policy file.

Owns: the member commands of a workspace's Telegram bot.
Must not: deliver messages itself (gateway_messages, gateway_commands).

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Callable

from agos_core.actions.services.channel import (
    gateway_commands,
    gateway_messages,
    gateway_platform,
    hermes_addresses,
)
from agos_core.actions.services.chat import chat_writes
from agos_core.context import Core
from agos_core.db import channel_connections as connections_repo
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction

__all__ = [
    "MENU_FIRST",
    "NEXT_TO",
    "NEXT_TO_S",
    "choose_member",
    "chosen_member",
    "command_name",
    "member_command",
    "member_commands",
    "member_of_command",
    "sync_member_menus",
]


# Each member of the workspace's Telegram groups is a command in Hermes's own "/" menu
# (/ideas_generator → @ideas-generator), with its job title: AGOS writes them into the
# profile's policy file, the agos-guard plugin registers them, Hermes pushes the menu.


def command_name(member: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", member.lower())[:32]


def member_of_command(
    core: Core, workspace_id: str, chat_id: int, text: str
) -> tuple[str, str] | None:
    """ "/ideas_generator 3 ideas" in a group chat → ("ideas-generator", "3 ideas").
    Also when Telegram glued the words on ("/ideas_generator3 ideas", what is left of
    "/ideas_generator@bot 3 ideas" once the bot's name is taken out)."""
    from agos_core.db.rows import load_json

    m = re.fullmatch(r"/([a-z0-9_]{1,64})(?:@\w+)?(?:\s+([\s\S]*))?", text.strip())
    if not m:
        return None
    chat = chats_repo.in_workspace(core.db, workspace_id, chat_id)
    if chat is None or chat["kind"] != "group":
        return None
    typed, rest = m.group(1), (m.group(2) or "").strip()
    found: tuple[str, str] | None = None
    for name in load_json(chat["members"]) or []:
        command = command_name(str(name))
        if typed == command:
            return str(name), rest
        if typed.startswith(command) and (found is None or len(command) > len(found[0])):
            glued = typed[len(command) :].lstrip("_")
            found = (str(name), f"{glued} {rest}".strip())
    return found


NEXT_TO = "group.next_to."  # + chat id: the member his next message goes to
NEXT_TO_S = 15 * 60


def choose_member(core: Core, workspace_id: str, chat_id: int, member: str) -> None:
    """He picked a member in Telegram's "/" menu (no words yet): his next message in
    this group goes to that member. AGOS says so in the group."""
    from agos_core.actions.chat import team_members
    from agos_core.db.app_settings import set_setting

    title = next((m.title or m.name for m in team_members(core, workspace_id, [member])), member)
    with transaction(core.db):
        set_setting(core.db, NEXT_TO + str(chat_id), {"member": member, "at": time.time()})
        chat_writes.add_chat_message(
            core.db,
            workspace_id,
            chat_id,
            "agent",
            f"Your next message here goes to {title}.",
            speaker="AGOS",
        )


def chosen_member(core: Core, chat_id: int) -> str | None:
    """The member he picked for his next message (once; it lasts 15 minutes)."""
    from agos_core.db.app_settings import delete_setting, get_setting

    key = NEXT_TO + str(chat_id)
    got = get_setting(core.db, key, None)
    if not isinstance(got, dict):
        return None
    delete_setting(core.db, key)
    if time.time() - float(got.get("at") or 0) > NEXT_TO_S:
        return None
    return str(got.get("member") or "") or None


def member_command(
    core: Core,
    workspace_id: str,
    address: str,
    sender: str,
    text: str,
    message_id: str,
    answer: Callable[[int], None] | None = None,
    *,
    authorized: bool = False,
) -> bool:
    """A member's command typed in a Telegram group: that member's message (True), or
    not one (Hermes runs it as its own command). `authorized`: Hermes's own allowlist
    lets the sender in (a stranger never reaches AGOS)."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None or not address.startswith("-"):
        return False
    target = hermes_addresses._target(core, row, hermes_addresses.address_of(address))
    if target is None or str(target["workspace_id"]) != workspace_id:
        return False
    chat_id = int(target["chat_id"])
    got = member_of_command(core, workspace_id, chat_id, text)
    if got is not None:
        member, words = got
        if not authorized:
            return True
        if not words:
            choose_member(core, workspace_id, chat_id, member)
            return True
        gateway_messages.incoming(
            core,
            workspace_id,
            address,
            sender,
            f"@{member} {words}",
            message_id,
            None,
            answer=answer,
            authorized=True,
        )
        return True
    where = hermes_addresses.chat_on_hermes(core, chat_id)
    if where is None or not str(where["address"]).startswith(hermes_addresses.AGOS_PREFIX):
        return False
    # Hermes's own command in a group that lives on the agos platform: it runs in
    # the group's own Hermes conversation (the Co-Founder's), its answer shows there and
    # in the topic.

    if not authorized:
        return True
    with transaction(core.db):
        added = chat_writes.add_chat_message(core.db, workspace_id, chat_id, "owner", text.strip())
    if added is not None:
        gateway_commands.hand_over_command(core, workspace_id, chat_id, added, text.strip())
    return True


MENU_FIRST = "platforms.telegram.extra.command_menu.priority"


def member_commands(core: Core, workspace_id: str) -> list[dict[str, str]]:
    """The members of the workspace's Telegram groups, as commands for Hermes's own
    "/" menu (its agos-guard plugin registers them; Hermes pushes the menu)."""
    from agos_core.actions.chat import team_members
    from agos_core.db.rows import load_json

    menu: dict[str, str] = {}
    for members in addresses_repo.group_members_on_bots(
        core.db, workspace_id, gateway_platform.ENGINE_HERMES
    ):
        for m in team_members(core, workspace_id, load_json(members) or []):
            menu.setdefault(command_name(m.name), (m.title or m.name)[:256])
    return [{"command": k, "title": v} for k, v in sorted(menu.items())]


def sync_member_menus(core: Core, only: set[str] | None = None) -> int:
    """Each workspace's policy file carries its members' commands; written again
    only when they change (the plugin follows it within seconds). `only`: just
    these workspaces (actions/member_menus.py picks the ones whose team or groups
    changed)."""
    if core.engine is None:
        return 0
    from agos_core.actions import autonomy
    from agos_core.shared.guard_contract import POLICY_FILE

    changed = 0
    for workspace_id in connections_repo.hermes_bot_workspaces(
        core.db, gateway_platform.ENGINE_HERMES
    ):
        if not workspace_id or (only is not None and workspace_id not in only):
            continue
        path = core.engine.profile_home(workspace_id) / POLICY_FILE
        try:
            have = json.loads(path.read_text()).get("members")
        except (OSError, ValueError, AttributeError):
            have = None
        wanted = member_commands(core, workspace_id)
        if have != wanted:
            # Hermes's menu holds 60: the members come first (Hermes's own setting),
            # then the plugin (from the policy) registers them and pushes the menu.
            with contextlib.suppress(Exception):
                core.engine.set_setting(
                    workspace_id,
                    MENU_FIRST,
                    json.dumps([m["command"] for m in wanted]),
                )
            autonomy.write_policy(core, workspace_id)
            changed += 1
    return changed
