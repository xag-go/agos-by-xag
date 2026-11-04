"""Saga: a change in several steps where some steps are outside SQLite (Hermes,
files), so a database rollback can't undo them.

    with Saga(core, "workspace.create", data={...}) as saga:
        paths = saga.step("folders", make_folders, undo=lambda p: remove(p))
        saga.step("row", insert_row, undo=lambda _: delete_row())
        saga.step("sync", sync_hermes, tolerate=(ActionError,))  # may be finished later

Each step is journaled (db/sagas.py). When a step (or the code between steps)
raises, the done steps' compensations run in reverse; a compensation that fails is
journaled, logged to the System Log and listed in `failed_compensations`, and the
others still run; the error goes on. A step given `tolerate` that raises one of
those errors is journaled "failed" and logged, the saga goes on and ends "needs
attention"; `Saga.resume` runs such steps again later (a sync) and closes the
saga when none is left. Order deletes so a failure never leaves an orphan running:
stop the Hermes job first, then remove the row.

Owns: the step order, the journal and the compensation rule. Must not: hold any
service's steps (each service writes its own), or open a SQL transaction across
steps (a step that writes rows uses its own Unit of Work).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, Protocol, TypeVar

from agos_core.db import sagas as journal

__all__ = ["Saga"]

log = logging.getLogger("agos.saga")

T = TypeVar("T")


class _HasDb(Protocol):
    @property
    def db(self) -> Any: ...


class Saga:
    def __init__(
        self,
        core: _HasDb,
        name: str,
        *,
        workspace_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.core = core
        self.name = name
        self.workspace_id = workspace_id
        self.data = dict(data or {})
        self.id = 0
        self.unfinished: list[str] = []
        self.failed_compensations: list[str] = []
        self._done: list[tuple[int, str, Callable[[Any], object] | None, Any]] = []
        self._seq = 0

    def __enter__(self) -> Saga:
        self.id = journal.start(self.core.db, self.name, self.workspace_id, self.data)
        return self

    def attach(self, workspace_id: str) -> None:
        """The workspace this saga made exists now (its journal goes with it)."""
        self.workspace_id = workspace_id
        journal.attach(self.core.db, self.id, workspace_id)

    def step(
        self,
        name: str,
        do: Callable[[], T],
        *,
        undo: Callable[[T], object] | None = None,
        tolerate: tuple[type[BaseException], ...] = (),
    ) -> T | None:
        self._seq += 1
        seq = self._seq
        try:
            result = do()
        except tolerate as error:
            journal.record_step(self.core.db, self.id, seq, name, "failed", str(error)[:500])
            self.unfinished.append(name)
            log.warning(
                "%s: step %s left to finish later: %s",
                self.name,
                name,
                error,
                extra=self._where(),
            )
            return None
        except BaseException as error:
            journal.record_step(self.core.db, self.id, seq, name, "failed", str(error)[:500])
            raise
        journal.record_step(self.core.db, self.id, seq, name, "done", None)
        self._done.append((seq, name, undo, result))
        return result

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if error is None:
            status = "needs_attention" if self.unfinished else "done"
            left = ", ".join(self.unfinished) or None
            journal.finish(self.core.db, self.id, status, f"left: {left}" if left else None)
            return
        log.error("%s failed, undoing its steps: %s", self.name, error, extra=self._where())
        if self.workspace_id:
            # Undoing a create may remove the workspace: its journal must outlive it.
            journal.attach(self.core.db, self.id, None)
        for seq, name, undo, result in reversed(self._done):
            if undo is None:
                continue
            try:
                undo(result)
            except Exception as failed:
                self.failed_compensations.append(f"{name}: {failed}")
                journal.record_step(
                    self.core.db, self.id, seq, name, "compensation_failed", str(failed)[:500]
                )
                log.error(
                    "%s: step %s could not be undone: %s",
                    self.name,
                    name,
                    failed,
                    exc_info=failed,
                    extra=self._where(),
                )
                continue
            journal.record_step(self.core.db, self.id, seq, name, "compensated", None)
        if self.failed_compensations:
            journal.finish(
                self.core.db, self.id, "compensation_failed", "; ".join(self.failed_compensations)
            )
        else:
            journal.finish(self.core.db, self.id, "compensated", str(error)[:500])

    def _where(self) -> dict[str, Any] | None:
        return {"agos_workspace": self.workspace_id} if self.workspace_id else None

    @staticmethod
    def resume(core: _HasDb, saga_id: int, retry: Mapping[str, Callable[[], object]]) -> list[str]:
        """Runs again the failed steps that `retry` knows; returns the ones still left.
        The saga is done once none is left."""
        left: list[str] = []
        for row in journal.steps(core.db, saga_id):
            if row["status"] != "failed":
                continue
            name = str(row["name"])
            again = retry.get(name)
            if again is None:
                left.append(name)
                continue
            try:
                again()
            except Exception as error:
                journal.record_step(
                    core.db, saga_id, int(row["seq"]), name, "failed", str(error)[:500]
                )
                log.warning("step %s still not done: %s", name, error, exc_info=True)
                left.append(name)
                continue
            journal.record_step(core.db, saga_id, int(row["seq"]), name, "done", None)
        if left:
            journal.finish(core.db, saga_id, "needs_attention", "left: " + ", ".join(left))
        else:
            journal.finish(core.db, saga_id, "done")
        return left
