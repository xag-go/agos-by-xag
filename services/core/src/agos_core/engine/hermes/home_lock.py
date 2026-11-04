"""The config write locks: one Hermes config write per home at a time (in this process and,
through a lock file, across processes), which Hermes commands write config, and one
apply per profile.

Owns: the home locks and their depth counters (one object each).
Must not: run Hermes or know what a write changes.

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "HOME_LOCK",
    "_HOME_DEPTH",
    "_HOME_GUARD",
    "_HOME_LOCKS",
    "_WRITING",
    "_Locks",
    "home_write_lock",
    "writes_config",
]


# Hermes's `config set` reads config.yaml, changes it and replaces the whole file,
# with no lock across processes (hermes_cli/config.py set_config_value ->
# atomic_config_replace; only its .env writer and plugin settings lock). Two writes
# on one home at once could lose one of them (a provider's base_url once vanished
# that way). Every Hermes command AGOS runs that can write a home's config runs
# one at a time per home: a thread lock, plus a file lock in the home other
# processes (the e2e rig, a script) can take too. Reentrant per thread.
HOME_LOCK = ".agos-config.lock"

_HOME_GUARD = threading.Lock()

_HOME_LOCKS: dict[str, threading.RLock] = {}

_HOME_DEPTH = threading.local()

_WRITING = {
    "config": {"set", "unset", "edit", "migrate"},
    "plugins": None,
    "mcp": None,
    "profile": None,
    "skills": None,
    "memory": None,
    "tools": None,
    "model": None,
}


def writes_config(args: Sequence[str]) -> bool:
    """A Hermes CLI command that may rewrite the home's config.yaml."""
    if not args:
        return False
    subs = _WRITING.get(args[0], set())
    if subs is None:
        return True
    return len(args) > 1 and args[1] in subs


@contextlib.contextmanager
def home_write_lock(home: Path) -> Iterator[None]:
    key = str(Path(home).resolve())
    with _HOME_GUARD:
        lock = _HOME_LOCKS.setdefault(key, threading.RLock())
    with lock:
        depth: dict[str, int] = getattr(_HOME_DEPTH, "by_home", None) or {}
        _HOME_DEPTH.by_home = depth
        depth[key] = depth.get(key, 0) + 1
        try:
            if depth[key] > 1:
                yield
                return
            import fcntl

            try:
                held = (Path(home) / HOME_LOCK).open("a")
            except OSError:
                yield  # no home folder yet (its first command makes it): thread lock only
                return
            with held:
                fcntl.flock(held, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(held, fcntl.LOCK_UN)
        finally:
            depth[key] -= 1


@dataclass
class _Locks:
    guard: threading.Lock = field(default_factory=threading.Lock)
    by_profile: dict[str, threading.Lock] = field(default_factory=dict)

    @contextlib.contextmanager
    def hold(self, name: str) -> Iterator[None]:
        with self.guard:
            lock = self.by_profile.setdefault(name, threading.Lock())
        with lock:
            yield
