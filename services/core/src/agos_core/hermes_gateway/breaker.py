"""A circuit breaker per Hermes root (ADR 0024).

Closed: calls run. FAILURES unavailability failures in a row (no answer, could not
start) open it: calls fail fast for OPEN_FOR_S. Then one call is let through as the
probe (half-open; others still fail fast while it runs): an answer closes it, a
failure opens it again. Any answer, a refusal included, means Hermes is up."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

FAILURES = 3
OPEN_FOR_S = 30.0


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False


class Breakers:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _State] = {}

    def allow(self, root: str) -> bool:
        """Whether a call on this root may start now (claims the probe when due)."""
        with self._lock:
            state = self._states.get(root)
            if state is None or state.opened_at is None:
                return True
            if state.probing or self._clock() - state.opened_at < OPEN_FOR_S:
                return False
            state.probing = True
            return True

    def answered(self, root: str) -> None:
        with self._lock:
            self._states.pop(root, None)

    def failed(self, root: str) -> None:
        with self._lock:
            state = self._states.setdefault(root, _State())
            state.failures += 1
            if state.probing or state.failures >= FAILURES:
                state.opened_at = self._clock()
            state.probing = False

    def released(self, root: str) -> None:
        """A call that ended without telling whether Hermes is up (a fake's plain
        error, a bug): a probe it held is given back."""
        with self._lock:
            state = self._states.get(root)
            if state is not None:
                state.probing = False

    def is_open(self, root: str) -> bool:
        with self._lock:
            state = self._states.get(root)
            return state is not None and state.opened_at is not None

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


# One registry for the process: every runner and process run on a root shares it.
BREAKERS = Breakers()
