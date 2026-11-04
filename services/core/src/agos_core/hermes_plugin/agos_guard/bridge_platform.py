"""AGOS's own conversations as a Hermes platform ("agos"): the adapter that takes
AGOS's inbox items as platform messages, joins group rooms, and sends what Hermes
says back to the AGOS chat.

Owns: the agos platform adapter and its registration.
Must not: touch the Telegram bot's loops (bridge_delivery).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import importlib
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = [
    "AGOS_OWNER_ID",
    "HANDED_KEPT",
    "PLATFORM_GROUPS",
    "PLATFORM_LOOK_S",
    "HandedIds",
    "take_once",
]

try:
    from . import bridge_core, bridge_delivery, bridge_runner, bridge_sessions
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_delivery = sys.modules["agos_guard_bridge_delivery"]
    bridge_runner = sys.modules["agos_guard_bridge_runner"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]


log = logging.getLogger("agos.bridge")


# Each AGOS chat of the workspace is a Hermes gateway conversation, like a Telegram
# chat: Hermes runs it (commands, steer / queue while busy, approvals, voice notes it
# transcribes itself). AGOS is the window: messages come from AGOS's inbox, what
# Hermes says goes back into the AGOS chat.


def _agos_arrived(event: Any, gateway: Any, source: Any) -> None:
    """His message from AGOS reached the gateway: remember the conversation's key and
    keep the chat's own Hermes session (its history) on first use."""
    keyer = bridge_core._missing(
        "gateway.run.GatewayRunner._session_key_for_source",
        getattr(gateway, "_session_key_for_source", None),
    )
    if not callable(keyer):
        return
    with bridge_core._guard("gateway.run.GatewayRunner._session_key_for_source"):
        key = str(keyer(source))
        address = bridge_core.AGOS_ADDRESS + str(source.chat_id)
        bridge_sessions._remember_key(address, key)
        wanted = str((getattr(event, "metadata", None) or {}).get("agos_session") or "")
        store = getattr(gateway, "session_store", None)
        if not wanted or store is None or store.lookup_by_session_key(key) is not None:
            return
        entry = store.get_or_create_session(source)
        if entry is not None and entry.session_id != wanted:
            store.switch_session(key, wanted)


def _platform_on() -> bool:

    with bridge_core._guard("gateway.platforms._shared.get_scoped_secret"):
        from gateway.platforms._shared import get_scoped_secret  # type: ignore[import-not-found]

        return bool(str(get_scoped_secret("AGOS_PLATFORM_ENABLED", "")).strip().lower() == "true")
    return os.environ.get("AGOS_PLATFORM_ENABLED", "").strip().lower() == "true"


# A root's gateway serves several Hermes profiles (the Co-Founder's and its members':
# Hermes's served_profiles), each with its own copy of this plugin and its own agos
# adapter. One copy (the first to ask) asks AGOS for every profile whose copy joined;
# AGOS answers each item with its member, and the item goes to that profile's
# adapter (its own task, in its own profile scope). A copy that joined after the ask
# went asks on its own until the next one carries it; when the asking copy goes,
# another asks. An older core answers without `members` (only the asking copy's
# own): then every copy asks on its own again, as before, until AGOS can't be
# reached once (a core restart: asked again which kind it is).
PLATFORM_GROUPS = "platform_asks_v1"
PLATFORM_LOOK_S = 5.0  # a copy waiting for its items looks again whether someone asks


def _platform_group(b: dict[str, str]) -> dict[str, Any]:
    groups: dict[tuple[str, str], dict[str, Any]] = bridge_core._shared.setdefault(
        PLATFORM_GROUPS, {}
    )
    return groups.setdefault(
        (b["core"], b["workspace"]),
        {"queues": {}, "asker": None, "covered": set(), "shared": None},
    )


def _platform_join(b: dict[str, str] | None, queue: asyncio.Queue[dict[str, Any]]) -> None:
    if b is not None:
        loop = asyncio.get_running_loop()
        _platform_group(b)["queues"][str(b.get("member") or "")] = (loop, queue)


def _platform_leave(b: dict[str, str] | None, queue: asyncio.Queue[dict[str, Any]]) -> None:
    if b is None:
        return
    group, me = _platform_group(b), str(b.get("member") or "")
    if (group["queues"].get(me) or (None, None))[1] is queue:
        group["queues"].pop(me, None)
        if group["asker"] == me:
            group["asker"], group["covered"] = None, set()


async def _platform_alone(group: dict[str, Any]) -> list[dict[str, Any]] | None:
    answer = await asyncio.to_thread(bridge_core.post, "platform-next", {}, 40)
    if answer is None:
        group["shared"] = None  # AGOS went (a restart?): which kind it is, asked again
        return None
    return [i for i in answer.get("items") or [] if isinstance(i, dict)]


async def _platform_items(
    b: dict[str, str] | None, queue: asyncio.Queue[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """The next items of this copy's profile from AGOS's inbox (its AGOS
    conversations). None: AGOS can't be reached (or no bridge): wait a little."""
    if b is None:
        return None
    _platform_join(b, queue)
    group, me = _platform_group(b), str(b.get("member") or "")
    if group["shared"] is False:
        return await _platform_alone(group)
    if group["asker"] in (None, me):
        group["asker"] = me
        members = sorted(group["queues"])
        group["covered"] = set(members)
        answer = await asyncio.to_thread(
            bridge_core.post, "platform-next", {"members": members}, 40
        )
        if answer is None:
            group["shared"] = None
            return None
        items = [i for i in answer.get("items") or [] if isinstance(i, dict)]
        if "members" not in answer:
            # An older core: it took only this copy's own; every copy asks alone.
            group["shared"], group["covered"] = False, set()
            return items
        group["shared"] = True
        mine = []
        for item in items:
            owner = str(item.get("member") or "")
            if owner == me:
                mine.append(item)
                continue
            target = group["queues"].get(owner)
            if target is not None:  # else its copy went: not confirmed, AGOS hands it again
                target[0].call_soon_threadsafe(target[1].put_nowait, item)
        return mine
    if me not in group["covered"]:
        return await _platform_alone(group)  # the ask under way doesn't carry this one
    try:
        first = await asyncio.wait_for(queue.get(), PLATFORM_LOOK_S)
    except TimeoutError:
        return []
    out = [first]
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


HANDED_KEPT = 2000  # inbox ids remembered as already in Hermes (HandedIds)


class HandedIds:
    """The AGOS inbox ids Hermes already has (the newest HANDED_KEPT). AGOS hands an
    item again when its "done" never arrived (the core restarted while Hermes took
    it): Hermes has it, so it is only confirmed again, never given twice."""

    def __init__(self) -> None:
        self._ids: collections.OrderedDict[int, None] = collections.OrderedDict()

    def __contains__(self, item_id: object) -> bool:
        return item_id in self._ids

    def add(self, item_id: int) -> None:
        self._ids[item_id] = None
        while len(self._ids) > HANDED_KEPT:
            self._ids.popitem(last=False)

    def settle(self, ids: list[int], ok: bool) -> None:
        """A batch Hermes refused (not ok) is not in Hermes: handed again, it goes in."""
        for item_id in [] if ok else ids:
            self._ids.pop(item_id, None)


async def take_once(
    take: Callable[[dict[str, Any]], Awaitable[bool | None]],
    handed: HandedIds,
    item: dict[str, Any],
) -> bool | None:
    """`take` (the adapter's: True = in Hermes, None = in its text batch) for an item
    Hermes doesn't have yet; True (confirm it again) for one it has."""
    item_id = int(item["id"])
    if item_id in handed:
        return True
    taken = await take(item)
    handed.add(item_id)
    return taken


def _answer_approval(address: str, item: dict[str, Any]) -> bool:
    """His Allow once / Deny from AGOS, for the approval Hermes asked in that chat."""
    approval = importlib.import_module("tools.approval")
    choice = "once" if item.get("text") == "once" else "deny"
    key = bridge_sessions._key_for(address)
    if approval.resolve_gateway_approval(key, choice):
        bridge_delivery._close_card(key, bridge_core.ANSWERED_IN_AGOS[choice])
    return True


def _agos_adapter(config: Any) -> Any:
    """The platform adapter (Hermes's own base class; built only inside the gateway)."""
    from gateway.config import Platform  # type: ignore[import-not-found]
    from gateway.platforms.base import (  # type: ignore[import-not-found, unused-ignore]
        BasePlatformAdapter,
        SendResult,
    )
    from gateway.platforms.event import MessageEvent, MessageType  # type: ignore[import-not-found]

    kinds = {"audio": MessageType.VOICE, "image": MessageType.PHOTO}

    class AgosAdapter(BasePlatformAdapter):  # type: ignore[misc]
        """Messages one after another are one turn (Hermes's own inbound text
        batching); a message while the agent works is Hermes's busy_input_mode. An
        item is confirmed to AGOS only once Hermes has it (after the batch went in),
        so one a stopped gateway never took comes again."""

        MAX_MESSAGE_LENGTH = 200_000

        def __init__(self, cfg: Any) -> None:
            super().__init__(config=cfg, platform=Platform(bridge_core.AGOS_PLATFORM))
            self._task: asyncio.Task[None] | None = None
            self._batched: dict[str, list[int]] = {}  # batch key → AGOS inbox ids
            self._handed = HandedIds()
            self._configure_text_batch_delays()

        async def connect(self, *, is_reconnect: bool = False) -> bool:
            if bridge_core.bridge() is None:
                return False
            self._task = asyncio.create_task(self._take_forever())
            self._mark_connected()
            self._wire_plugin_handlers(None)
            return True

        async def disconnect(self) -> None:
            self._running = False
            self._mark_disconnected()
            if self._task is not None:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._task
                self._task = None

        async def _take_forever(self) -> None:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            try:
                while self._running:
                    try:
                        items = await _platform_items(bridge_core.bridge(), queue)
                        if items is None:
                            await asyncio.sleep(5)
                            continue
                        for item in items:
                            ok = await take_once(self._take, self._handed, item)
                            if ok is not None:
                                await self._done([int(item["id"])], ok)
                    except asyncio.CancelledError:
                        return
                    except Exception:  # keep taking messages in
                        log.exception("AGOS platform: inbox round failed")
                        await asyncio.sleep(5)
            finally:
                _platform_leave(bridge_core.bridge(), queue)

        @staticmethod
        async def _done(ids: list[int], ok: bool) -> None:
            for item_id in ids:
                await asyncio.to_thread(bridge_core.post, "done", {"id": item_id, "ok": ok}, 15)

        async def _take(self, item: dict[str, Any]) -> bool | None:
            """None: in Hermes's text batch, confirmed when the batch goes in."""
            address = str(item.get("chat") or "")
            if not address.startswith(bridge_core.AGOS_ADDRESS):
                return True
            chat = address[len(bridge_core.AGOS_ADDRESS) :]
            if item.get("kind") == "approval":
                return _answer_approval(address, item)
            media = [m for m in item.get("media") or [] if isinstance(m, dict) and m.get("path")]
            kind = MessageType.COMMAND if item.get("kind") == "command" else MessageType.TEXT
            if media and kind == MessageType.TEXT:
                kind = kinds.get(str(media[0].get("kind")), MessageType.DOCUMENT)
            event = MessageEvent(
                text=str(item.get("text") or ""),
                message_type=kind,
                source=self.build_source(
                    chat_id=chat,
                    chat_name="AGOS",
                    chat_type="dm",
                    user_id=AGOS_OWNER_ID,
                    # The AGOS chat's name: Hermes shows it as the conversation's topic.
                    chat_topic=str(item.get("topic") or "") or None,
                ),
                message_id=f"agos-{item['id']}",
                media_urls=[str(m["path"]) for m in media],
                media_types=[str(m.get("mime") or "") for m in media],
                metadata={"agos_session": str(item.get("session") or "")},
                # What only this conversation is told (the learning conversation): Hermes's
                # per-channel prompt.
                channel_prompt=str(item.get("channelPrompt") or "") or None,
                # When he sent it: Hermes's message timestamp (gateway.message_timestamps).
                timestamp=bridge_runner.sent_at(item),
            )
            # No file text in his words: Hermes's note says "read the saved file".
            event.media_text_inlined = [False] * len(media)
            reply = str(item.get("replyTo") or "")
            if reply:
                # His reply in AGOS: Hermes's own reply context ("[Replying to: …]").
                event.reply_to_message_id = f"agos-reply-{item['id']}"
                event.reply_to_text = reply
                event.reply_to_is_own_message = bool(item.get("replyOwn"))
            key = self._text_batch_key(event)
            if kind == MessageType.TEXT and not media and not reply:
                self._batched.setdefault(key, []).append(int(item["id"]))
                self._enqueue_text_event(event)
                return None
            await self._flush_text_batch_now(key)  # what he wrote before goes first
            await self.handle_message(event)
            return True

        def _pop_text_batch(self, key: str) -> Any:
            event = super()._pop_text_batch(key)
            if event is not None:
                event._agos_ids = self._batched.pop(key, [])
            return event

        async def _dispatch_text_batch(self, event: Any) -> None:
            ok = True
            try:
                await self.handle_message(event)
            except Exception:  # AGOS hands it again
                log.exception("AGOS platform: a message didn't go in")
                ok = False
            ids = list(getattr(event, "_agos_ids", []) or [])
            self._handed.settle(ids, ok)
            await self._done(ids, ok)

        async def send(
            self,
            chat_id: str,
            content: str,
            reply_to: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> Any:
            said = await asyncio.to_thread(
                bridge_core.post,
                "platform-send",
                {"chat": bridge_core.AGOS_ADDRESS + str(chat_id), "text": content},
                30,
            )
            if said is None:
                return SendResult(success=False, error="AGOS can't be reached")
            return SendResult(success=True, message_id=f"agos-{chat_id}")

        async def send_clarify(
            self,
            chat_id: str,
            question: str,
            choices: list[Any] | None,
            clarify_id: str,
            session_key: str,
            metadata: dict[str, Any] | None = None,
        ) -> Any:
            """Hermes's clarify: AGOS shows the question where the work is (a task's
            card, a chat); his next message in this conversation is the answer."""
            with bridge_core._guard("tools.clarify_gateway.mark_awaiting_text"):
                importlib.import_module("tools.clarify_gateway").mark_awaiting_text(clarify_id)
            body = {
                "chat": bridge_core.AGOS_ADDRESS + str(chat_id),
                "question": str(question or ""),
                "choices": [str(c) for c in choices or []],
            }
            said = await asyncio.to_thread(bridge_core.post, "clarify", body, 30)
            if said is None:
                return SendResult(success=False, error="AGOS can't be reached")
            return SendResult(success=True, message_id=f"agos-{chat_id}")

        async def edit_message(self, chat_id: str, message_id: str, content: str, **_: Any) -> Any:
            return SendResult(success=True, message_id=message_id)

        async def send_typing(self, chat_id: str, metadata: Any = None) -> None:
            return None  # AGOS shows "Working…" itself

        async def _send_exec_approval_prompt(self, prompt: Any) -> Any:
            # AGOS shows the card in its chat (pre_approval_request hook); on the
            # phone it is Hermes's own Telegram card, where AGOS said.
            await _phone_card(prompt)
            return SendResult(success=True, message_id="agos-approval")

        async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
            return {"name": f"AGOS chat {chat_id}", "type": "dm", "chat_id": chat_id}

    return AgosAdapter(config)


AGOS_OWNER_ID = "owner"


async def _phone_card(prompt: Any) -> None:
    """Hermes's own Telegram Allow / Deny card for an approval asked in an AGOS
    conversation, in the chat's Telegram place: the workspace's bot (this root's
    gateway) sends it and resolves it with this conversation's session key."""
    with bridge_core._lock:
        where = bridge_core._phone.pop(str(getattr(prompt, "session_key", "") or ""), None)
    telegram = bridge_core._process()["telegram"]
    if where is None or telegram is None:
        return
    choices = [str(a[1]) for a in getattr(prompt, "actions", None) or []]
    try:
        await telegram.send_exec_approval(
            chat_id=where["chat"],
            command=str(getattr(prompt, "command", "") or ""),
            session_key=str(prompt.session_key),
            description=getattr(prompt, "description", None),
            metadata={"thread_id": where["thread"]} if where["thread"] else None,
            allow_permanent="always" in choices,
            allow_session="session" in choices,
            smart_denied=bool(getattr(prompt, "smart_denied", False)),
        )
    except Exception as error:  # noqa: BLE001 — the card in AGOS still answers it
        log.warning("AGOS bridge: no Telegram card for the approval: %s", error)
        bridge_core._broken(
            "plugins.platforms.telegram.adapter.TelegramAdapter.send_exec_approval", error
        )


def _platform_seed() -> dict[str, Any] | None:
    """The platform's config from the profile's env: on, and its home chat (the
    Co-Founder chat, where Hermes delivers its own notices)."""

    if not _platform_on():
        return None
    # Messages he sends one after another within this many seconds are one turn
    # (Hermes's own inbound text batching, at its ceiling).
    seed: dict[str, Any] = {"window": "agos", "text_batch_delay_seconds": 2.0}
    home = os.environ.get("AGOS_PLATFORM_HOME_CHANNEL", "").strip()
    with bridge_core._guard("gateway.platforms._shared.get_scoped_secret"):
        from gateway.platforms._shared import get_scoped_secret

        home = str(get_scoped_secret("AGOS_PLATFORM_HOME_CHANNEL", "") or home).strip()
    if home.isdigit():
        seed["home_channel"] = {"chat_id": home, "name": "Co-Founder"}
    return seed


def _register_platform(ctx: Any) -> None:
    register_platform = bridge_core._missing(
        "hermes_cli.plugins.PluginContext.register_platform",
        getattr(ctx, "register_platform", None),
    )
    if register_platform is None:
        return
    with bridge_core._guard("hermes_cli.plugins.PluginContext.register_platform"):
        register_platform(
            name=bridge_core.AGOS_PLATFORM,
            label="AGOS",
            adapter_factory=_agos_adapter,
            check_fn=lambda: True,
            is_connected=lambda _config: _platform_on(),
            env_enablement_fn=_platform_seed,
            allowed_users_env="AGOS_PLATFORM_ALLOWED_USERS",
            cron_deliver_env_var="AGOS_PLATFORM_HOME_CHANNEL",
            emoji="🖥",
            # Hermes's quietest display defaults (no progress, no busy notes): AGOS
            # shows "Working…" itself (H: gateway/display_config.py _TIER_MINIMAL).
            display_tier="minimal",
            platform_hint=(
                "You are talking with the owner in AGOS, his own app for this workspace. "
                "Markdown renders there."
            ),
        )
