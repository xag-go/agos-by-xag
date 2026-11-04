"""Idempotency for an owner call that is not a registered operation yet (the owner's
own hire, Run now): `once(core, operation, key, do)` runs `do` once per (operation,
key) and gives a retry or a double click the first answer. The same rule and rows
as the registry's own key (registry.run(..., idempotency_key)): an audit row in
op_runs, a failed try lets its key go, a key of another workspace is refused.

Owns: that rule for calls outside the registry. Must not: hold the call's logic
(its service does) or open a transaction around `do`.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from agos_core.db import op_runs
from agos_core.ops.errors import OperationNotAllowed

__all__ = ["once"]

_locks: dict[tuple[str, str], threading.Lock] = {}
_guard = threading.Lock()


def _lock(operation: str, key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault((operation, key), threading.Lock())


def once(
    core: Any,
    operation: str,
    key: str | None,
    do: Callable[[], dict[str, Any]],
    *,
    workspace_id: str | None = None,
    title: str = "",
    actor: str = "owner",
) -> dict[str, Any]:
    """`do()` once per key (no key: every time); returns its answer or the first one."""
    if key is None:
        return do()
    with _lock(operation, key):
        prior = op_runs.find(core.db, operation, key)
        if prior is not None and prior["status"] in ("done", "undone"):
            if workspace_id is not None and prior["workspace_id"] not in (None, workspace_id):
                raise OperationNotAllowed(f"{operation}: this key was used in another workspace")
            return op_runs.result_of(prior)
        if prior is not None:
            op_runs.forget_key(core.db, int(prior["id"]))
        try:
            run_id = op_runs.start(core.db, operation, actor, title or operation, key)
        except sqlite3.IntegrityError as error:  # another process holds this key now
            raise OperationNotAllowed(f"{operation} is already running for this key") from error
        try:
            result = do()
        except BaseException as error:
            text = str(error) or type(error).__name__
            op_runs.finish(core.db, run_id, "failed", error=text, workspace_id=workspace_id)
            raise
        op_runs.finish(core.db, run_id, "done", result=result, workspace_id=workspace_id)
        return result
