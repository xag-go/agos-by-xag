"""Unit of Work: one SQL transaction, plus the compensations of the side effects
done while it was open, plus what may only happen once it committed.

    with UnitOfWork(core, name="create workspace") as uow:
        repo.insert(...)                     # inside the transaction
        made = hermes_step(...)              # outside SQLite: can't be rolled back
        uow.on_rollback(lambda: undo(made))  # so it registers its compensation
        uow.publish(Event(...))              # told to subscribers after commit
        uow.after_commit(outbox.wake)        # anything else that must wait for it

On an exception the transaction rolls back and the compensations run in reverse
order; one that fails is logged (System Log) and listed in `failed_compensations`,
never swallowed, and the others still run. After a commit the hooks and events run
in order; a failing hook is logged and never undoes the commit. A unit opened
inside another one on the same connection and thread becomes its savepoint and
hands its hooks and compensations to the outer unit when it succeeds.

Owns: the commit / rollback rule and the ordering of compensations and hooks.
Must not: run any service's rule, talk to Hermes itself, or send notifications
(those are outbox rows written inside the unit).
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol

from agos_core import events
from agos_core.db.connection import transaction

__all__ = ["UnitOfWork"]

log = logging.getLogger("agos.uow")

_open = threading.local()  # per thread: [(db id, unit), ...], innermost last


class _HasDb(Protocol):
    @property
    def db(self) -> Any: ...


def _stack() -> list[tuple[int, UnitOfWork]]:
    found: list[tuple[int, UnitOfWork]] | None = getattr(_open, "units", None)
    if found is None:
        found = []
        _open.units = found
    return found


class UnitOfWork:
    def __init__(self, core: _HasDb, *, name: str = "", workspace_id: str | None = None) -> None:
        self.core = core
        self.name = name
        self.workspace_id = workspace_id
        self.failed_compensations: list[str] = []
        self._compensations: list[tuple[str, Callable[[], None]]] = []
        self._after: list[Callable[[], None]] = []
        self._tx: contextlib.AbstractContextManager[None] | None = None
        self._parent: UnitOfWork | None = None

    def on_rollback(self, compensation: Callable[[], None], what: str = "") -> None:
        """Undoes a side effect already done, if the unit fails later; `what` names
        it in the log when it fails."""
        self._compensations.append((what or "a compensation", compensation))

    def after_commit(self, hook: Callable[[], None]) -> None:
        self._after.append(hook)

    def publish(self, event: events.Event) -> None:
        self._after.append(lambda: events.publish(self.core, event))

    def __enter__(self) -> UnitOfWork:
        stack = _stack()
        key = id(self.core.db)
        self._parent = next((u for k, u in reversed(stack) if k == key), None)
        self._tx = transaction(self.core.db)
        self._tx.__enter__()
        stack.append((key, self))
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        stack = _stack()
        stack.pop()
        assert self._tx is not None
        if error is not None:
            with contextlib.suppress(BaseException):
                self._tx.__exit__(kind, error, trace)
            self._compensate()
            return  # the exception goes on
        self._tx.__exit__(None, None, None)
        if self._parent is not None:
            self._parent._compensations.extend(self._compensations)
            self._parent._after.extend(self._after)
            return
        for hook in self._after:
            try:
                hook()
            except Exception:
                log.exception("after the commit of %s, a follow-up failed", self.name or "a change")

    def _compensate(self) -> None:
        for what, compensation in reversed(self._compensations):
            try:
                compensation()
            except Exception as error:
                self.failed_compensations.append(f"{what}: {error}")
                log.error(
                    "%s failed and could not be fully undone: %s: %s",
                    self.name or "a change",
                    what,
                    error,
                    exc_info=error,
                    extra={"agos_workspace": self.workspace_id} if self.workspace_id else None,
                )
