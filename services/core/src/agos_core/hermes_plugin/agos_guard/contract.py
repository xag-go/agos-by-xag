"""A Hermes internal the plugin uses failed: said out loud, once.

The plugin keeps failing closed where it did (a block stays a block; nothing that
was refused becomes allowed). What changes is that the owner hears it: an ERROR
"Hermes contract broken: <name>" in this profile's agent.log, and the same to
AGOS (its Log, and his phone), once per name while this gateway runs. The names
are the entries of AGOS's contract (services/core/src/agos_core/engine/
hermes_contract.py): `<module>.<name>`.

Only contract-shaped failures count: the name is gone (ImportError,
AttributeError, NameError) or the call no longer fits (TypeError). A refusal
Hermes gives on purpose (its own errors) is not a broken contract.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import os
import re
import threading
from collections.abc import Iterator
from typing import Any

log = logging.getLogger("agos_guard")

SHAPED = (ImportError, AttributeError, NameError, TypeError)

_told: set[str] = set()
_lock = threading.Lock()
_inside: dict[str, bool] = {}


def inside_hermes() -> bool:
    """Running in Hermes (its modules importable): a missing Hermes module is then a
    break, not just a test run outside Hermes."""
    if "yes" not in _inside:
        try:
            _inside["yes"] = importlib.util.find_spec("hermes_cli") is not None
        except (ImportError, ValueError):
            _inside["yes"] = False
    return _inside["yes"]


def shaped(error: BaseException | None) -> bool:
    if error is None:
        return True
    if isinstance(error, ImportError) and not inside_hermes():
        return False
    return isinstance(error, SHAPED)


def gateway_id() -> str:
    """This gateway's start (Hermes's own gateway_state.json: pid + start time), so
    AGOS tells the owner once per name per gateway start, across its processes."""
    with contextlib.suppress(Exception):
        state = importlib.import_module("gateway.status").read_runtime_status() or {}
        if state.get("pid"):
            return f"{state.get('pid')}:{state.get('start_time') or ''}"
    return f"{os.getpid()}:"


def broken(name: str, error: BaseException | str | None = None) -> bool:
    """`name` (a contract entry) failed. Logs ERROR and tells AGOS, once per name in
    this process. True when it was reported now. Never raises."""
    if isinstance(error, BaseException) and not shaped(error):
        return False
    with _lock:
        if name in _told:
            return False
        _told.add(name)
    if isinstance(error, BaseException):
        detail = f"{type(error).__name__}: {error}"
        log.error("Hermes contract broken: %s (%s)", name, detail[:300], exc_info=error)
    else:
        detail = str(error or "missing")
        log.error("Hermes contract broken: %s (%s)", name, detail[:300])
    with contextlib.suppress(Exception):
        threading.Thread(
            target=_tell, args=(name, detail[:500]), name="agos-contract", daemon=True
        ).start()
    return True


def name_of(error: BaseException, fallback: str) -> str:
    """The Hermes name an ImportError / AttributeError says is gone, else `fallback`."""
    text = str(error)
    for pattern, build in (
        (r"cannot import name '(\w+)' from '([\w.]+)'", lambda m: f"{m[2]}.{m[1]}"),
        (r"module '([\w.]+)' has no attribute '(\w+)'", lambda m: f"{m[1]}.{m[2]}"),
        (r"No module named '([\w.]+)'", lambda m: m[1]),
    ):
        found = re.search(pattern, text)
        if found:
            return str(build(found))
    return fallback


def missing(name: str, value: Any) -> Any:
    """`value` (a getattr(..., None) of a Hermes internal) is None: reported as gone
    (inside Hermes only). Returns the value unchanged."""
    if value is None and inside_hermes():
        broken(name, "missing")
    return value


@contextlib.contextmanager
def guard(name: str) -> Iterator[None]:
    """Like contextlib.suppress(Exception) around a Hermes internal (what the code did
    before), plus the report of a contract-shaped failure."""
    try:
        yield
    except Exception as error:  # noqa: BLE001 — the caller's fallback stays as it was
        with contextlib.suppress(Exception):
            broken(name, error)


def _tell(name: str, detail: str) -> None:
    with contextlib.suppress(Exception):
        try:
            from . import bridge
        except ImportError:  # loaded beside the plugin by file (see __init__._sibling)
            import sys

            bridge = sys.modules["agos_guard_bridge"]
        if bridge.bridge() is None:
            return
        bridge.post("contract-broken", {"name": name, "error": detail, "gateway": gateway_id()}, 15)


def reset() -> None:
    """Forget what was told (tests)."""
    with _lock:
        _told.clear()
    _inside.clear()
