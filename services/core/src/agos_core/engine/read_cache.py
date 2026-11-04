"""Hermes's answers kept in this process's memory while what they come from is
unchanged.

AGOS keeps no copy of Hermes's data. An entry here is the last answer Hermes gave
(its CLI, a script in its runtime, or its own store read only), held in memory
under a stamp of the files that answer comes from. A changed stamp means Hermes is
asked again; nothing is written to disk or to agos.db, and a restart forgets it.

Why: every ask starts Hermes's whole Python (about 1 s when the machine is calm,
tens of seconds when it is busy), so a page that asks on each render is as slow
as Hermes's start, and two pages opened together start it twice.

- `file_stamp`: size, mtime and inode of each file (a missing file counts too).
  Cheap; for files only Hermes writes. A file the reader itself rewrites must be
  stamped on what it holds (`content_stamp`, or a hash of the rows like
  kanban_board._stamp).
- `sqlite_stamp`: a SQLite store with its WAL (Hermes's writes land there first).
- One computation per key at a time: whoever asks while it runs gets the same
  answer.
- `stale_ok=True` answers at once with the last answer and asks Hermes again in
  the background. Only for numbers that move all the time (usage, health), never
  for settings: a page reloaded right after a save must show the save.
- A failed ask is not repeated for `retry_after` seconds with the same stamp (a
  broken Hermes is not started again on every page render).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


def file_stamp(*paths: Path) -> tuple[int, ...]:
    """What the files are now: (size, mtime_ns, inode) each, (-1, 0, 0) if missing."""
    out: list[int] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            out.extend((-1, 0, 0))
            continue
        out.extend((stat.st_size, stat.st_mtime_ns, stat.st_ino))
    return tuple(out)


def sqlite_stamp(db: Path) -> tuple[int, ...]:
    """A SQLite store as it is now: the database file and its write-ahead log."""
    return file_stamp(db, db.with_name(db.name + "-wal"))


def content_stamp(*paths: Path) -> str:
    """What the files hold (a file rewritten with the same text keeps its stamp)."""
    digest = hashlib.sha256()
    for path in paths:
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"\0missing")
        digest.update(b"\0" + str(path).encode() + b"\0")
    return digest.hexdigest()


@dataclass
class _Entry(Generic[T]):
    stamp: Hashable
    value: T
    started: float  # when the computation that gave it began (monotonic)


@dataclass
class _Flight:
    stamp: Hashable
    started: float
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()
_pending: set[object] = set()
_pending_lock = threading.Lock()


BACKGROUND_NICE = 10


def low_priority() -> None:
    """This thread, and every Hermes process it starts, yields the CPU to the
    owner's pages and clicks (Linux keeps a nice value per thread and a child
    process inherits its thread's). Never raised back: a thread that calls this is
    a background thread for good."""
    with contextlib.suppress(OSError, AttributeError):
        me = threading.get_native_id()
        if os.getpriority(os.PRIO_PROCESS, me) < BACKGROUND_NICE:
            os.setpriority(os.PRIO_PROCESS, me, BACKGROUND_NICE)


def _background() -> ThreadPoolExecutor:
    """Two low-priority threads for every background ask: Hermes is never started
    many times at once behind the owner's back (each start holds hundreds of MB),
    and what they start never slows a page."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="agos-read-ahead", initializer=low_priority
            )
        return _pool


def submit(task: Callable[[], object]) -> None:
    """Runs `task` on the background threads (tests wait for it with `ReadCache.settle`)."""
    token = object()
    with _pending_lock:
        _pending.add(token)

    def run() -> None:
        try:
            task()
        except Exception:
            log.warning("background read failed", exc_info=True)
        finally:
            with _pending_lock:
                _pending.discard(token)

    _background().submit(run)


class ReadCache(Generic[T]):
    """Answers by key, each kept while its stamp is unchanged."""

    @staticmethod
    def settle(timeout: float = 30.0) -> bool:
        """Waits until no background ask is queued or running (for tests)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with _pending_lock:
                if not _pending:
                    return True
            time.sleep(0.01)
        return False

    def __init__(self, name: str, *, retry_after: float = 20.0, max_entries: int = 1024) -> None:
        self.name = name
        self._retry_after = retry_after
        self._max_entries = max_entries
        self._entries: dict[Hashable, _Entry[T]] = {}
        self._flights: dict[Hashable, _Flight] = {}
        self._failed: dict[Hashable, tuple[float, Hashable, BaseException]] = {}
        self._lock = threading.Lock()

    def get(
        self,
        key: Hashable,
        stamp: Hashable,
        compute: Callable[[], T],
        *,
        stale_ok: bool = False,
    ) -> T:
        """The answer for `stamp`: kept, joined while it is being computed, or
        computed now. With `stale_ok`, the last answer at once (asked again in the
        background) whenever there is one."""
        asked = time.monotonic()
        while True:
            with self._lock:
                entry = self._entries.get(key)
                # Fresh: same stamp, or computed by an ask that began after this one.
                if entry is not None and (entry.stamp == stamp or entry.started >= asked):
                    return entry.value
                if entry is not None and stale_ok:
                    self._start_background(key, stamp, compute)
                    return entry.value
                failed = self._failed.get(key)
                if (
                    failed is not None
                    and failed[1] == stamp
                    and time.monotonic() - failed[0] < self._retry_after
                ):
                    raise failed[2]
                flight = self._flights.get(key)
                mine = flight is None
                if flight is None:
                    flight = _Flight(stamp=stamp, started=time.monotonic())
                    self._flights[key] = flight
            if mine:
                return self._run(key, flight, compute)
            flight.done.wait()
            if flight.error is not None:
                raise flight.error
            # Loop: the joined ask may have read older files than this one asked for.

    def refresh(self, key: Hashable, stamp: Hashable, compute: Callable[[], T]) -> None:
        """Asks again in the background when the kept answer isn't for `stamp`
        (read-ahead after start or after a write); never waits."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.stamp == stamp:
                return
            self._start_background(key, stamp, compute)

    def peek(self, key: Hashable) -> T | None:
        """The last answer whatever its stamp (None when there is none)."""
        with self._lock:
            entry = self._entries.get(key)
            return entry.value if entry is not None else None

    def drop(self, key: Hashable | None = None) -> None:
        """Forgets one key (or all): the next ask goes to Hermes."""
        with self._lock:
            if key is None:
                self._entries.clear()
                self._failed.clear()
            else:
                self._entries.pop(key, None)
                self._failed.pop(key, None)

    def _start_background(self, key: Hashable, stamp: Hashable, compute: Callable[[], T]) -> None:
        # Called with self._lock held.
        if key in self._flights:
            return
        failed = self._failed.get(key)
        if (
            failed is not None
            and failed[1] == stamp
            and time.monotonic() - failed[0] < self._retry_after
        ):
            return
        flight = _Flight(stamp=stamp, started=time.monotonic())
        self._flights[key] = flight

        def run() -> None:
            try:
                self._run(key, flight, compute)
            except Exception:
                log.warning("%s: %r not read again from Hermes", self.name, key, exc_info=True)

        submit(run)

    def _run(self, key: Hashable, flight: _Flight, compute: Callable[[], T]) -> T:
        try:
            value = compute()
        except BaseException as error:
            with self._lock:
                self._flights.pop(key, None)
                self._failed[key] = (time.monotonic(), flight.stamp, error)
            flight.error = error
            flight.done.set()
            raise
        with self._lock:
            self._entries[key] = _Entry(flight.stamp, value, flight.started)
            self._flights.pop(key, None)
            self._failed.pop(key, None)
            if len(self._entries) > self._max_entries:
                oldest = min(self._entries, key=lambda k: self._entries[k].started)
                self._entries.pop(oldest, None)
        flight.done.set()
        return value
