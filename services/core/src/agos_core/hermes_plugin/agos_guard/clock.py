"""The current time on every agent turn: Hermes's own `pre_llm_call` context.

Hermes stamps a message with its time only on the gateway message path
(`gateway.message_timestamps`, H: gateway/run_turn.py `_hmwa_apply_message_timestamp`).
Rooms (group chats, TUI `prompt.submit`), cron runs, Kanban workers (`hermes chat -q`)
and subagents get no such stamp: only the session's start date in the system prompt
(H: agent/system_prompt.py). `pre_llm_call` runs on every one of those turns
(H: agent/turn_context.py `_collect_pre_llm_call_context`); its `{"context": …}` is
added to this turn's user message only, through the `api_content` sidecar that later
turns replay byte for byte, so the prompt cache stays whole (H: agent/turn_context.py
`compose_user_api_content`, `build_api_messages`).

The time is Hermes's own: its `timezone` setting (the owner's, actions/owner_time.py)
and its own format (H: gateway/message_timestamps.py `format_message_timestamp`). A
turn whose message already carries Hermes's gateway stamp gets nothing: the time is
never said twice.
"""

from __future__ import annotations

import contextlib
import re
import time
from typing import Any

# Hermes's gateway stamp, `[Fri 2026-10-16 18:40:53 BST]`, at the start of a line of
# this turn's message (Hermes may put a note of its own before it).
GATEWAY_STAMP = re.compile(
    r"(?m)^\[[A-Z][a-z]{2} \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?: [A-Za-z0-9_+\-/:]+)?\]"
)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def turn_message(history: Any) -> str:
    """This turn's user message as Hermes sends it (the last user row)."""
    for message in reversed(list(history or [])):
        if isinstance(message, dict) and message.get("role") == "user":
            return _text(message.get("content"))
    return ""


def stamped(history: Any) -> bool:
    """Hermes's gateway already put the time on this turn's message."""
    return bool(GATEWAY_STAMP.search(turn_message(history)))


def now_text() -> str:
    """Now, in Hermes's timezone and Hermes's format (without its brackets)."""
    try:
        from gateway.message_timestamps import (  # type: ignore[import-not-found]
            format_message_timestamp,
        )
        from hermes_time import get_timezone  # type: ignore[import-not-found]

        shown = str(format_message_timestamp(time.time(), tz=get_timezone()))
    except Exception as error:  # noqa: BLE001 — outside Hermes (tests): the server's own clock
        with contextlib.suppress(Exception):
            from . import bridge

            bridge._broken(
                bridge._name_of(error, "gateway.message_timestamps.format_message_timestamp"),
                error,
            )
        shown = time.strftime("[%a %Y-%m-%d %H:%M:%S %Z]")
    return shown.strip("[]")


def context(history: Any) -> dict[str, str] | None:
    """`pre_llm_call`'s answer: the current time, unless the gateway gave it."""
    if stamped(history):
        return None
    return {"context": f"[Current time: {now_text()}]"}
