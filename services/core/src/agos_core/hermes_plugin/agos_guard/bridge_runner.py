"""Handing AGOS's items to Hermes's gateway runner as if they came in on a platform:
a message or a /command he wrote in AGOS, its media, bound to the conversation's
session, and the wait for its answer.

Owns: building and running Hermes message events for AGOS's items.
Must not: poll AGOS or deliver to Telegram (bridge_delivery).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from typing import Any

__all__ = [
    "MEDIA_KINDS",
    "sent_at",
]

try:
    from . import bridge_core, bridge_sessions
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]


log = logging.getLogger("agos.bridge")


def _took_from_agos(address: str, text: str) -> bool:
    """This admitted message is one AGOS put in here (his, typed in AGOS): once."""
    with bridge_core._lock:
        waiting = bridge_core._from_agos.get(address) or []
        if text in waiting:
            waiting.remove(text)
            return True
    return False


def _run_command(address: str, text: str) -> bool:
    """A /command he typed in AGOS runs as if he typed it in this Telegram chat (he
    is the owner in both): Hermes's own command handling, with its own answer.
    Plugin injections can't run gateway commands, so it goes in as his message."""
    return _run_event(address, {"text": text}, command=True)


def _run_message(address: str, item: dict[str, Any]) -> bool:
    """His message from AGOS goes into this Telegram conversation as if he sent it
    here, his files with it: Hermes hears his voice notes (its own speech-to-text)
    and looks at his pictures itself, as for a message sent on Telegram
    (H: gateway/run_inbound.py `_prepare_inbound_message_text`). Plugin injections
    carry text only (H: hermes_cli/plugins.py `inject_message`)."""
    return _run_event(address, item)


MEDIA_KINDS = {"audio": "VOICE", "image": "PHOTO"}  # else a document


def _run_event(address: str, item: dict[str, Any], *, command: bool = False) -> bool:
    with bridge_core._lock:
        source = bridge_core._sources.get(address)
    adapter, loop = bridge_core._ctx["adapter"], bridge_core._ctx["loop"]
    if adapter is None or loop is None:
        return False  # the bot isn't connected yet: AGOS hands it again
    if source is None:
        source = bridge_sessions._source_for(adapter, address)
    if source is None:
        return False
    from gateway.platforms.event import MessageEvent, MessageType  # type: ignore[import-not-found]

    media = [m for m in item.get("media") or [] if isinstance(m, dict) and m.get("path")]
    kind = MessageType.COMMAND if command else MessageType.TEXT
    if media and not command:
        kind = getattr(MessageType, MEDIA_KINDS.get(str(media[0].get("kind")), "DOCUMENT"))
    event = MessageEvent(
        text=str(item.get("text") or ""),
        message_type=kind,
        source=source,
        media_urls=[str(m["path"]) for m in media],
        media_types=[str(m.get("mime") or "") for m in media],
        metadata={bridge_core.FROM_AGOS: True},
        timestamp=sent_at(item),
    )
    # AGOS puts no file text in his words: Hermes's own note then says "read the
    # saved file" (MessageEvent.media_text_inlined, gateway/run.py).
    event.media_text_inlined = [False] * len(media)
    with bridge_core._lock:
        kept = bridge_core._from_agos.setdefault(address, [])
        kept.append(event.text or "")
        del kept[:-20]
    future = asyncio.run_coroutine_threadsafe(adapter.handle_message(event), loop)
    with contextlib.suppress(Exception):
        future.result(timeout=30)
    return True


def _bind(address: str, body: str) -> bool:
    """A member's topic continues the member's conversation from before (AGOS's
    agos platform): the topic's session key points at that session, the way
    Hermes's own /resume does it (SessionStore.switch_session). Only for a topic
    whose key has no conversation yet, and only once Hermes routes the topic to
    that member (gateway.profile_routes stamps it on the source). True: done or
    nothing to do; False: the bot isn't up yet (AGOS hands it again)."""
    try:
        wanted = json.loads(body)
        session, profile = str(wanted["session"]), str(wanted["profile"])
    except (ValueError, KeyError, TypeError):
        return True
    adapter = bridge_core._ctx.get("adapter")
    store = getattr(bridge_sessions._runner(), "session_store", None)
    if adapter is None or store is None:
        return False
    source = bridge_sessions._source_for(adapter, address)
    if source is None:
        return False
    if str(getattr(source, "profile", "") or "") != profile:
        log.warning("AGOS bridge: %s isn't routed to %s; its conversation stays", address, profile)
        return True
    key = bridge_sessions._session_key_of(source)
    if store.lookup_by_session_key(key) is not None:
        return True  # the topic already has its conversation
    entry = store.get_or_create_session(source)
    if entry is not None and entry.session_id != session:
        store.switch_session(key, session, preserve_prompt_pin=False)
    bridge_sessions._remember_key(address, key)
    log.info("AGOS bridge: %s continues session %s (%s)", address, session, profile)
    return True


def _await_answer(chat: str, address: str) -> None:
    import time

    with bridge_core._lock:
        bridge_core._awaiting[chat] = (time.monotonic() + bridge_core.COMMAND_WINDOW_S, address)


def sent_at(item: dict[str, Any]) -> Any:
    """When he sent an AGOS message (its queue time, UTC), as Hermes's event time;
    now when AGOS didn't say (Hermes's own default)."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(item.get("createdAt") or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()
