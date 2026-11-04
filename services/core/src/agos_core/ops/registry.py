"""Binding declarations to their service's code, and running them.

`run(core, name, data, actor=..., workspace_id=..., idempotency_key=...)`:
1. finds the bound operation (UnknownOperation if none);
2. checks the caller: the owner runs anything; the Co-Founder only a kind of a
   Co-Founder domain, an agent only an agent tool; both only inside the workspace
   they run in (an input's `workspace_id` must be theirs);
3. validates the input with the declaration's Pydantic model;
4. with an idempotency key (create / run operations only): the first run's result
   is returned to a retry or a double click, which never does the work again; a
   failed run lets its key go, so a retry is a new try;
5. writes the audit row (db/op_runs.py), runs `do`, records how it ended.
`undo(core, run_id, actor)` runs the operation's own undo once
(`undo_unrecorded`: a run from before its audit row, e.g. an older Co-Founder card).

Owns: those rules. Must not: hold an operation's own logic (its service does) or
open a transaction around `do` (the service's Unit of Work / saga does).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel

from agos_core.db import op_runs
from agos_core.ops.errors import OperationNotAllowed, UnknownOperation
from agos_core.ops.operation import Actor, Do, OpContext, Operation, Undo
from agos_core.ops.spec import WORKSPACE_FIELD, OperationSpec
from agos_core.ops.specs import SPECS

__all__ = ["REGISTRY", "Registry", "bind", "run", "undo"]


class Registry:
    def __init__(self, specs: Iterable[OperationSpec[Any]]) -> None:
        self._specs = {s.name: s for s in specs}
        self._bound: dict[str, Operation[Any]] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def bind(self, spec: OperationSpec[Any], *, do: Do, undo: Undo | None = None) -> Operation[Any]:
        if self._specs.get(spec.name) is not spec:
            raise ValueError(f"{spec.name} is not declared in this registry")
        if spec.has_undo and undo is None:
            raise ValueError(f"{spec.name}: its gate promises Undo, give it an undo")
        operation = Operation(spec, do, undo)
        self._bound[spec.name] = operation
        return operation

    def unbound(self) -> list[str]:
        return sorted(n for n in self._specs if n not in self._bound)

    def get(self, name: str) -> Operation[Any]:
        found = self._bound.get(name)
        if found is None:
            raise UnknownOperation(name)
        return found

    def specs(self) -> list[OperationSpec[Any]]:
        return list(self._specs.values())

    def run(
        self,
        core: Any,
        name: str,
        data: Mapping[str, Any] | BaseModel,
        *,
        actor: Actor,
        workspace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Runs it; returns what its `do` returned (or the first run's, for a retry)."""
        return self.execute(
            core,
            name,
            data,
            actor=actor,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )[1]

    def execute(
        self,
        core: Any,
        name: str,
        data: Mapping[str, Any] | BaseModel,
        *,
        actor: Actor,
        workspace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """`run`, plus the id of its audit row (what an Undo names)."""
        operation = self.get(name)
        spec = operation.spec
        _check_caller(spec, actor, workspace_id)
        raw = data.model_dump() if isinstance(data, BaseModel) else dict(data)
        if actor.kind != "owner" and WORKSPACE_FIELD in spec.input_model.model_fields:
            given = raw.setdefault(WORKSPACE_FIELD, workspace_id)
            if given != workspace_id:
                raise OperationNotAllowed(f"{name}: another workspace's {WORKSPACE_FIELD}")
        model = spec.input_model.model_validate(raw)
        if idempotency_key is None:
            return self._run(core, operation, model, actor, workspace_id, None)
        if not spec.idempotent:
            raise ValueError(f"{name} takes no idempotency key")
        with self._lock_for(name, idempotency_key):
            prior = op_runs.find(core.db, name, idempotency_key)
            if prior is not None and prior["status"] in ("done", "undone"):
                if workspace_id is not None and prior["workspace_id"] not in (None, workspace_id):
                    raise OperationNotAllowed(f"{name}: this key was used in another workspace")
                return int(prior["id"]), op_runs.result_of(prior)
            if prior is not None:
                op_runs.forget_key(core.db, int(prior["id"]))
            return self._run(core, operation, model, actor, workspace_id, idempotency_key)

    def undo(
        self, core: Any, run_id: int, *, actor: Actor, workspace_id: str | None = None
    ) -> None:
        row = op_runs.get(core.db, run_id)
        if row is None or row["status"] != "done":
            raise OperationNotAllowed("This can't be undone (not a finished run).")
        operation = self.get(str(row["operation"]))
        if operation.undo is None:
            raise OperationNotAllowed(f"{operation.spec.name} can't be undone.")
        _check_caller(operation.spec, actor, workspace_id)
        if actor.kind != "owner" and row["workspace_id"] != workspace_id:
            raise OperationNotAllowed("Another workspace's run.")
        ctx = OpContext(actor, row["workspace_id"], row["idempotency_key"], run_id)
        operation.undo(core, ctx, op_runs.result_of(row))
        op_runs.mark_undone(core.db, run_id)

    def undo_unrecorded(
        self,
        core: Any,
        name: str,
        result: dict[str, Any],
        *,
        actor: Actor,
        workspace_id: str | None = None,
    ) -> None:
        """The undo of a run that has no audit row (a Co-Founder card made before its
        kind was declared here): the same caller checks, then the operation's undo
        with that run's result."""
        operation = self.get(name)
        if operation.undo is None:
            raise OperationNotAllowed(f"{name} can't be undone.")
        _check_caller(operation.spec, actor, workspace_id)
        operation.undo(core, OpContext(actor, workspace_id, None, 0), result)

    def _run(
        self,
        core: Any,
        operation: Operation[Any],
        model: BaseModel,
        actor: Actor,
        workspace_id: str | None,
        key: str | None,
    ) -> tuple[int, dict[str, Any]]:
        spec = operation.spec
        try:
            run_id = op_runs.start(core.db, spec.name, actor.label, spec.title(model), key)
        except sqlite3.IntegrityError as error:  # another process holds this key now
            raise OperationNotAllowed(f"{spec.name} is already running for this key") from error
        ctx = OpContext(actor, workspace_id, key, run_id)
        where = workspace_id or getattr(model, WORKSPACE_FIELD, None)
        try:
            result = operation.do(core, ctx, model)
        except BaseException as error:
            text = str(error) or type(error).__name__
            op_runs.finish(core.db, run_id, "failed", error=text, workspace_id=where)
            raise
        op_runs.finish(
            core.db,
            run_id,
            "done",
            result=result,
            workspace_id=result.get(WORKSPACE_FIELD) or where,
        )
        return run_id, result

    def _lock_for(self, name: str, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault((name, key), threading.Lock())


def _check_caller(spec: OperationSpec[Any], actor: Actor, workspace_id: str | None) -> None:
    if actor.kind == "owner":
        return
    if actor.kind == "cofounder" and spec.cofounder_domain is None:
        raise OperationNotAllowed(f"{spec.name} is the owner's alone: {spec.owner_only}")
    if actor.kind == "agent" and spec.agent_tool is None:
        raise OperationNotAllowed(f"{spec.name} is no agent tool")
    if workspace_id is None:
        raise OperationNotAllowed(f"{spec.name}: a {actor.kind} runs inside its workspace")


# The app's one registry: every declaration of ops/specs, bound by its service.
REGISTRY = Registry(SPECS)
bind = REGISTRY.bind
run = REGISTRY.run
undo = REGISTRY.undo
