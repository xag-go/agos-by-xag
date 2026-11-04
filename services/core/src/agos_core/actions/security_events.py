"""Security events: refused requests, in the System Log (source `security`).

What is written: a Host or Origin the web app refused (DNS rebinding, a cross-site
POST), a wrong or missing internal token at the core's API, a wrong bridge key at
`/hermes-bridge/<workspace>/…`, a local MCP relay refusing a call. Never the value
given (a token, a key): only what kind of refusal, where, and a short safe label
(a host name, a path). Rate-limited per kind so a scan can't flood the log: at most
PER_WINDOW lines per kind per WINDOW_S, then one line that says how many were
dropped.
"""

from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger("agos.security")

SOURCE = "security"  # the System Log's source column (actions/system_log.py)
WINDOW_S = 60.0
PER_WINDOW = 30  # a scan floods one kind: 30 a minute keeps real ones (review L13)
KINDS = {
    "host": "a request with a Host AGOS doesn't serve was refused",
    "origin": "a request from another site (its Origin) was refused",
    "internal_token": "a call to the core's API with a wrong or missing internal token was refused",
    "bridge_key": "a Hermes bridge call with a wrong workspace key was refused",
}
_SAFE = re.compile(r"[^A-Za-z0-9._:/\[\]@+-]")
_lock = threading.Lock()
_windows: dict[str, tuple[float, int]] = {}  # kind -> (window start, lines in it)


def _safe(text: str, cap: int = 120) -> str:
    """A label for the log: no spaces, no control characters, no query string."""
    return _SAFE.sub("_", text.split("?", 1)[0])[:cap]


def record(
    kind: str, *, where: str = "", detail: str = "", workspace_id: str | None = None
) -> bool:
    """One refusal; True when it was written (False: rate-limited or unknown kind)."""
    if kind not in KINDS:
        return False
    at = time.monotonic()
    dropped = 0
    with _lock:
        start, count = _windows.get(kind, (at, 0))
        if at - start > WINDOW_S:
            dropped = max(0, count - PER_WINDOW)
            start, count = at, 0
        count += 1
        _windows[kind] = (start, count)
        if count > PER_WINDOW:
            return False
    extra = {"agos_log_source": SOURCE}
    if workspace_id:
        extra["agos_workspace"] = workspace_id
    if dropped:
        log.warning("security: %d more %s refusals in the last minute", dropped, kind, extra=extra)
    label = f" ({_safe(detail)})" if detail else ""
    log.warning("security: %s%s on %s", KINDS[kind], label, _safe(where) or "?", extra=extra)
    return True


def reset() -> None:
    """Tests: a fresh window for every kind."""
    with _lock:
        _windows.clear()
