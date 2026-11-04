"""engine/read_cache.py, engine/read_ahead.py, engine/loop_guard.py: Hermes's
answers kept while their stamp holds, asked once at a time, read ahead after
start, and never asked on the event loop."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from agos_core.engine import loop_guard, read_ahead, read_cache


def test_same_stamp_asks_hermes_once() -> None:
    cache: read_cache.ReadCache[int] = read_cache.ReadCache("t")
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    assert cache.get("k", ("a",), compute) == 1
    assert cache.get("k", ("a",), compute) == 1
    assert cache.get("k", ("b",), compute) == 2  # changed stamp: asked again
    assert cache.get("other", ("b",), compute) == 3  # keys are apart
    assert len(calls) == 3


def test_callers_together_share_one_ask() -> None:
    cache: read_cache.ReadCache[str] = read_cache.ReadCache("t")
    release = threading.Event()
    started = threading.Event()
    calls: list[int] = []

    def compute() -> str:
        calls.append(1)
        started.set()
        release.wait(5)
        return "answer"

    got: list[str] = []
    threads = [
        threading.Thread(target=lambda: got.append(cache.get("k", 1, compute))) for _ in range(5)
    ]
    for t in threads:
        t.start()
        started.wait(5)
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(5)
    assert got == ["answer"] * 5
    assert len(calls) == 1


def test_stale_ok_answers_at_once_and_asks_again_behind() -> None:
    cache: read_cache.ReadCache[int] = read_cache.ReadCache("t")
    assert cache.get("k", 1, lambda: 10, stale_ok=True) == 10  # nothing yet: waits
    slow = threading.Event()

    def newer() -> int:
        slow.wait(5)
        return 20

    started = time.monotonic()
    assert cache.get("k", 2, newer, stale_ok=True) == 10  # the last answer, at once
    assert time.monotonic() - started < 1
    slow.set()
    assert read_cache.ReadCache.settle(5)
    assert cache.get("k", 2, lambda: 99) == 20  # the background ask landed


def test_a_failed_ask_is_not_repeated_at_once() -> None:
    cache: read_cache.ReadCache[int] = read_cache.ReadCache("t", retry_after=60)
    calls: list[int] = []

    def broken() -> int:
        calls.append(1)
        raise OSError("hermes down")

    with pytest.raises(OSError):
        cache.get("k", 1, broken)
    with pytest.raises(OSError):
        cache.get("k", 1, broken)  # same stamp within retry_after: not asked
    assert len(calls) == 1
    assert cache.get("k", 2, lambda: 5) == 5  # the files changed: asked again
    cache.drop("k")
    assert cache.get("k", 2, lambda: 6) == 6  # dropped: asked again


def test_joiners_get_the_error_too() -> None:
    cache: read_cache.ReadCache[int] = read_cache.ReadCache("t")
    go = threading.Event()

    def broken() -> int:
        go.wait(5)
        raise ValueError("bad answer")

    errors: list[str] = []

    def ask() -> None:
        try:
            cache.get("k", 1, broken)
        except ValueError as error:
            errors.append(str(error))

    threads = [threading.Thread(target=ask) for _ in range(3)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    go.set()
    for t in threads:
        t.join(5)
    assert errors == ["bad answer"] * 3


def test_refresh_fills_in_the_background() -> None:
    cache: read_cache.ReadCache[str] = read_cache.ReadCache("t")
    cache.refresh("k", 1, lambda: "warm")
    assert read_cache.ReadCache.settle(5)
    assert cache.peek("k") == "warm"
    cache.refresh("k", 1, lambda: "never")  # same stamp: nothing to do
    assert read_cache.ReadCache.settle(5)
    assert cache.get("k", 1, lambda: "never") == "warm"


def test_stamps(tmp_path: Path) -> None:
    f = tmp_path / "config.yaml"
    missing = read_cache.file_stamp(f)
    f.write_text("a: 1\n")
    first = read_cache.file_stamp(f)
    assert first != missing
    content = read_cache.content_stamp(f)
    time.sleep(0.01)
    f.write_text("a: 1\n")  # same text written again
    assert read_cache.content_stamp(f) == content
    f.write_text("a: 2\n")
    assert read_cache.content_stamp(f) != content
    db = tmp_path / "kanban.db"
    db.write_bytes(b"x")
    before = read_cache.sqlite_stamp(db)
    (tmp_path / "kanban.db-wal").write_bytes(b"w")
    assert read_cache.sqlite_stamp(db) != before


def test_read_ahead_goes_on_after_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    import types

    mod = types.ModuleType("agos_fake_warm")

    def broken(core: object) -> None:
        raise RuntimeError("no Hermes")

    def fine(core: object) -> None:
        seen.append("fine")

    mod.broken = broken  # type: ignore[attr-defined]
    mod.fine = fine  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "agos_fake_warm", mod)
    took = read_ahead.run(object(), ("agos_fake_warm:broken", "agos_fake_warm:fine"))
    assert seen == ["fine"]
    assert set(took) == {"agos_fake_warm:broken", "agos_fake_warm:fine"}


def test_hermes_never_starts_on_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGOS_STRICT_LOOP", "1")
    loop_guard.off_loop("in a thread")  # no loop here: fine

    async def route() -> None:
        loop_guard.off_loop("hermes kanban show")

    with pytest.raises(RuntimeError, match="event loop"):
        asyncio.run(route())

    async def threaded() -> None:
        await asyncio.to_thread(loop_guard.off_loop, "hermes kanban show")

    asyncio.run(threaded())  # a thread off the loop: fine
    monkeypatch.setenv("AGOS_STRICT_LOOP", "0")
    asyncio.run(route())  # live: only logged
    # Strict mode keeps what broke the rule (also when a caller swallowed it).
    assert loop_guard.broken == ["hermes kanban show"]
    loop_guard.broken.clear()


def test_background_asks_and_read_ahead_yield_the_cpu() -> None:
    """What runs behind the pages (and every Hermes process it starts) has a lower
    CPU priority than the pages themselves."""
    import os
    import sys
    import types

    seen: list[int] = []

    def nice_here() -> None:
        seen.append(os.getpriority(os.PRIO_PROCESS, threading.get_native_id()))

    read_cache.submit(nice_here)
    assert read_cache.ReadCache.settle(5)
    mod = types.ModuleType("agos_fake_nice")
    mod.warm = lambda core: nice_here()  # type: ignore[attr-defined]
    sys.modules["agos_fake_nice"] = mod
    try:
        read_ahead.run(object(), ("agos_fake_nice:warm",))
    finally:
        del sys.modules["agos_fake_nice"]
    assert len(seen) == 2
    assert all(n >= read_cache.BACKGROUND_NICE for n in seen)
