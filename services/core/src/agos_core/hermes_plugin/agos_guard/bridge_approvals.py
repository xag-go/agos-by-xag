"""Hermes's Allow / Deny cards for a conversation AGOS shows: where the card goes
(the chat's Telegram place), AGOS told when it is asked and answered, and the
cards kept to close them from AGOS.

Owns: approval requests and answers seen by AGOS.
Must not: decide an approval (Hermes and the owner do).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

__all__ = [
    "post_approval_response",
    "pre_approval_request",
]

try:
    from . import bridge_core, bridge_sessions
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]


def _watch_cards(adapter: Any) -> None:
    """Remember which Telegram message holds each Allow/Deny card (to close it when he
    answers in AGOS). Wraps the adapter's public send_exec_approval; nothing else."""
    send = getattr(adapter, "send_exec_approval", None)
    if send is None or getattr(send, "_agos_watch", False):
        return

    async def send_exec_approval(*args: Any, **kwargs: Any) -> Any:
        result = await send(*args, **kwargs)
        bridge_core._ctx["loop"] = bridge_core._process()["loop"] = asyncio.get_running_loop()
        session_key = kwargs.get("session_key") or (args[2] if len(args) > 2 else "")
        chat_id = kwargs.get("chat_id") or (args[0] if args else "")
        if getattr(result, "success", False) and getattr(result, "message_id", None):
            with bridge_core._lock:
                bridge_core._cards[str(session_key)] = (str(chat_id), str(result.message_id))
        return result

    send_exec_approval._agos_watch = True  # type: ignore[attr-defined]
    adapter.send_exec_approval = send_exec_approval
    bridge_core._ctx["adapter"] = adapter
    # Every profile's AGOS conversations show their approvals on this bot.
    bridge_core._process()["telegram"] = adapter


def _allowed_users() -> set[str]:

    return {
        u.strip() for u in (os.environ.get("TELEGRAM_ALLOWED_USERS") or "").split(",") if u.strip()
    }


def _chat_of(session_key: str) -> str | None:
    """The address of the chat a session key belongs to (Hermes's key layout:
    `agent:<profile>:<platform>:<chat type>:<chat>[:<thread>]`, H: gateway/session.py
    `build_session_key`), also after a restart when this gateway has seen no
    message there yet: a group's topic, a member's routed topic, a private chat."""
    for address, key in list(bridge_core._keys.items()):
        if key == session_key:
            return address
    marker = f":{bridge_core.AGOS_PLATFORM}:dm:"
    if marker in (session_key or ""):
        number = session_key.rsplit(":", 1)[-1]  # "<chat>" or "<chat>.<member>"
        head, _, member = number.partition(".")
        # "<chat>" or "l<n>" (the learning conversation), then ".<member>" in a group
        bare = head[1:] if head[:1] == "l" else head
        ok = bare.isdigit() and all(ch.isalnum() or ch in "_-" for ch in member)
        return bridge_core.AGOS_ADDRESS + number if ok else None
    for kind in ("group", "dm"):
        marker = f":telegram:{kind}:"
        if marker not in (session_key or ""):
            continue
        # Groups: "<chat>[:<thread>][:<user>]" (the user only outside a topic, with
        # Hermes's default group_sessions_per_user); a private chat: "<chat>[:<thread>]".
        parts = session_key.split(marker, 1)[1].split(":")
        chat = parts[0]
        thread = parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
        if kind == "group" and len(parts) == 2 and thread in _allowed_users():
            thread = ""  # "<chat>:<user>": the group itself, his own session there
        if not chat.lstrip("-").isdigit():
            return None
        return bridge_sessions._address(chat, thread or None)
    return None


def pre_approval_request(
    command: str = "",
    description: str = "",
    pattern_key: str = "",
    session_key: str = "",
    surface: str = "",
    **_: Any,
) -> None:
    """Hermes asks Allow / Deny in Telegram: AGOS shows the same card."""
    chat = _chat_of(session_key)
    if surface != "gateway" or chat is None or bridge_core.bridge() is None:
        return
    answer = bridge_core.post(
        "approval",
        {"chat": chat, "command": command, "description": description, "pattern": pattern_key},
        15,
    )
    phone = (answer or {}).get("phone")
    with bridge_core._lock:
        if isinstance(phone, dict) and str(phone.get("chat") or "").lstrip("-").isdigit():
            bridge_core._phone[session_key] = {
                "chat": str(phone["chat"]),
                "thread": str(phone.get("thread") or ""),
            }
        else:
            bridge_core._phone.pop(session_key, None)


def post_approval_response(
    session_key: str = "", surface: str = "", choice: Any = "", **_: Any
) -> None:
    """Answered (here or from AGOS): AGOS closes its card too."""
    chat = _chat_of(session_key)
    if surface != "gateway" or chat is None or bridge_core.bridge() is None:
        return
    bridge_core.post("approval-done", {"chat": chat, "choice": str(choice or "")[:40]}, 15)
