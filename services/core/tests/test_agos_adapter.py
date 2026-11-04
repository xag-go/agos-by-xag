"""The agos platform adapter inside Hermes (agos-guard plugin), against stand-ins
for Hermes's own base classes: a queued message keeps the time the owner sent it
(Hermes's MessageEvent.timestamp)."""

from __future__ import annotations

import asyncio
import enum
import sys
import types
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.hermes_plugin.agos_guard import bridge, bridge_platform


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> Any:
    class MessageType(enum.Enum):
        TEXT = "text"
        COMMAND = "command"
        VOICE = "voice"
        PHOTO = "photo"
        DOCUMENT = "document"

    @dataclass
    class MessageEvent:
        text: str
        message_type: Any
        source: Any
        message_id: str | None = None
        media_urls: list[str] = field(default_factory=list)
        media_types: list[str] = field(default_factory=list)
        metadata: dict[str, Any] = field(default_factory=dict)
        channel_prompt: str | None = None
        timestamp: datetime = field(default_factory=datetime.now)

    class Base:
        def __init__(self, config: Any, platform: Any) -> None:
            self.handled: list[Any] = []

        def _configure_text_batch_delays(self) -> None: ...

        def build_source(self, **kw: Any) -> Any:
            return SimpleNamespace(**kw)

        def _text_batch_key(self, event: Any) -> str:
            return str(event.source.chat_id)

        def _enqueue_text_event(self, event: Any) -> None:
            self.handled.append(event)

        async def _flush_text_batch_now(self, key: str) -> None: ...

        async def handle_message(self, event: Any) -> None:
            self.handled.append(event)

    config = types.ModuleType("gateway.config")
    config.Platform = lambda name: name  # type: ignore[attr-defined]
    base = types.ModuleType("gateway.platforms.base")
    base.BasePlatformAdapter = Base  # type: ignore[attr-defined]
    base.SendResult = SimpleNamespace  # type: ignore[attr-defined]
    event = types.ModuleType("gateway.platforms.event")
    event.MessageEvent = MessageEvent  # type: ignore[attr-defined]
    event.MessageType = MessageType  # type: ignore[attr-defined]
    for name, module in (
        ("gateway", types.ModuleType("gateway")),
        ("gateway.config", config),
        ("gateway.platforms", types.ModuleType("gateway.platforms")),
        ("gateway.platforms.base", base),
        ("gateway.platforms.event", event),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return bridge._agos_adapter(SimpleNamespace())


def test_a_queued_message_keeps_the_time_he_sent_it(adapter: Any) -> None:
    item = {
        "id": 4,
        "chat": "agos:5",
        "text": "sent while the gateway was down",
        "kind": "message",
        "createdAt": "2026-10-16T08:15:30.250Z",
    }
    asyncio.run(adapter._take(item))
    [event] = adapter.handled
    assert event.timestamp == datetime(2026, 10, 16, 8, 15, 30, 250000, tzinfo=UTC)
    # No time from AGOS: Hermes's own default (now).
    assert isinstance(bridge.sent_at({}), datetime)


def test_his_file_is_never_said_to_be_inlined(adapter: Any) -> None:
    """AGOS puts no file text in his words, so Hermes's own document note must say
    "read the saved file" (media_text_inlined False), never "content included below"."""
    import inspect

    item = {
        "id": 5,
        "chat": "agos:5",
        "text": "read the note",
        "kind": "message",
        "media": [{"kind": "file", "path": "/files/n.txt", "mime": "text/plain"}],
    }
    asyncio.run(adapter._take(item))
    [event] = adapter.handled
    assert event.media_urls == ["/files/n.txt"]
    assert event.media_text_inlined == [False]
    # The Telegram-linked path too.
    assert "media_text_inlined = [False]" in inspect.getsource(bridge._run_event)


def test_an_item_handed_again_after_its_lost_confirmation_goes_in_once(adapter: Any) -> None:
    """AGOS hands an item again when its "done" never arrived (the core restarted
    while Hermes took it: tests/failure/test_recovery.py). Hermes already has it, so
    the plugin confirms it again instead of giving Hermes the message a second time
    (seen on the real rig: his message and its answer twice)."""

    def take(item: dict[str, Any]) -> Any:
        return asyncio.run(bridge_platform.take_once(adapter._take, adapter._handed, item))

    item = {"id": 7, "chat": "agos:5", "text": "slow answer please", "kind": "message"}
    assert take(item) is None  # in Hermes's text batch
    assert take(dict(item)) is True  # handed again: confirmed only
    assert [e.text for e in adapter.handled] == ["slow answer please"]
    command = {"id": 8, "chat": "agos:5", "text": "/title Plans", "kind": "command"}
    assert take(command) is True
    assert take(dict(command)) is True
    assert [e.text for e in adapter.handled] == ["slow answer please", "/title Plans"]


def test_an_item_whose_batch_failed_goes_in_again(adapter: Any) -> None:
    """A batch Hermes refused is confirmed not ok: AGOS hands it again and this
    time it goes in (only what Hermes really has is skipped)."""
    item = {"id": 9, "chat": "agos:5", "text": "try again", "kind": "message"}
    asyncio.run(bridge_platform.take_once(adapter._take, adapter._handed, item))
    done: list[tuple[list[int], bool]] = []

    async def record(ids: list[int], ok: bool) -> None:
        done.append((ids, ok))

    async def refuse(event: Any) -> None:
        raise RuntimeError("Hermes refused")

    adapter._done = record
    adapter.handle_message = refuse
    asyncio.run(adapter._dispatch_text_batch(SimpleNamespace(_agos_ids=[9])))
    assert done == [([9], False)]
    again = asyncio.run(bridge_platform.take_once(adapter._take, adapter._handed, dict(item)))
    assert again is None  # into the batch again
    assert [e.text for e in adapter.handled] == ["try again", "try again"]


def test_the_ids_kept_are_bounded() -> None:
    handed = bridge_platform.HandedIds()
    for i in range(bridge_platform.HANDED_KEPT + 5):
        handed.add(i)
    assert 0 not in handed and 4 not in handed and 5 in handed
    handed.settle([5], ok=True)
    assert 5 in handed
    handed.settle([5], ok=False)
    assert 5 not in handed
