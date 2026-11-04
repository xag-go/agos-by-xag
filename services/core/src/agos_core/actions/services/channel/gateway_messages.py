"""His messages that come in through Hermes's bot to AGOS: the incoming message, the
check-in hold for an off-hours agent, the Telegram files, and the 👀 / 👍 / 👎
AGOS's own answers leave.

Owns: inbound Telegram messages and their reactions.
Must not: open turns itself beyond chat_turns' API, or run commands.

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agos_core.actions.services.channel import gateway_places, gateway_platform, hermes_addresses
from agos_core.actions.services.chat import gateway_turns
from agos_core.context import Core
from agos_core.db import channel_outbox as outbox
from agos_core.db import channel_reactions as reactions
from agos_core.db import chat_turns, hermes_inbox
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction
from agos_core.engine import doorbell

__all__ = [
    "REACTION_CLAIM_S",
    "REACTION_GIVE_UP_H",
    "REACTION_SETTLE_S",
    "incoming",
    "keeps_eyes",
    "reaction_done",
    "reactions_open",
    "reactions_ready",
    "waits_for_check_in",
]


def incoming(
    core: Core,
    workspace_id: str,
    address: str,
    sender: str,
    text: str,
    message_id: str,
    reply_to: str | None,
    chat_name: str = "",
    topic_name: str = "",
    media: list[dict[str, str]] | None = None,
    answer: Callable[[int], None] | None = None,
    *,
    authorized: bool = False,
) -> bool:
    """Each message he sends the bot. True when AGOS handled it itself: the agent
    never sees it. Otherwise it joins the AGOS chat (also when Hermes passes it into
    an answer already working) and the chat shows it being answered. `authorized`:
    Hermes's own allowlist or pairing lets the sender in; anyone else never reaches
    AGOS (Hermes answers him with its pairing code)."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None:
        return False
    del reply_to
    stripped = text.strip()
    address = hermes_addresses.address_of(address)
    if not authorized:
        return True  # a stranger: never reaches AGOS or the agent
    if address.startswith("-"):
        # Every group and topic he writes in is remembered, so AGOS can offer them
        # as places to link a chat to (no ids to look up).
        group, _, thread = address.partition(":")
        gateway_places._seen_group(core, workspace_id, group, chat_name, thread, topic_name)
    target = hermes_addresses._target(core, row, address)
    if target is None or str(target["workspace_id"]) != workspace_id:
        # A group or topic no AGOS chat is linked to: the bot stays quiet there.
        return not address.endswith(":0") or address.startswith("-")
    if not stripped:
        return False
    chat_id = int(target["chat_id"])
    kind = chats_repo.any_row(core.db, chat_id)
    if kind is not None and kind["kind"] == "group":
        # An AGOS group chat in its topic: AGOS's own team relay answers it (each
        # member speaks), its replies go to the topic; Hermes stays quiet there.
        # His voice notes and files go with it.
        from agos_core.actions import chat as chat_actions

        attached = _telegram_files(core, workspace_id, media or [])
        # Hermes's own mark for a bare voice note / file: the file shows itself.
        words = "" if attached and stripped in ("🎤 Voice note", "📎 File") else stripped
        chat_actions.save_owner_message(core, workspace_id, chat_id, words, attached)
        _keep_eyes(core, row, chat_id, address, message_id)
        if answer is not None:
            answer(chat_id)  # the answer starts now (who answers: AGOS decides)
        return True
    if waits_for_check_in(core, workspace_id, address):
        _hold_for_check_in(core, workspace_id, row, address, stripped, media or [])
        return True  # Hermes stays quiet: it is answered at check-in
    # Hermes answers it in its own Telegram conversation (and keeps it there): the
    # Co-Founder's, or a member's topic that Hermes routes to that member's profile
    # (gateway.profile_routes). The chat shows it working.
    with transaction(core.db):
        gateway_turns._open_turn(
            core, workspace_id, chat_id, 0, speaker=gateway_turns._dm_speaker(core, chat_id)
        )
    return False


def waits_for_check_in(core: Core, workspace_id: str, address: str) -> bool:
    """A message to an agent that is off-hours (Settings → Work hours,
    actions/work_hours.py) waits in the queue to Hermes until its check-in."""
    from agos_core.actions import work_hours

    if not work_hours.enabled(core, workspace_id):
        return False
    chat = hermes_addresses.chat_of_address(core, workspace_id, address)
    if chat is None:
        return False
    found = (
        hermes_addresses.split_agos(address)
        if address.startswith(hermes_addresses.AGOS_PREFIX)
        else None
    )
    agent = found[1] if found and found[1] else work_hours.chat_agent(core, chat)
    return agent is not None and work_hours.holds(core, workspace_id, agent)


def _hold_for_check_in(
    core: Core,
    workspace_id: str,
    row: sqlite3.Row,
    address: str,
    text: str,
    media: list[dict[str, str]],
) -> None:
    """His Telegram message to an off agent: into the queue to Hermes (the chat shows
    it waiting), handed to its Telegram conversation at check-in; he is told once."""
    from agos_core.actions import work_hours
    from agos_core.actions.channels import _queue

    files = [
        {"path": str(m.get("path") or ""), "mime": str(m.get("mime") or "")}
        for m in media
        if isinstance(m, dict) and m.get("path")
    ]
    hermes_inbox.put(core.db, workspace_id, address, text, "message", json.dumps(files))
    doorbell.ring(doorbell.INBOX, workspace_id)  # the plugin looks now (it stays held)
    chat = hermes_addresses.chat_of_address(core, workspace_id, address)
    line = work_hours.off_line(core, workspace_id, chat) if chat is not None else None
    if line is not None:
        _queue(
            core,
            int(row["id"]),
            address,
            work_hours.off_words(line),
            f"work-hours:{line['until'] or 'off'}",
        )


def _telegram_files(core: Core, workspace_id: str, media: list[dict[str, str]]) -> list[Any]:
    """The files Hermes's Telegram saved for his message (voice note, photo, file),
    as AGOS attachments. Only files inside the workspace's own Hermes; one that is
    too big or gone is left out (his words still go)."""
    import mimetypes

    from agos_core.engine import attachments as files

    if not media or core.engine is None:
        return []
    root = core.engine.profile_home(workspace_id).resolve()
    out: list[files.Incoming] = []
    total = 0
    for item in media[: files.MAX_FILES]:
        try:
            path = Path(str(item.get("path") or "")).resolve()
            if root not in path.parents or not path.is_file():
                continue
            size = path.stat().st_size
            if not size or size > files.MAX_FILE_BYTES or total + size > files.MAX_TOTAL_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        total += size
        mime = str(item.get("mime") or "").split(";", 1)[0].strip().lower()
        if not mime or "/" not in mime:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime in files.AUDIO_TYPES:
            kind = "audio"
        elif mime in files.IMAGE_TYPES:
            kind = "image"
        else:
            kind = "file"
        out.append(files.Incoming(kind=kind, name=files.safe_name(path.name), mime=mime, data=data))  # type: ignore[arg-type]
    return out


REACTION_SETTLE_S = 3  # a group's next speaker starts within this after one ends
REACTION_GIVE_UP_H = 6  # an answer that never ends: 👎, never an 👀 left forever
REACTION_CLAIM_S = 30


def _keep_eyes(core: Core, row: sqlite3.Row, chat_id: int, address: str, message_id: str) -> None:
    """His message in a chat AGOS answers itself: Hermes's 👀 stays on it until
    that answer is out (Hermes's own reaction then says how it went)."""
    if not str(message_id or "").isdigit():
        return
    reactions.add(core.db, int(row["id"]), chat_id, address.partition(":")[0], str(message_id))
    doorbell.ring(doorbell.OUTBOX)


def keeps_eyes(core: Core, workspace_id: str, address: str, message_id: str) -> bool:
    """Whether Hermes keeps its 👀 on this message (its answer is AGOS's)."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None or not str(message_id or "").isdigit():
        return False
    return reactions.open_for(core.db, int(row["id"]), address.partition(":")[0], str(message_id))


def _reaction_outcome(core: Core, conn_id: int, r: sqlite3.Row) -> str | None:
    """How the answer to his message went, once it is out; None while it works."""
    chat_id = int(r["chat_id"])
    old = reactions.older_than(core.db, str(r["created_at"]), REACTION_GIVE_UP_H)
    give_up = "failure" if old else None
    from agos_core.actions import chat as chat_actions

    if chats_repo.live_turn(core.db, chat_id) is not None or chat_actions.pending(core, chat_id):
        return give_up
    last = chat_turns.last_settled(core.db, chat_id, REACTION_SETTLE_S)
    if last is None or not last["settled"]:
        return give_up  # none yet, or the next member may be about to speak
    status = str(last["status"])  # how Hermes ended it (its on_session_end, turn_ended)
    if status == "stopped":
        return "cancelled"
    if status != "completed":
        return "failure"
    source = (
        f"msg:{int(last['reply_id'])}" if last["reply_id"] is not None else f"turn:{last['id']}"
    )
    sends = outbox.sends_of(core.db, conn_id, source)
    if not sends and last["reply_id"] is None:
        return "success"
    if any(s["sent_id"] for s in sends):
        return "success"  # the answer is in Telegram
    if sends and all(int(s["attempts"]) >= 5 for s in sends):
        return "failure"  # Telegram never took it
    return give_up  # not sent yet


def reactions_open(core: Core, workspace_id: str) -> bool:
    """His messages still waiting for their 👍 / 👎: when it is due is a time (the
    answer settled), which nothing rings for (the gateway's outbox looks often)."""
    conn = gateway_platform.connection(core, workspace_id)
    return conn is not None and reactions.waiting(core.db, int(conn["id"]))


def reactions_ready(core: Core, workspace_id: str, limit: int = 20) -> list[dict[str, str]]:
    """His messages whose answer (AGOS's) is out: the gateway's Hermes swaps its 👀
    for its own 👍 / 👎 (or clears it when the answer was stopped)."""
    conn = gateway_platform.connection(core, workspace_id)
    if conn is None:
        return []
    conn_id = int(conn["id"])
    rows = reactions.due(core.db, conn_id, REACTION_CLAIM_S)
    out: list[dict[str, str]] = []
    for r in rows:
        outcome = _reaction_outcome(core, conn_id, r)
        if outcome is None:
            continue
        reactions.outcome(core.db, int(r["id"]), outcome)
        out.append(
            {
                "id": str(r["id"]),
                "chat": str(r["tg_chat"]),
                "messageId": str(r["tg_message"]),
                "outcome": outcome,
            }
        )
        if len(out) >= limit:
            break
    return out


def reaction_done(core: Core, workspace_id: str, row_id: int, error: str | None) -> None:
    conn = gateway_platform.connection(core, workspace_id)
    if conn is None:
        return
    if error:
        reactions.failed(core.db, row_id, int(conn["id"]))
        return
    reactions.done(core.db, row_id, int(conn["id"]))
