"""The one conversation seen from both sides: what he writes in AGOS handed over to
Hermes's conversation (with its media and name), and what Hermes says there kept
once in the AGOS chat.

Owns: mirroring messages between an AGOS chat and its Hermes conversation.
Must not: run commands or pick models itself (gateway_commands, gateway_models).

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import json
import re
from typing import Any

from agos_core.actions.services.channel import (
    gateway_commands,
    gateway_messages,
    gateway_models,
    gateway_platform,
    hermes_addresses,
)
from agos_core.actions.services.chat import chat_writes, gateway_turns
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import chats as repo
from agos_core.db import hermes_inbox
from agos_core.db.connection import transaction
from agos_core.engine import doorbell

__all__ = [
    "hand_over",
    "platform_said",
    "set_media",
]


def hand_over(
    core: Core,
    workspace_id: str,
    chat_id: int,
    text: str,
    *,
    reply: tuple[str, bool] | None = None,
) -> int | None:
    """His message, into the chat's Hermes conversation: the agos platform's queue
    item it is (its id; Hermes keeps it as its message's own id), None when the
    chat isn't on Hermes. On the agos platform it goes as itself, as Hermes takes a
    message: a reply as Hermes's own reply context (`reply`: the quoted text, the
    agent's or not); his files are added to it (`set_media`). Messages one after
    another, or while it works, are Hermes's to put together. In Telegram his message
    goes into the conversation as if he sent it there (with his files) and his words
    are also shown there, marked as written in AGOS. A group chat never comes here:
    it is a Hermes room (actions/rooms.py)."""

    where = hermes_addresses.chat_on_hermes(core, chat_id)
    if where is None:
        return None
    address = str(where["address"])
    on_platform = where["connection_id"] is None
    busy = repo.live_turn(core.db, chat_id) is not None
    if not gateway_messages.waits_for_check_in(core, workspace_id, address):
        # Off-hours it waits in the queue (no answer is working on it yet).
        gateway_turns._open_turn(
            core, workspace_id, chat_id, 0, speaker=gateway_turns._dm_speaker(core, chat_id)
        )
    if on_platform and not busy:
        gateway_models.tell_model(core, workspace_id, chat_id, None)
        _tell_name(core, workspace_id, chat_id)
    changed = ""
    if not busy:
        # Told with the message that is really handed over (older messages he
        # changed or deleted: Hermes keeps no edit in the middle of a conversation).
        from agos_core.actions import chat as chat_actions

        changed = chat_actions.edits_note(core, chat_id)
    words = f"{changed}\n\n{text}" if changed else text
    if reply is None or not on_platform:
        body, kind = words, "message"
    else:
        # Hermes's reply context travels with the message (take_inbox opens it).
        body = json.dumps({"text": words, "replyTo": reply[0], "own": reply[1]})
        kind = "reply"
    item = hermes_inbox.put(core.db, workspace_id, address, body, kind, "[]")
    doorbell.ring(doorbell.INBOX, workspace_id)
    if not on_platform and text.strip():
        from agos_core.actions.channels import _queue

        _queue(
            core,
            int(where["connection_id"]),
            address,
            f"{hermes_addresses.MIRROR_MARK}\n{text}",
            f"mirror:p{item}",
        )
    return item


def set_media(core: Core, item: int, stored: list[dict[str, Any]]) -> None:
    """His files go with his message as files, on the agos platform and in a
    Telegram conversation alike: Hermes reads, hears (its own speech-to-text) and
    looks at them itself (H: gateway/run_inbound.py `_prepare_inbound_message_text`)."""
    hermes_inbox.set_media(core.db, item, json.dumps(stored))


def _tell_name(core: Core, workspace_id: str, chat_id: int) -> None:
    """The name he gave a chat before it had a Hermes session: Hermes's /title goes
    just before his first message (before Hermes names the session itself). Hermes
    decides whether the name is free (its title rules); its refusal is shown in the
    chat. Once Hermes has it, AGOS's copy goes (actions/chat_store.py)."""
    from agos_core.db import hermes_chats as hc

    row = repo.any_row(core.db, chat_id)
    title = str(row["title"] or "").strip() if row is not None else ""
    if row is None or row["kind"] != "chat" or not title or title in repo.DEFAULT_TITLES:
        return
    store = hc.store()
    where = repo.where_of(core.db, row)
    if store is None or where is None or store.title(where):
        return
    if repo.pending_command(core.db, row, "/title"):
        return
    gateway_commands.own_command(core, workspace_id, chat_id, f"/title {title}")


def platform_said(core: Core, workspace_id: str, address: str, text: str) -> bool:
    """What Hermes says in an AGOS conversation (its command answers, notices, the
    answer itself): kept in the chat once (the answer is already there from
    turn-finish)."""
    chat_id = hermes_addresses.chat_at(core, workspace_id, address)
    text = text.strip()
    if gateway_models._own_model_switch(core, workspace_id, address, text):
        return True  # the answer to AGOS's own /model (the model he picked in AGOS)
    if gateway_commands._own_command_note(core, address, text):
        return True  # Hermes's confirmations of AGOS's own /undo, /title, /yolo
    if chat_id is None or not text or text == "✅":
        return chat_id is not None

    def same(body: str) -> bool:  # Hermes may reformat the answer a little to send it
        a, b = re.sub(r"\W+", "", body).lower(), re.sub(r"\W+", "", text).lower()
        return a == b or (min(len(a), len(b)) > 20 and (a in b or b in a))

    if any(same(body) for body in _recent_answers(core, chat_id)):
        return True  # Hermes's answer: it is in Hermes's transcript (what the chat shows)
    with transaction(core.db):
        last = repo.recent_agent_lines(core.db, chat_id, 10, 3)
        if any(same(body) for body in last):
            return True
        added = chat_writes.add_chat_message(core.db, workspace_id, chat_id, "agent", text)
        row = (
            gateway_platform.connection(core, workspace_id)
            if not address.startswith(hermes_addresses.AGOS_PREFIX)
            else None
        )
        if added is not None and row is not None:
            # Hermes sent it to Telegram itself: AGOS never sends it there again.
            outbox.queue_sent(
                core.db, int(row["id"]), hermes_addresses.address_of(address), text, f"msg:{added}"
            )
    return True


def _recent_answers(core: Core, chat_id: int) -> list[str]:
    """Hermes's answers in this conversation of the last ten minutes (its own
    transcript), and the one working now."""
    from agos_core.actions import chat as chat_actions
    from agos_core.db import hermes_chats as hc

    out: list[str] = []
    live = repo.live_turn(core.db, chat_id)
    if live is not None:
        found = chat_actions._registry(core).get(live.id)
        if found is not None:
            out.append(found.turn.final_text() or found.turn.text)
    row = repo.any_row(core.db, chat_id)
    store = hc.store()
    where = repo.where_of(core.db, row) if row is not None else None
    if store is not None and where is not None:
        since = hc.now_epoch() - 600
        out += [
            r.content for r in store.transcript(where).rows if hc.is_answer(r) and r.ts >= since
        ]
    return [t for t in out if t]
