"""Whatever needs the owner reaches his phone too, only where the work is.

Each card goes to the chat it belongs to — the conversation the agent works in; a
Kanban card belongs to the Co-Founder — and only there: in AGOS, and in that chat's
own Telegram place; a chat with no Telegram place sends it to the Co-Founder's on the
phone. Never copied to every group.

- Hermes's own approvals (any conversation, an AGOS chat too) are Hermes's own
  Telegram card there (`phone_place` says where); Kanban news are Hermes's
  notifier (`kanban_notify_target` says where).
- AGOS's own cards (a Kanban card's Allow once / Deny, a token warning, a room
  member's command) are queued by `push` for the workspace's Hermes gateway.

Must not: call Telegram itself (the workspace's Hermes gateway sends what `push` queues), or copy a card to every group.
"""

from __future__ import annotations

import contextlib
import hashlib

from agos_core.actions.services.chat import chat_writes
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import chats as chats_repo
from agos_core.engine import doorbell

__all__ = [
    "GROUP_ADDRESS",
    "RECENT_DAYS",
    "TOOL_MARKS",
    "chat_command",
    "cofounder_chat",
    "ensure_cofounder_chat",
    "kanban_notify_target",
    "phone_place",
    "push",
    "targets",
    "tell_owner",
]

RECENT_DAYS = 7
# The first character of a card from one of AGOS's tools (Add to To do, the
# Co-Founder's actions, a capability): shown as a plain yes / no.
TOOL_MARKS = ("📋", "🛠", "🔌", "🗂")
# A Telegram group / topic address ("-100…:topic"); a private chat is a positive id.
GROUP_ADDRESS = "a.address LIKE '-%'"


def cofounder_chat(core: Core, workspace_id: str) -> int | None:
    return chats_repo.cofounder_chat_id(core.db, workspace_id)


def ensure_cofounder_chat(core: Core, workspace_id: str) -> int | None:
    """The Co-Founder's chat, made now when the workspace has none yet (as on his first
    message to it)."""
    from agos_core.db.workspaces import get_workspace

    found = chats_repo.cofounder_chat_id(core.db, workspace_id, hidden=True)
    if found is not None:
        return found
    workspace = get_workspace(core.db, workspace_id)
    if workspace is None:
        return None
    return chats_repo.insert_chat(
        core.db,
        workspace_id=workspace_id,
        title="",  # db/chats.py dm_title
        channel="web",
        kind="dm",
        agent=None,
    )


def tell_owner(core: Core, workspace_id: str, text: str, chat_id: int | None = None) -> int | None:
    """A message from the team in `chat_id` (the chat the work belongs to), else in
    the Co-Founder's DM (synced to the Telegram place linked to that chat)."""

    if chat_id is not None and chats_repo.chat_row(core.db, workspace_id, chat_id) is not None:
        return chat_writes.add_chat_message(core.db, workspace_id, chat_id, "agent", text)
    cofounder = ensure_cofounder_chat(core, workspace_id)
    if cofounder is None:
        return None
    return chat_writes.add_chat_message(core.db, workspace_id, cofounder, "agent", text)


def kanban_notify_target(core: Core, workspace_id: str) -> dict[str, str] | None:
    """Where Hermes's Kanban notifier tells the owner about the board's cards: the
    Co-Founder's own Hermes conversation (its Telegram chat when it lives there, else
    its AGOS chat), as a `hermes kanban notify-subscribe` destination. The agos-guard
    plugin subscribes it to every card that starts and that no chat follows yet."""
    from agos_core.actions import hermes_channel

    cofounder = ensure_cofounder_chat(core, workspace_id)
    where = hermes_channel.chat_on_hermes(core, cofounder) if cofounder is not None else None
    if cofounder is None or where is None:
        return None
    address = str(where["address"])
    if address.startswith(hermes_channel.AGOS_PREFIX):
        return {
            "platform": "agos",
            "chatId": str(cofounder),
            "chatType": "dm",
            "userId": hermes_channel.AGOS_OWNER,
        }
    from agos_core.actions import telegram_people

    chat, _, thread = hermes_channel.address_of(address).partition(":")
    owner = telegram_people.owner_id(core, workspace_id)
    thread = "" if thread in ("", "0") else thread
    return {
        "platform": "telegram",
        "chatId": chat,
        "threadId": thread,
        "chatType": "dm" if not chat.startswith("-") else ("forum" if thread else "group"),
        "userId": owner,
    }


def targets(core: Core, workspace_id: str, chat_id: int | None = None) -> list[tuple[int, str]]:
    """Where a card goes on the phone: the chat it belongs to (its own Telegram place),
    only there. No chat given, or a chat with no Telegram place = the Co-Founder's (its
    addresses, else the bot's private chat with him)."""
    cofounder = cofounder_chat(core, workspace_id)
    if chat_id is not None and chat_id != cofounder:
        places = addresses_repo.places_on_bots(core.db, chat_id)
        if places:
            return places
        # That chat has no Telegram place: the card reaches him on the Co-Founder's
        # (he may not be in the app), and stays in its own chat in AGOS.
    found = addresses_repo.places_on_bots(core.db, cofounder or -1)
    if found:
        return found
    # No chat linked yet: the bot's private chat with him (the workspace's bot chat).
    from agos_core.actions import hermes_channel, telegram_people

    bot = hermes_channel.connection(core, workspace_id)
    owner = telegram_people.owner_id(core, workspace_id) if bot is not None else ""
    return [(int(bot["id"]), owner)] if bot is not None and owner else []


def phone_place(
    core: Core, workspace_id: str, chat_id: int, what: str = ""
) -> dict[str, str] | None:
    """Where Hermes shows its own Telegram Allow / Deny card for an approval asked in
    an AGOS chat (`targets`): {"chat", "thread"}; None = nowhere (no bot, or he
    turned these off, or wants them in his Daily digest: `what` is held for it)."""
    from agos_core.actions.notification_rules import delivery_for

    delivery = delivery_for(core, "task.waiting")
    if delivery == "silent":
        return None
    if delivery == "batched":
        _hold_approval(core, workspace_id, chat_id, what)
        return None
    from agos_core.actions import web_push

    with contextlib.suppress(Exception):
        web_push.waiting(core, workspace_id, chat_id, what)  # the installed app too
    for _connection, address in targets(core, workspace_id, chat_id):
        chat, _, thread = address.partition(":")
        return {"chat": chat, "thread": "" if thread in ("", "0") else thread}
    return None


def push(
    core: Core,
    workspace_id: str,
    body: str,
    source: str,
    *,
    buttons: list[tuple[str, str]] | None = None,
    chat_id: int | None = None,
) -> int:
    """Queues `body` once (per `source`) to the chat it belongs to (`targets`)."""
    added = 0
    for connection_id, address in targets(core, workspace_id, chat_id):
        added += outbox.queue(core.db, connection_id, address, body, source, buttons)
    if added:
        doorbell.ring(doorbell.OUTBOX, workspace_id)
        from agos_core.actions import web_push

        with contextlib.suppress(Exception):
            web_push.card(core, workspace_id, body, chat_id, source)  # the installed app too
    return added


def chat_command(
    core: Core,
    workspace_id: str,
    speaker: str | None,
    command: str,
    why: str,
    callback: str,
    source: str,
    chat_id: int | None = None,
) -> int:
    """A member of a group's Hermes room asks to run a command (Hermes rooms have no
    Telegram): the command itself on the phone, Allow once / Deny, in that chat
    only. `callback` = "<kind>:<id>"."""
    from agos_core.actions import voice
    from agos_core.actions.notification_rules import delivery_for
    from agos_core.actions.system_log import redact

    delivery = delivery_for(core, "task.waiting")
    if delivery == "silent":
        return 0
    if delivery == "batched":
        _hold_approval(core, workspace_id, chat_id, redact(command.strip()))
        return 0
    shown = redact(command.strip())
    if len(shown) > 900:
        shown = shown[:899] + "…"
    lang = voice.language(core, workspace_id, speaker)
    reason = redact(why.strip())[:300].rstrip(".")
    because = voice.say("command_why", lang, why=reason[:1].lower() + reason[1:]) if reason else ""
    who = voice.name_of(core, workspace_id, speaker)
    tool = shown[:1] in TOOL_MARKS and not reason  # one of AGOS's tools (a yes/no)
    if tool:
        body = f"**{who}:**\n{shown}"
    else:
        body = voice.say("chat_command", lang, who=who, command=shown, why=because)
        body = f"🔐 **{who}:**\n{body}"  # which agent asks (all come from the same bot)
    yes, no = ("Yes", "No") if tool else ("Allow once", "Deny")
    return push(
        core,
        workspace_id,
        body,
        f"{source}:{hashlib.sha256(command.encode()).hexdigest()[:16]}",
        buttons=[
            (yes, f"{callback.replace(':', ':once:', 1)}"),
            (no, f"{callback.replace(':', ':deny:', 1)}"),
        ],
        chat_id=chat_id,
    )


def _hold_approval(core: Core, workspace_id: str, chat_id: int | None, what: str) -> None:
    """An approval asked while he wants a Daily digest: the chat in AGOS shows it
    now; the phone gets a line about it in the next digest."""
    from agos_core.actions import digest

    row = chats_repo.any_row(core.db, chat_id or -1)
    where = f"“{chats_repo.chat_title(core.db, row) or 'a chat'}”" if row is not None else "a chat"
    line = f"An agent asked for your approval in {where}" + (f": {what[:200]}" if what else "")
    digest.hold(core, workspace_id, "task.waiting", line)
