"""Small readers of Hermes's events: a message's text, whether a conversation is on
Telegram or on AGOS's own agos platform (the conversations AGOS shows), and a forum
topic's name from Telegram's own message.

Owns: those pure readers (no state, no I/O).
Must not: hold state or talk to AGOS (bridge_core does both).

Part of the agos-guard bridge (moved out of bridge_core.py; bridge.py re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import sys
from typing import Any

__all__: list[str] = []

try:
    from . import bridge_core
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]


def _text_of(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return "\n".join(
            str(p.get("text") or "") for p in message if isinstance(p, dict) and p.get("text")
        )
    return ""


def _is_telegram(platform: Any) -> bool:
    return str(getattr(platform, "value", platform) or "").lower() == "telegram"


def _topic_name(event: Any) -> str:
    """The forum topic's name, from Telegram's own message (the topic's first
    message, which messages in a topic hang from, carries it)."""
    raw = getattr(event, "raw_message", None)
    for message in (raw, getattr(raw, "reply_to_message", None)):
        for field in ("forum_topic_created", "forum_topic_edited"):
            name = getattr(getattr(message, field, None), "name", None)
            if name:
                return str(name)
    return ""


def _is_agos(platform: Any) -> bool:
    return str(getattr(platform, "value", platform) or "").lower() == bridge_core.AGOS_PLATFORM


def _ours(platform: Any) -> bool:
    """A conversation AGOS shows: a Telegram chat, or AGOS's own (agos platform)."""
    return _is_telegram(platform) or _is_agos(platform)
