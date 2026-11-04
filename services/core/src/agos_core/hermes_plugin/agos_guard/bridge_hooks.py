"""Hermes's gateway and LLM hooks that keep AGOS's chat in step with a turn: a message
admitted, the turn's start and end (sent surely, retried in order), a stop, the
language note and the owner's rules as system-prompt sections.

Owns: turn start/finish/stop reporting to AGOS.
Must not: deliver AGOS's outbox or run AGOS's items (bridge_delivery, bridge_runner).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import threading
from typing import Any

__all__ = [
    "ENDS_RETRY_S",
    "LANGUAGE_NOTE",
    "OWNER_RULES_SECTION",
    "OWNER_RULES_SECTIONS",
    "agent_loop_stopped",
    "agent_of_session",
    "on_session_end",
    "owner_rules_part",
    "owner_rules_section",
    "post_gateway_admission",
    "post_llm_call",
    "pre_gateway_dispatch",
    "pre_llm_call",
]

try:
    from . import (
        bridge_approvals,
        bridge_core,
        bridge_delivery,
        bridge_platform,
        bridge_runner,
        bridge_sessions,
        bridge_stream,
        bridge_text,
    )
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_approvals = sys.modules["agos_guard_bridge_approvals"]
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_delivery = sys.modules["agos_guard_bridge_delivery"]
    bridge_platform = sys.modules["agos_guard_bridge_platform"]
    bridge_runner = sys.modules["agos_guard_bridge_runner"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]
    bridge_stream = sys.modules["agos_guard_bridge_stream"]
    bridge_text = sys.modules["agos_guard_bridge_text"]


log = logging.getLogger("agos.bridge")


async def pre_gateway_dispatch(
    event: Any = None, gateway: Any = None, **_: Any
) -> dict[str, str] | None:
    """Each Telegram message, before Hermes's own checks: only what must be AGOS's
    before Hermes acts. A member of a group's room called by its command
    (/ideas_generator …) is AGOS's; Hermes's own /commands are shown in the AGOS chat
    too. Who may write is Hermes's: AGOS reads his /command's sender against
    Hermes's own allowlist and pairing; every other message reaches AGOS only once
    Hermes admitted it (post_gateway_admission).

    A key he pastes is masked by Hermes's own masking first (keys.py, ADR 0023):
    Hermes's {"action": "rewrite"} puts the masked text, with a note for the agent,
    in place of his before Hermes keeps or answers it (H: gateway/run_inbound.py
    _hm_pre_gateway_dispatch_hook; only the first rewrite/allow counts, so it is this
    hook's own answer, also when it hands a /command to AGOS)."""
    if event is None or getattr(event, "internal", False) or bridge_core.bridge() is None:
        return None
    if (getattr(event, "metadata", None) or {}).get(bridge_core.FROM_AGOS):
        return None  # his own command typed in AGOS, already in the AGOS chat
    source = getattr(event, "source", None)
    if source is not None and bridge_text._is_agos(getattr(source, "platform", None)):
        bridge_platform._agos_arrived(event, gateway, source)
        return None  # AGOS already has it (it came from there)
    if source is None or not bridge_text._is_telegram(getattr(source, "platform", None)):
        return None
    text = str(getattr(event, "text", "") or "")
    hidden = _hide_keys(text)
    if hidden is not None:
        text = hidden
    rewrite = {"action": "rewrite", "text": text} if hidden is not None else None
    address = bridge_sessions._address(source.chat_id, getattr(source, "thread_id", None))
    bridge_core._ctx["loop"] = asyncio.get_running_loop()
    _keep_inbound(event, source)
    sender = str(getattr(source, "user_id", "") or "")
    if text.startswith("/") and address.startswith("-"):
        # In a group: a member's command (/ideas_generator …) is that member's message.
        took = await asyncio.to_thread(
            bridge_core.post,
            "member-command",
            {
                "chat": address,
                "sender": sender,
                "text": text,
                "messageId": str(getattr(event, "message_id", "") or ""),
            },
            15,
        )
        if took and took.get("handled"):
            bridge_delivery._eyes_stay(source.chat_id, getattr(event, "message_id", ""), took)
            return {"action": "skip", "reason": "handled by AGOS"}
    if text.startswith("/"):
        # Hermes's own command (/new, /status, …): Hermes runs and answers it itself;
        # the AGOS chat shows the command and Hermes's answer (one conversation).
        said = await asyncio.to_thread(
            bridge_core.post, "command", {"chat": address, "sender": sender, "text": text}, 15
        )
        if said and said.get("shown"):
            bridge_runner._await_answer(str(source.chat_id), address)
    return rewrite


_keys_told: set[str] = set()


def _keys_module() -> Any:
    """keys.py beside this file (Hermes's masking of his messages), however loaded."""
    return bridge_core._beside("keys")


def _hide_keys(text: str) -> str | None:
    """His message with any key masked by Hermes and the note (no note on a
    /command), None when nothing was hidden. Hermes's masking not there: the message
    goes on unchanged, said once (the Secrets check finds such a key later)."""
    if not text:
        return None
    with bridge_core._guard("agent.redact.redact_sensitive_text"):
        hidden: str | None = _keys_module().owner_text(text, command=text.startswith("/"))
        return hidden
    if not _keys_told:
        _keys_told.add("told")
        log.warning("AGOS bridge: keys in his messages are not checked (Hermes's masking failed)")
    return None


def _keep_inbound(event: Any, source: Any) -> None:
    """What only Hermes's event carries, for when Hermes admits the message: where
    it saved his voice note / photo / file, its kind, the topic's name."""
    kind = str(getattr(getattr(event, "message_type", ""), "value", "") or "")
    info = {
        "kind": kind,
        "replyTo": getattr(event, "reply_to_message_id", None) or None,
        "chatName": str(getattr(source, "chat_name", "") or "")[:200],
        "topicName": bridge_text._topic_name(event)[:200],
        "media": [
            {"path": str(p), "mime": str(t or "")}
            for p, t in zip(
                list(getattr(event, "media_urls", None) or [])[:8],
                list(getattr(event, "media_types", None) or []) + [""] * 8,
                strict=False,
            )
            if p
        ],
    }
    with bridge_core._lock:
        if len(bridge_core._inbound) >= bridge_core.INBOUND_MAX:
            bridge_core._inbound.clear()  # left over from messages Hermes never admitted
        bridge_core._inbound[(str(source.chat_id), str(getattr(event, "message_id", "") or ""))] = (
            info
        )


async def post_gateway_admission(
    session_key: str = "",
    platform: str = "",
    source: Any = None,
    message_id: Any = "",
    text: str = "",
    **_: Any,
) -> dict[str, str] | None:
    """A Telegram message Hermes admitted (its allowlist, pairing, pause, pending
    replies and busy lanes are behind it; H: gateway/run_inbound_consumer.py) and is
    about to answer, in the profile that answers it. It joins the AGOS chat (the
    chat shows it being answered); one AGOS answers itself (a group's room) or a
    place with no AGOS chat is consumed: Hermes stays quiet there."""
    if (
        not bridge_text._is_telegram(platform)
        or not isinstance(source, dict)
        or bridge_core.bridge() is None
    ):
        return None
    message_id = str(message_id or "")
    chat = str(source.get("chat_id") or "")
    if not chat:
        return None
    address = bridge_sessions._address(chat, source.get("thread_id"))
    if bridge_runner._took_from_agos(address, str(text or "")):
        return None  # his message from AGOS (the chat already has it)
    bridge_sessions._remember_key(address, str(session_key or ""))
    with bridge_core._guard("gateway.session.SessionSource.from_dict"):
        from gateway.session import SessionSource  # type: ignore[import-not-found]

        restored = SessionSource.from_dict(source)
        with bridge_core._lock:
            bridge_core._sources[address] = restored  # where a command he types in AGOS is run from
    with bridge_core._lock:
        info = bridge_core._inbound.pop((chat, message_id), None) or {}
        bridge_core._unread.pop(address, None)
    words = str(text or "")
    if not words.strip() and info.get("media"):
        # Hermes reads it first (its own transcript of a voice note): AGOS shows
        # the words once the answer starts.
        words = "🎤 Voice note" if info.get("kind") in ("voice", "audio") else "📎 File"
        with bridge_core._lock:
            bridge_core._unread[address] = "replace"
    answer = await asyncio.to_thread(
        bridge_core.post,
        "incoming",
        {
            "chat": address,
            "sender": str(source.get("user_id") or ""),
            "text": words,
            "messageId": message_id,
            "replyTo": info.get("replyTo"),
            "chatName": str(info.get("chatName") or source.get("chat_name") or "")[:200],
            "topicName": str(info.get("topicName") or "")[:200],
            # A chat AGOS answers itself (a group's room) passes his files on.
            "media": list(info.get("media") or []),
            "authorized": True,  # Hermes admitted him
        },
        15,
    )
    if answer and answer.get("handled"):
        bridge_delivery._eyes_stay(chat, message_id, answer)
        return {"action": "handled"}
    return None


def _here(sender_id: Any, platform: Any = "telegram") -> str:
    """The chat (and topic) this answer is for; a private chat's id is the sender's."""
    if bridge_text._is_agos(platform):
        with bridge_core._guard("gateway.session_context.get_session_env"):
            from gateway.session_context import get_session_env  # type: ignore[import-not-found]

            return bridge_core.AGOS_ADDRESS + str(get_session_env("HERMES_SESSION_CHAT_ID", ""))
        return ""
    chat, thread = "", ""
    with bridge_core._guard("gateway.session_context.get_session_env"):
        from gateway.session_context import get_session_env

        chat = get_session_env("HERMES_SESSION_CHAT_ID", "")
        thread = get_session_env("HERMES_SESSION_THREAD_ID", "")
    return bridge_sessions._address(chat or sender_id, thread if chat else None)


def pre_llm_call(
    session_id: str = "",
    turn_id: str = "",
    platform: str = "",
    sender_id: str = "",
    user_message: Any = "",
    conversation_history: Any = None,
    **_: Any,
) -> dict[str, str] | None:
    """An answer starts: AGOS opens its turn, to show it. Added to this turn's message
    (Hermes's own pre_llm_call context, never the system prompt): the current time on
    a turn Hermes's gateway didn't stamp (clock.py), and on a person's message in a
    chat AGOS shows, which language to answer in (LANGUAGE_NOTE)."""
    try:
        _turn_opens(str(session_id), str(turn_id), str(platform), sender_id, user_message)
    except Exception:  # the turn goes on (and keeps its time) without AGOS's view
        log.exception("AGOS bridge: turn start not reported")
    notes = []
    try:
        from . import clock

        timed = clock.context(conversation_history)
        if timed:
            notes.append(timed["context"])
    except ImportError:
        pass
    if sender_id and bridge_text._ours(platform):
        notes.append(LANGUAGE_NOTE)
    return {"context": "\n".join(notes)} if notes else None


# The owner's rule "answer in my language" sits in the system prompt (SOUL.md), far from
# a long turn's end: after tools, notices in English or Hermes's own notes around his
# words ("Gateway message origin …"), answers slid into English. Said again next to
# his words on every turn of his, it holds (same text each turn: the cache stays whole).
LANGUAGE_NOTE = (
    "[Language: answer in the language and alphabet of the person's own words (not the "
    "notes, notices or quotes around them; when this message has none, their last "
    "message). Darija in Latin letters (3/7/9) stays Darija in Latin letters. Keep it for "
    "every message of this turn, also after tools; never switch to English on your own.]"
)


def _turn_opens(
    session_id: str, turn_id: str, platform: str, sender_id: Any, user_message: Any
) -> None:
    if not bridge_text._ours(platform) and bridge_core.bridge() is not None:
        _room_turn(str(session_id), str(turn_id), user_message)
    if not bridge_text._ours(platform) or not sender_id or bridge_core.bridge() is None:
        return None
    here = _here(sender_id, platform)
    with bridge_core._lock:
        how = bridge_core._unread.pop(here, "")
        bridge_core._busy[(str(session_id), str(turn_id))] = here
        bridge_core._awaiting.pop(here.split(":", 1)[0], None)  # it became a request for the agent
    said = bridge_text._text_of(user_message) if how else ""
    body = {"chat": here, "sessionId": str(session_id), "said": said, "how": how}
    answer = bridge_core.post("turn-start", {**body, "sender": str(sender_id)[:40]})
    bridge_core._taint().opened(
        str(session_id), here, str(sender_id), answer, user_message, bridge_core.post
    )
    if not answer:
        return None
    if answer.get("turnId"):
        key = ""
        with bridge_core._guard("gateway.session_context.get_session_env"):
            from gateway.session_context import get_session_env

            key = get_session_env("HERMES_SESSION_KEY", "")
        if not key:  # no session vars in this thread: the chat's own key (its last message's)
            with contextlib.suppress(Exception):
                key = bridge_sessions._key_for(here)
        with bridge_core._lock:
            bridge_core._turns[(str(session_id), str(turn_id))] = int(answer["turnId"])
            if key:
                bridge_core._turn_keys[(str(session_id), str(turn_id))] = str(key)
    if "agent" in answer:
        with bridge_core._lock:
            _agents[str(session_id)] = str(answer.get("agent") or "")
    return None


def _room_turn(session_id: str, turn_id: str, user_message: Any) -> None:
    """A Hermes room turn (ADR 0020): its AGOS tools act for the room's group chat,
    and the owner's Autonomy rules of that member apply to its tool calls."""
    try:
        from . import rooms
    except ImportError:
        return
    found = rooms.room_address(user_message)
    if found is None:
        return
    where, handle = found
    with bridge_core._lock:
        if len(bridge_core._busy) > 500:
            bridge_core._busy.clear()
        bridge_core._busy[(session_id, turn_id)] = where
        # "manager": the handle before step 44 (a room made before it, until remade)
        _agents[session_id] = "" if handle in ("cofounder", "manager") else handle


# session id -> the agent answering in it ("" = the Co-Founder), from AGOS at turn-start:
# the owner's Autonomy rules for that agent apply to its tool calls.
_agents: dict[str, str] = {}


def agent_of_session(session_id: str) -> str:
    with bridge_core._lock:
        return _agents.get(str(session_id), "")


def _end(session_id: str, turn_id: str) -> int | None:
    """The answer is over here: its AGOS turn (None: none open), its live text sent."""
    import time

    with bridge_core._lock:
        agos_turn = bridge_core._turns.pop((str(session_id), str(turn_id)), None)
        bridge_core._turn_keys.pop((str(session_id), str(turn_id)), None)
        here = bridge_core._busy.pop((str(session_id), str(turn_id)), None)
        if here:
            bridge_stream._ended[here] = time.monotonic()
    if agos_turn is None:
        return None
    bridge_stream._live_add(agos_turn, {}, flush=True)
    bridge_stream._live_sent()  # its live text reached AGOS before its end does
    with bridge_core._lock:
        bridge_stream._live.pop(agos_turn, None)
        if len(_closed) > 500:
            _closed.clear()
        _closed[(str(session_id), str(turn_id))] = agos_turn  # how it ended comes next
    return agos_turn


# Turns whose answer is out (or stopped), until Hermes says how they ended.
_closed: dict[tuple[str, str], int] = {}


def _finish(session_id: str, turn_id: str, text: str) -> None:
    agos_turn = _end(session_id, turn_id)
    if agos_turn is None:
        return
    # Only its answer: how it ended comes from on_session_end; its model and tokens
    # are Hermes's own (its sessions, session_model_usage), read by AGOS there.
    _tell_surely("turn-finish", {"turnId": agos_turn, "text": text})


# A turn's end must reach AGOS even when its core is restarting right then (every
# ship restarts it, and the gateways keep running): otherwise the AGOS turn stays
# "running" and the answer never shows in his chat. What didn't get through waits
# here and is sent again for a few minutes, in order (an end before its answer would
# close the turn without the answer).
_ends_lock = threading.Lock()
_ends_backlog: list[tuple[str, dict[str, Any]]] = []
_ends_sending = False
ENDS_RETRY_S = (2, 4, 8, 15, 30, 60, 60, 60)


def _tell_surely(path: str, body: dict[str, Any]) -> None:
    global _ends_sending
    with _ends_lock:
        if not _ends_backlog and (
            bridge_core.post(path, body, 60) is not None or bridge_core.bridge() is None
        ):
            return
        _ends_backlog.append((path, body))
        if _ends_sending:
            return
        _ends_sending = True
    threading.Thread(target=_send_backlog, daemon=True, name="agos-turn-ends").start()


def _send_backlog() -> None:
    import time

    global _ends_sending
    while True:
        with _ends_lock:
            if not _ends_backlog:
                _ends_sending = False
                return
            path, body = _ends_backlog[0]
        for wait in ENDS_RETRY_S:
            time.sleep(wait)
            if bridge_core.post(path, body, 60) is not None:
                break
        else:
            log.warning("AGOS bridge %s never reached AGOS (turn %s)", path, body.get("turnId"))
        with _ends_lock:
            _ends_backlog.pop(0)


def on_session_end(
    session_id: str = "",
    turn_id: str = "",
    turn_exit_reason: str = "",
    **_: Any,
) -> None:
    """Hermes finalized the turn (H: agent/turn_finalizer.py, after post_llm_call;
    forks never fire it): AGOS keeps how it ended, Hermes's turn_exit_reason. A
    turn that sent no answer closes here. CLI/TUI exit shapes carry no turn."""
    if not turn_id:
        return
    key = (str(session_id), str(turn_id))
    with bridge_core._lock:
        agos_turn = _closed.pop(key, None)
    if agos_turn is None:
        agos_turn = _end(*key)  # no answer came (post_llm_call didn't fire)
        with bridge_core._lock:
            _closed.pop(key, None)
    if agos_turn is not None:
        _tell_surely("turn-end", {"turnId": agos_turn, "reason": str(turn_exit_reason or "")[:500]})


def post_llm_call(
    session_id: str = "",
    turn_id: str = "",
    assistant_response: Any = "",
    platform: str = "",
    **_: Any,
) -> None:
    """The answer is done (Hermes fires this before it sends it): the AGOS chat
    shows it. Hermes's text is never changed."""
    if bridge_text._ours(platform):
        _finish(session_id, turn_id, bridge_text._text_of(assistant_response))


def agent_loop_stopped(
    session_key: str = "",
    platform: str = "",
    reason: str = "",
    invalidation_reason: str = "",
    **_: Any,
) -> None:
    """Hermes interrupted the conversation's running answer (its /stop, or /new while
    it works; H: gateway/run_agent_cache.py `_interrupt_and_clear_session`): no
    post_llm_call comes for it, so its AGOS turn closes now with Hermes's reason.
    Called on the gateway's loop: AGOS is told off it."""
    if not bridge_text._ours(platform) or not session_key:
        return
    with bridge_core._lock:
        stopped = [k for k, key in bridge_core._turn_keys.items() if key == str(session_key)]
    if not stopped:
        # The key AGOS noted at the turn's start may differ (or be missing): the answer
        # running in this chat is the one Hermes stopped.
        chat = bridge_approvals._chat_of(str(session_key))
        with bridge_core._lock:
            stopped = [
                k
                for k, here in bridge_core._busy.items()
                if chat and here == chat and k in bridge_core._turns
            ]
    if stopped:
        why = str(reason or invalidation_reason or "")[:500]
        threading.Thread(target=_stopped, args=(stopped, why), daemon=True).start()
    else:
        log.warning("agent_loop_stopped for %s: no AGOS turn open there", session_key)


def _stopped(turns: list[tuple[str, str]], why: str) -> None:
    for session_id, turn_id in turns:
        agos_turn = _end(session_id, turn_id)
        if agos_turn is not None:
            _tell_surely("turn-stop", {"turnId": agos_turn, "reason": why})


# The owner's rules for every workspace (AGOS's actions/owner_rules.py): two
# system-prompt sections (Hermes caps one at 4,000 characters, all at 8,000),
# rendered once per new session (cron and Kanban runs too), in id order.
OWNER_RULES_SECTION = "agos.owner-rules"
OWNER_RULES_SECTIONS = (OWNER_RULES_SECTION, OWNER_RULES_SECTION + ".2")
_owner_rules: dict[str, Any] = {}


def owner_rules_section(_info: Any = None) -> str:
    """His rules' first part, asked from AGOS when a session starts (the answer's
    other parts are kept for the next sections). AGOS unreachable: the last answer
    this process had (else none this session; Hermes skips an empty one)."""
    answer = bridge_core.post("owner-rules", {}, 5)
    if answer is not None:
        parts = answer.get("parts")
        if not isinstance(parts, list):
            parts = [str(answer.get("text") or "")]
        _owner_rules["parts"] = [str(p) for p in parts]
    return str(owner_rules_part(0)())


def owner_rules_part(n: int) -> Any:
    """Section n's text: part n of the answer the first section just fetched."""

    def content(_info: Any = None) -> str:
        parts = _owner_rules.get("parts") or []
        return str(parts[n]) if n < len(parts) else ""

    return content
