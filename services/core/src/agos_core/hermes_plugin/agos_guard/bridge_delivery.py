"""The bridge's two loops with AGOS: the poller that takes AGOS's items and runs them
on Hermes, and the sender that puts AGOS's outbox on Telegram (once per row), with
the 👀 / 👍 / 👎 AGOS's own answers leave and the Allow/Deny card closed from AGOS.

Owns: what moves between AGOS's queues and the Telegram bot.
Must not: report turns (bridge_hooks) or stream them (bridge_stream).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import threading
from typing import Any

__all__ = [
    "BOT_WAIT_S",
    "FINAL_REACTIONS",
    "UNSURE",
]

try:
    from . import bridge_core, bridge_runner, bridge_sessions
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_runner = sys.modules["agos_guard_bridge_runner"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]


log = logging.getLogger("agos.bridge")


def _poll_forever() -> None:
    """Takes what he wrote in AGOS into the Telegram conversation, as if sent there."""
    import time

    while True:
        try:
            _poll_once()
        except Exception:  # keep taking messages in
            log.exception("AGOS bridge: inbox round failed")
            time.sleep(5)


def _serving() -> bool:
    """This process is the gateway that serves (Hermes's own gateway_state.json,
    H: gateway/status.py read_runtime_status): a gateway that is draining or stopping
    for a restart takes no more AGOS work; the gateway after it does."""

    with bridge_core._guard("gateway.status.read_runtime_status"):
        import importlib

        state = importlib.import_module("gateway.status").read_runtime_status() or {}
        if int(state.get("pid") or 0) == os.getpid() and str(state.get("gateway_state") or "") in (
            "draining",
            "stopping",
            "stopped",
        ):
            return False
    return True


def _poll_once() -> None:
    import time

    b = bridge_core.bridge()
    if b is None or (isinstance(b, dict) and b.get("member")) or not _serving():
        # A team member's own copy (its bridge file names the member) takes nothing
        # here: AGOS hands a member nothing on "next" (no Telegram of its own; its AGOS
        # conversations come by platform-next), so it doesn't ask.
        time.sleep(10)
        return
    answer = bridge_core.post("next", {}, 40)
    if answer is None:
        time.sleep(5)
        return
    for item in answer.get("items") or []:
        ok = False
        key = bridge_sessions._key_for(str(item["chat"]))
        try:
            if item.get("kind") == "approval":
                # His Allow once / Deny from AGOS, for the approval waiting here.
                import importlib

                approval = importlib.import_module("tools.approval")
                choice = "once" if item["text"] == "once" else "deny"
                if approval.resolve_gateway_approval(key, choice):
                    _close_card(key, bridge_core.ANSWERED_IN_AGOS[choice])
                ok = True  # nothing waiting any more: nothing to retry either
            elif item.get("kind") == "bind":
                ok = bridge_runner._bind(
                    bridge_sessions._address(str(item["chat"])), str(item["text"])
                )
            else:
                address = bridge_sessions._address(str(item["chat"]))
                if item.get("kind") == "command":
                    bridge_runner._await_answer(address.split(":", 1)[0], address)
                    ok = bridge_runner._run_command(address, str(item["text"]))
                else:
                    # His words (and files) go in as his message there, tagged
                    # agos-<id> so the AGOS chat doesn't take them twice; Hermes
                    # answers in the profile it routes the place to.
                    ok = bridge_runner._run_message(address, item)
        except Exception as error:  # noqa: BLE001 — retried by AGOS
            log.warning("AGOS bridge: message not taken in: %s", error)
        bridge_core.post("done", {"id": int(item["id"]), "ok": ok}, 15)
        if not ok:
            time.sleep(5)


def _send_forever() -> None:
    """AGOS's cards and status lines go out on this gateway's own bot (Hermes sends
    them; AGOS only says what)."""
    import time

    while True:
        try:
            if not _send_once():
                time.sleep(2)
        except Exception:  # keep sending
            log.exception("AGOS bridge: sending round failed")
            time.sleep(5)


BOT_WAIT_S = 60
# A send whose outcome is unknown (it may have reached Telegram): done, never again.
UNSURE = "unsure"


def _run_on_bot(coro: Any) -> Any:
    loop = bridge_core._ctx.get("loop")
    if loop is None:
        coro.close()
        raise RuntimeError("the gateway's loop isn't known yet")
    return asyncio.run_coroutine_threadsafe(coro, loop).result(BOT_WAIT_S)


def _load_sent() -> None:
    home = bridge_core._home()
    if home is None or bridge_core._sent:
        return
    with contextlib.suppress(OSError, ValueError, AttributeError, TypeError):
        saved = json.loads((home / bridge_core.SENT_FILE).read_text())
        bridge_core._sent.update({int(k): str(v) for k, v in saved.items()})


def _mark_sent(row_id: int, message_id: str) -> None:
    """This row is on Telegram (or may be): kept across restarts, so a row AGOS
    hands out again is only reported, never sent a second time."""
    with bridge_core._lock:
        bridge_core._sent[row_id] = message_id
        while len(bridge_core._sent) > bridge_core.SENT_MAX:
            bridge_core._sent.pop(min(bridge_core._sent))
        body = json.dumps(bridge_core._sent)
    home = bridge_core._home()
    if home is not None:
        with contextlib.suppress(OSError):
            (home / bridge_core.SENT_FILE).write_text(body)


def _send_once() -> bool:
    native = bridge_core._ctx.get("native")
    if native is None or bridge_core.bridge() is None or not _serving():
        return False
    answer = bridge_core.post("outbox", {}, 40)
    if answer is None:
        return False
    _load_sent()
    for item in answer.get("send") or []:
        row_id = int(item["id"])
        with bridge_core._lock:
            already = bridge_core._sent.get(row_id)
        if already is not None:
            message_id, error = already, None  # sent before; only AGOS didn't hear it
        else:
            message_id, error = _send_item(native, item)
            if message_id:
                _mark_sent(row_id, message_id)
        bridge_core.post(
            "outbox-done",
            {
                "id": row_id,
                "kind": "send",
                "messageId": message_id or None,
                "error": error,
            },
            15,
        )
    for item in answer.get("topics") or []:
        # A topic in his Telegram group, made by this gateway's own bot (Hermes's).
        thread, error = "", None
        try:
            topic = _run_on_bot(
                native.bot.create_forum_topic(
                    chat_id=int(str(item["chat"])), name=str(item["name"])[:128]
                )
            )
            thread = str(topic.message_thread_id)
        except Exception as failed:  # noqa: BLE001 — AGOS shows why
            error = str(failed)[:300] or type(failed).__name__
        bridge_core.post(
            "outbox-done",
            {"id": int(item["id"]), "kind": "topic", "messageId": thread or None, "error": error},
            15,
        )
    for item in answer.get("close") or []:
        chat = str(item["address"]).partition(":")[0]
        with contextlib.suppress(Exception):
            _run_on_bot(
                native.bot.edit_message_text(
                    chat_id=int(chat),
                    message_id=int(item["messageId"]),
                    text=str(item["text"]),
                    reply_markup=None,
                )
            )
        bridge_core.post("outbox-done", {"id": int(item["id"]), "kind": "close"}, 15)
    for item in answer.get("reactions") or []:
        error = _react(item)
        bridge_core.post(
            "outbox-done", {"id": int(item["id"]), "kind": "reaction", "error": error}, 15
        )
    return bool(
        answer.get("send") or answer.get("close") or answer.get("topics") or answer.get("reactions")
    )


def _send_item(native: Any, item: dict[str, Any]) -> tuple[str, str | None]:
    """One outbox item on this bot: a reply with Hermes's own Telegram send (its
    formatting and splitting, the topic as its thread), a card as one message with
    its buttons. (message id, error)."""
    chat, _, topic = str(item["address"]).partition(":")
    thread = topic if topic and topic != "0" else None
    text = str(item.get("text") or "") or "(empty)"
    buttons = item.get("buttons") or []
    try:
        if not buttons:
            send = bridge_core._ctx.get("send")  # the adapter's own send (not the AGOS-watched one)
            if send is None:
                return "", "Hermes's Telegram isn't ready yet"
            result = _run_on_bot(send(chat, text, None, {"thread_id": thread} if thread else None))
            if not getattr(result, "success", False):
                return "", str(getattr(result, "error", "") or "not sent")[:300]
            return str(getattr(result, "message_id", "") or "sent"), None
        from telegram import (  # type: ignore[import-not-found, unused-ignore]
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(str(b[0]), callback_data=str(b[1])[:64]) for b in buttons]]
        )
        sent = _run_on_bot(
            native.bot.send_message(
                chat_id=int(chat),
                text=text,
                message_thread_id=int(thread) if thread else None,
                reply_markup=markup,
            )
        )
        return str(sent.message_id), None
    except TimeoutError:
        # It may be on Telegram already (Hermes's own send has its own retries): never
        # sent again, like Hermes's delivery ledger does with an unsure send.
        log.warning("AGOS bridge: outbox item %s took too long; not sent again", item.get("id"))
        return UNSURE, None
    except Exception as failed:  # noqa: BLE001 — AGOS keeps it and tries again
        return "", str(failed)[:300] or type(failed).__name__


def _start_sender() -> None:
    running = bridge_core._ctx.get("sender")
    if (running is not None and running.is_alive()) or not _in_gateway():
        return
    thread = threading.Thread(target=_send_forever, name="agos-bridge-outbox", daemon=True)
    bridge_core._ctx["sender"] = thread
    thread.start()


def _in_gateway() -> bool:
    return "gateway" in sys.argv and "run" in sys.argv


def _start_poller() -> None:
    """Only in the running gateway (never in a `hermes config …` call); the thread
    itself waits while there is no bridge file."""
    running = bridge_core._ctx["poller"]
    if (running is not None and running.is_alive()) or not _in_gateway():
        return
    bridge_sessions.drop_old_keys_file()
    thread = threading.Thread(target=_poll_forever, name="agos-bridge-inbox", daemon=True)
    bridge_core._ctx["poller"] = thread
    thread.start()


def _eyes_stay(chat: Any, message_id: Any, answer: dict[str, Any]) -> None:
    """AGOS answers it itself: Hermes's 👀 stays (its end of this turn says nothing)."""
    if not answer.get("keepEyes"):
        return
    with bridge_core._lock:
        if len(bridge_core._keep_eyes) >= bridge_core.KEEP_EYES_MAX:
            bridge_core._keep_eyes.clear()  # left over from turns that never ended here
        bridge_core._keep_eyes.add((str(chat), str(message_id or "")))


def _watch_reactions(adapter: Any) -> None:
    """Hermes's own reaction at the end of its turn, except on his messages AGOS
    answers itself: those keep Hermes's 👀 until AGOS says the answer is out. Stays
    a wrapper: Hermes always ends a message it was handed with its own reaction,
    even one a plugin consumed (H: gateway/platforms/base.py, the processing task
    runs `on_processing_complete` after the handler returns), and has no setting or
    hook to leave one message's 👀 in place."""
    complete = getattr(adapter, "on_processing_complete", None)
    if complete is None or getattr(complete, "_agos_watch", False):
        return
    bridge_core._ctx["complete"] = complete

    async def watched(event: Any, outcome: Any) -> Any:
        source = getattr(event, "source", None)
        key = (str(getattr(source, "chat_id", "")), str(getattr(event, "message_id", "") or ""))
        with bridge_core._lock:
            if key in bridge_core._keep_eyes:
                bridge_core._keep_eyes.discard(key)
                return None
        return await complete(event, outcome)

    watched._agos_watch = True  # type: ignore[attr-defined]
    adapter.on_processing_complete = watched


FINAL_REACTIONS = {"success": "\U0001f44d", "failure": "\U0001f44e"}  # Hermes's own 👍 / 👎


def _react(item: dict[str, Any]) -> str | None:
    """The end-of-answer reaction on his message once AGOS's answer is out: Hermes's
    own 👍 / 👎 through its platform actions (ctx.platform_actions, the
    `gateway.platform_actions` capability AGOS grants the plugin). A stopped answer
    clears the 👀 the way Hermes does (its own `on_processing_complete`): Hermes's
    platform actions only add a reaction (H: hermes_cli/platform_actions.py)."""
    chat, message = str(item["chat"]), str(item["messageId"])
    with bridge_core._lock:
        bridge_core._keep_eyes.discard((chat, message))
    emoji = FINAL_REACTIONS.get(str(item.get("outcome")))
    ctx = bridge_core._ctx.get("ctx")
    actions = getattr(ctx, "platform_actions", None) if emoji else None
    try:
        if actions is not None:
            done = _run_on_bot(actions.add_reaction("telegram", chat, message, emoji))
            if isinstance(done, dict) and done.get("ok"):
                return None
            return str((done or {}).get("error") or "not set")[:300]
        complete = bridge_core._ctx.get("complete")
        if complete is None:
            return "Hermes's reactions aren't ready yet"
        from types import SimpleNamespace

        from gateway.platforms.base import ProcessingOutcome  # type: ignore[import-not-found]

        outcome = {
            "success": ProcessingOutcome.SUCCESS,
            "failure": ProcessingOutcome.FAILURE,
            "cancelled": ProcessingOutcome.CANCELLED,
        }.get(str(item.get("outcome")), ProcessingOutcome.FAILURE)
        event = SimpleNamespace(source=SimpleNamespace(chat_id=chat), message_id=message)
        _run_on_bot(complete(event, outcome))
    except Exception as failed:  # noqa: BLE001 — AGOS tries again
        return str(failed)[:300] or type(failed).__name__
    return None


def _close_card(session_key: str, text: str) -> None:
    """The card in Telegram shows the answer given in AGOS, without its buttons
    (like Hermes does when it is answered there)."""
    with bridge_core._lock:
        card = bridge_core._cards.pop(session_key, None)
    shared = bridge_core._process()
    adapter, loop = shared["telegram"], shared["loop"]
    if card is None or adapter is None or loop is None:
        return
    with bridge_core._guard("gateway.platforms.base.BasePlatformAdapter.edit_message"):
        asyncio.run_coroutine_threadsafe(
            adapter.edit_message(card[0], card[1], text, finalize=True), loop
        )
