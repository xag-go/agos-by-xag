"""Channels (Settings → Channels, each chat's "Where"): each workspace's Telegram
bot is Hermes's own Telegram platform, run by the workspace's Hermes gateway.

- Hermes receives the bot's messages and decides who may talk to it: its own
  allowlist (TELEGRAM_ALLOWED_USERS) and DM pairing. AGOS shows them and the
  pairing requests, and the owner approves or removes people there, through
  Hermes's CLI (actions/telegram_people.py). The agos-guard plugin hands AGOS only
  what an allowed person says, to keep the same conversation in the AGOS chat.
- Hermes's own cards are Hermes's: an approval asked in any conversation (an AGOS
  chat too) is Hermes's Telegram Allow / Deny card, and Kanban news are Hermes's
  notifier.
- AGOS keeps only what Hermes has no place for, queued once in `channel_outbox`
  and sent by the workspace's Hermes gateway (Hermes's own send) on its bot:
  the replies of chats AGOS answers itself (a group's Hermes room: Hermes rooms
  have no Telegram), and its cards about AGOS's own state
  (a Kanban card's Allow once / Deny, a card's token warning, a room member's
  command). A restart never loses or doubles a message.
- Status lamp: connecting → connected (Hermes's own view of the bot) / error.

This module holds the channel outbox (queueing once, the send loop, closing answered
cards, Hermes's claim of the outbox) and approving a person; the connections, topics,
addresses, buttons and bot set-up live in actions/services/channel/ and are
re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any

from agos_core.actions import telegram_people
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import chats as chats_repo
from agos_core.db import kanban_asks as kanban_asks_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import load_json
from agos_core.engine import doorbell

# isort: off
from agos_core.actions.services.channel.connections import Kind as Kind
from agos_core.actions.services.channel.connections import TELEGRAM_LIMIT as TELEGRAM_LIMIT
from agos_core.actions.services.channel.connections import ConnectionView as ConnectionView
from agos_core.actions.services.channel.connections import ClaimView as ClaimView
from agos_core.actions.services.channel.connections import AddressView as AddressView
from agos_core.actions.services.channel.connections import _view as _view
from agos_core.actions.services.channel.connections import list_connections as list_connections
from agos_core.actions.services.channel.connections import read_ahead as read_ahead
from agos_core.actions.services.channel.connections import add_connection as add_connection
from agos_core.actions.services.channel.connections import update_connection as update_connection
from agos_core.actions.services.channel.connections import delete_connection as delete_connection
from agos_core.actions.services.channel.connections import retry as retry
from agos_core.actions.services.channel.connections import connection_row as _row
from agos_core.actions.services.channel.connections import connection_row as connection_row
from agos_core.actions.services.channel.connections import check_one as check_one
from agos_core.actions.services.channel.connections import workspace_bots as workspace_bots
from agos_core.actions.services.channel.topics import (
    TOPIC_WAIT_S as TOPIC_WAIT_S,
    _topics as _topics,
    _topics_lock as _topics_lock,
    _topics_to_make as _topics_to_make,
    make_topic as make_topic,
)
from agos_core.actions.services.channel.bot_addresses import (
    link_cofounder_chat as link_cofounder_chat,
    addresses_of as addresses_of,
    add_address as add_address,
    remove_address as remove_address,
)
from agos_core.actions.services.channel.buttons import (
    button as button,
    _workspace_of_address as _workspace_of_address,
)
from agos_core.actions.services.channel.bot_setup import (
    BotSetupView as BotSetupView,
    start_bot_setup as start_bot_setup,
    bot_setup_status as bot_setup_status,
    start_claim as start_claim,
    remove_person as remove_person,
)
# isort: on

log = logging.getLogger("agos.channels")  # the same logger as connections'


def _queue(
    core: Core,
    connection_id: int,
    address: str,
    body: str,
    source: str,
    *,
    buttons: list[tuple[str, str]] | None = None,
) -> None:
    outbox.queue(core.db, connection_id, address, body, source, buttons)
    doorbell.ring(doorbell.OUTBOX)


# ---- outbound: what Hermes has no place for -------------------------------------------------


def queue_replies(core: Core) -> int:
    """Each new agent reply in a chat that has addresses, queued once per address.
    In a group chat every reply says who wrote it (all of them come from the same
    bot in Telegram)."""
    from agos_core.actions import voice

    rows = outbox.unqueued_replies(core.db)
    added = 0
    for r in rows:
        # Hermes already sent the answers of its own turns in its Telegram chat (and
        # holds the chat's other replies until its answer is out, so they don't jump
        # ahead). A member's DM linked to a topic too: Hermes routes the topic to the
        # member's profile and sends its answers itself (actions/member_topics.py).
        if r["hermes_sends"]:
            continue
        body = str(r["body"])
        if r["kind"] == "group" or (r["kind"] == "dm" and r["speaker"]):
            # Every line from the workspace's one bot says who wrote it (a group's
            # member, or AGOS's own line in a member's topic).
            who = voice.name_of(core, str(r["workspace_id"]), r["speaker"])
            body = f"**{who}:**\n{body}"
        added += outbox.queue(
            core.db, int(r["connection_id"]), str(r["address"]), body, f"msg:{r['id']}"
        )
    if added:
        doorbell.ring(doorbell.OUTBOX)
    return added


def _card_text(body: str) -> str:
    """A card as Telegram shows it: plain text, one message."""
    text = re.sub(r"^#{1,6}\s*", "", body, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).strip() or "(empty)"
    return text if len(text) <= TELEGRAM_LIMIT - 200 else text[: TELEGRAM_LIMIT - 201] + "…"


# ---- the loop -------------------------------------------------------------------------------

# One sending round at a time: the lock keeps the database work in order; the
# workspace's Hermes gateway does the sending (hermes_outbox).
_WORK = threading.Lock()
SEND_EVERY = 0.5  # seconds before a round after a failed one (it doubles, up to 30 s)
SLOW_PASS_S = 5.0  # a pass longer than this delays replies: said in the log
STALE_EVERY_S = 60.0  # turns that never reported their end: looked for once a minute
_stale_at = 0.0


def send_round(core: Core) -> int:
    """What goes out on the bots: the relayed replies, and cards answered meanwhile
    closed. Database work only: no Hermes process runs in it (upkeep does that, in
    its own loop), so a reply never waits behind one. Turns that never reported
    their end (hours, STALE_AFTER_S) are closed at most once a minute: that check
    is a write attempt."""
    global _stale_at
    with _WORK:
        queue_replies(core)
        from agos_core.actions import hermes_channel

        if time.monotonic() - _stale_at >= STALE_EVERY_S:
            _stale_at = time.monotonic()
            hermes_channel.close_stale(core)
        close_answered(core)
    return 0


def upkeep(core: Core) -> None:
    """What may run a Hermes command (it can wait while Hermes prepares a new
    root): the members' Telegram menus, rebuilt only for a workspace whose team or
    groups changed (actions/member_menus.py). Each bot's lamp is read live from
    Hermes."""
    from agos_core.actions import member_menus

    member_menus.sync(core)


# ---- cards answered elsewhere ---------------------------------------------------------
# Like Hermes's Allow / Deny: a card answered in AGOS (or anywhere) shows the answer in
# Telegram too and loses its buttons, so the same thing is never answered twice.

CLOSE_WITHIN_DAYS = 14


def _answered(core: Core, data: str) -> str | None:
    """What became of the thing a card's button acts on; None while it still waits."""
    m = re.fullmatch(r"kask:(?:once|deny|approve|reject|ans):(\d+)(?::[a-z0-9_-]+)?", data)
    if m:
        found = kanban_asks_repo.status_of(core.db, int(m.group(1)))
        status = "gone" if found is None else found
        if status == "waiting":
            return None
        return {
            "allowed": "Allowed once.",
            "denied": "Denied.",
            "approved": "Approved.",
            "revised": "Sent back for changes.",
            "rejected": "Rejected.",
            "undone": "Undone.",
            "answered": "Answered.",
        }.get(status, "Answered.")
    m = re.fullmatch(r"chatcmd:(?:once|deny):(\d+)", data)
    if m:
        from agos_core.actions import rooms

        workspace_id = chats_repo.workspace_of(core.db, int(m.group(1)))
        if workspace_id is None:
            return "Answered."
        waiting = rooms.still_asks(core, workspace_id, int(m.group(1)))
        return None if waiting is not False else "Answered."
    return None  # a card this doesn't know stays as it is


def close_answered(core: Core) -> int:
    """Cards sent with buttons whose question was answered meanwhile: closed in Telegram."""
    closed = 0
    for r in outbox.open_cards(core.db, CLOSE_WITHIN_DAYS):
        buttons = load_json(r["buttons"]) or []
        data = str(buttons[0][1]) if buttons and len(buttons[0]) > 1 else ""
        shown = _answered(core, data)
        if shown is None:
            continue
        # The gateway that sent it closes it (hermes_outbox).
        outbox.close_card(core.db, int(r["id"]), f"{_card_text(str(r['body']))}\n\n→ {shown}")
        closed += 1
    if closed:
        doorbell.ring(doorbell.OUTBOX)
    return closed


def mark_card_closed(core: Core, connection_id: int, message_id: str) -> None:
    """Answered by its own button in Telegram (Hermes already shows the answer there)."""
    outbox.closed_by_button(core.db, connection_id, message_id)


def tick(core: Core) -> None:
    """One sending round (tests, and anything that wants it at once)."""
    send_round(core)
    from agos_core.actions import hermes_channel

    hermes_channel.sync_member_menus(core)


async def run_forever(core: Core) -> None:
    """Hands what goes out to the gateways at once: a round runs when its doorbell
    rings (an agent's line or a turn's end in a chat, a card answered: doorbell.SEND)
    and every doorbell.FALLBACK_S anyway (a writer that doesn't ring, a room's ask
    answered in Hermes). Receiving, sending and each bot's state are Hermes's (its
    lamp is read live from gateway_state.json); its service keeps the gateway up."""
    backoff = 0.0
    with doorbell.listening(doorbell.SEND, "") as bell:  # listen first, then look
        while True:
            try:
                started = time.monotonic()
                await asyncio.to_thread(send_round, core)
                if time.monotonic() - started > SLOW_PASS_S:
                    log.warning(
                        "channels: slow send round (%.1fs): replies wait",
                        time.monotonic() - started,
                    )
                backoff = 0.0
            except Exception:
                log.exception("channels: sending failed")
                backoff = min(backoff * 2 or SEND_EVERY, 30)
            if backoff:
                await asyncio.sleep(backoff)
            else:
                await bell.wait(doorbell.FALLBACK_S)


UPKEEP_EVERY = 2.0  # seconds between two looks at the members' menus (stat() only)


async def upkeep_forever(core: Core) -> None:
    """The members' menus, apart from the sending loop."""
    backoff = UPKEEP_EVERY
    while True:
        try:
            started = time.monotonic()
            await asyncio.to_thread(upkeep, core)
            if time.monotonic() - started > SLOW_PASS_S:
                log.info("channels: upkeep took %.1fs", time.monotonic() - started)
            backoff = UPKEEP_EVERY
        except Exception:
            log.exception("channels: upkeep failed")
            backoff = min(backoff * 2, 30)
        await asyncio.sleep(backoff)


def approve_person(core: Core, connection_id: int, request_id: str) -> None:
    """The owner's yes to someone who wrote to the bot (Hermes's pairing request).
    The first account becomes the bot's private chat with the Co-Founder."""
    row = _row(core, connection_id)
    workspace_id = str(row["workspace_id"] or "")
    if row["kind"] != "telegram" or not workspace_id:
        raise ActionError("Only a workspace's own Telegram bot has people to approve.")
    user_id = telegram_people.approve(core, workspace_id, request_id)
    if not user_id.isdigit():
        return
    address = f"{user_id}:0"  # his private chat with the bot has his own id
    with _WORK, transaction(core.db):
        added = link_cofounder_chat(core, connection_id, address)
        if added is None:
            return
        from agos_core.db.workspaces import name_of

        name = name_of(core.db, workspace_id)
        _queue(
            core,
            connection_id,
            address,
            f"Connected to the AGOS workspace “{name}”. "
            "Write here to talk to its Co-Founder; board notifications arrive here too.",
            f"paired:{user_id}",
        )


# ---- what Hermes's gateway sends for AGOS (its own bot) -----------------------------

CLAIM_FOR_S = 120  # a row taken but never confirmed goes out again after this


def hermes_outbox(core: Core, workspace_id: str, limit: int = 20) -> dict[str, Any]:
    """Replies and cards for the workspace's bot, for its Hermes gateway to send, and
    cards to close."""
    from agos_core.actions import hermes_channel

    conn = hermes_channel.connection(core, workspace_id)
    if conn is None:
        return {"send": [], "close": [], "topics": []}
    rows = outbox.to_send(core.db, int(conn["id"]), CLAIM_FOR_S, limit)
    from agos_core.shared.guard_contract import AGOS_BUTTONS

    send = []
    for r in rows:
        buttons = [list(b) for b in load_json(r["buttons"]) or []]
        if any(not re.match(AGOS_BUTTONS, str(b[1] if len(b) > 1 else "")) for b in buttons):
            # A card from before whose buttons nothing answers any more (the Co-Founder's
            # actions, requests, proposals): never sent.
            outbox.skip(core.db, int(r["id"]))
            continue
        outbox.claim(core.db, int(r["id"]))
        send.append(
            {
                "id": int(r["id"]),
                "address": str(r["address"]),
                # A reply goes as written (Hermes's own send formats and splits it); a
                # card is one plain message with its buttons.
                "text": _card_text(str(r["body"])) if buttons else str(r["body"]),
                "buttons": buttons,
            }
        )
    close = [
        {
            "id": int(r["id"]),
            "address": str(r["address"]),
            "messageId": str(r["sent_id"]),
            "text": str(r["close_text"])[:TELEGRAM_LIMIT],
        }
        for r in outbox.to_close(core.db, int(conn["id"]), limit)
        if str(r["sent_id"] or "").isdigit()
    ]
    return {"send": send, "close": close, "topics": _topics_to_make(workspace_id)}


def hermes_outbox_done(
    core: Core,
    workspace_id: str,
    row_id: int,
    kind: str,
    message_id: str | None,
    error: str | None,
) -> None:
    """The gateway sent (or closed) it, or says why not."""
    from agos_core.actions import hermes_channel

    if kind == "topic":
        with _topics_lock:
            t = _topics.get(row_id)
            if t is not None and t["workspace"] == workspace_id:
                t["thread"], t["error"] = message_id, error
                t["done"].set()
        return
    conn = hermes_channel.connection(core, workspace_id)
    if conn is None:
        return
    if kind == "close":
        outbox.closed(core.db, row_id, int(conn["id"]))
        return
    if error:
        outbox.failed(core.db, row_id, int(conn["id"]), error[:300])
        return  # the Log shows it (channel_outbox.error); the lamp is Hermes's
    outbox.sent(core.db, row_id, int(conn["id"]), message_id or "sent")
