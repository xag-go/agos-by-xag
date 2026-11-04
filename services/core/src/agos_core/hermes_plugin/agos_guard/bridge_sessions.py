"""Which Hermes conversation a Telegram chat or AGOS address is: AGOS's address of a
chat (and topic), this gateway's session key for it, Hermes's own session index
and gateway runner.

Owns: chat/address <-> Hermes session key lookups (read only on Hermes).
Must not: run messages or send anything.

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any

__all__ = [
    "drop_old_keys_file",
]

try:
    from . import bridge_core, bridge_text
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_text = sys.modules["agos_guard_bridge_text"]


def _address(chat: Any, thread: Any = None) -> str:
    """AGOS's address of a Telegram chat: "<chat id>:<topic id>" (no topic = 0)."""
    chat = str(chat or "")
    return chat if ":" in chat else f"{chat}:{thread or 0}"


def _remember_key(address: str, key: str) -> None:
    if address and key:
        bridge_core._keys[address] = key


def drop_old_keys_file() -> None:
    """The plugin's own copy of the chat → session-key map goes (once; safe to
    repeat): Hermes's session index holds it (H: gateway/session.py list_sessions,
    persisted to state.db and its sessions.json mirror, gateway/session_persistence.py:482)."""
    home = bridge_core._home()
    if home is not None:
        with contextlib.suppress(OSError):
            (home / bridge_core.OLD_KEYS_FILE).unlink(missing_ok=True)


def _key_in_hermes(chat: str, thread: str) -> str:
    """The newest Hermes session of this Telegram chat (or topic), from Hermes's own
    session index: the gateway's SessionStore (an entry's origin is the chat it came
    from), or, with no store in this process, its sessions.json mirror."""
    store = getattr(_runner(), "session_store", None)
    if store is not None:
        with bridge_core._guard("gateway.session.SessionStore.list_sessions"):
            for entry in store.list_sessions():  # newest first
                origin = getattr(entry, "origin", None)
                if (
                    origin is not None
                    and bridge_text._is_telegram(getattr(origin, "platform", None))
                    and str(getattr(origin, "chat_id", "") or "") == chat
                    and str(getattr(origin, "thread_id", "") or "0") == thread
                ):
                    return str(entry.session_key)
            return ""
    home = bridge_core._home()
    if home is None:
        return ""
    ends = (f":telegram:dm:{chat}",) if thread == "0" else (f":{chat}:{thread}",)
    with contextlib.suppress(OSError, ValueError, AttributeError):
        index = json.loads((home / "sessions" / "sessions.json").read_text())
        found = [
            (str((v or {}).get("updated_at") or ""), k)
            for k, v in index.items()
            if ":telegram:" in k
            and (k.endswith(ends) or (thread == "0" and k.endswith(f":{chat}")))
        ]
        if found:
            return str(max(found)[1])
    return ""


def _key_for(address: str) -> str:
    """This gateway's session key for the chat (or topic): Hermes's own key for the
    place when it has a conversation there (a routed topic: the member's profile),
    else the one its last message used, else the newest in Hermes's session index,
    else Hermes's standalone default."""
    if address.startswith(bridge_core.AGOS_ADDRESS):
        return (
            bridge_core._keys.get(address)
            or f"agent:main:{bridge_core.AGOS_PLATFORM}:dm:{address[len(bridge_core.AGOS_ADDRESS) :]}"
        )
    address = _address(address)
    chat, thread = address.split(":", 1)
    adapter = bridge_core._ctx.get("adapter")
    if adapter is not None:
        with bridge_core._guard("gateway.session.build_session_key"):
            source = _source_for(adapter, address)
            if source is not None:
                own = _session_key_of(source)
                if _has_session(own):
                    return own
    if address in bridge_core._keys:
        return bridge_core._keys[address]
    return _key_in_hermes(chat, thread) or f"agent:main:telegram:dm:{chat}"


def _source_for(adapter: Any, address: str) -> Any:
    """His chat as Hermes's Telegram adapter builds it (after a restart, before he
    writes there again): the bot's owner, in that chat / topic."""

    owner = (os.environ.get("TELEGRAM_ALLOWED_USERS") or "").split(",")[0].strip()
    chat, _, thread = address.partition(":")
    if not owner:
        return None
    with bridge_core._guard("plugins.platforms.telegram.adapter.TelegramAdapter.build_source"):
        return adapter.build_source(
            chat_id=chat,
            chat_type="group" if chat.startswith("-") else "dm",
            user_id=owner,
            thread_id=thread if thread and thread != "0" else None,
        )
    return None


def _runner() -> Any:
    """Hermes's own running gateway (gateway.run keeps a weak reference to it): its
    session key settings and session store, for a member topic's routing and its
    one-time bind to the conversation from before (Hermes's /resume refuses a
    cross-platform resume, H: gateway/slash_commands_session.py)."""
    with bridge_core._guard("gateway.run._gateway_runner_ref"):
        import importlib

        return importlib.import_module("gateway.run")._gateway_runner_ref()
    return None


def _session_key_of(source: Any) -> str:
    """Hermes's session key for a source its adapter built (the profile a route
    stamped on it included): Hermes's own key builder, with its gateway's settings."""
    from gateway.session import build_session_key  # type: ignore[import-not-found]

    config = getattr(_runner(), "config", None)
    return str(
        build_session_key(
            source,
            group_sessions_per_user=bool(getattr(config, "group_sessions_per_user", True)),
            thread_sessions_per_user=bool(getattr(config, "thread_sessions_per_user", False)),
            profile=getattr(source, "profile", None),
        )
    )


def _has_session(key: str) -> bool:
    store = getattr(_runner(), "session_store", None)
    if store is None:
        return True  # nothing to check: Hermes's injection says itself
    with bridge_core._guard("gateway.session.SessionStore.lookup_by_session_key"):
        return store.lookup_by_session_key(key) is not None
    return True
