"""A declaration bound to its service's code, the caller of a run and its context.

Owns: `Operation`, `Actor` and `OpContext`. Must not: run anything (registry.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal

from agos_core.ops.spec import In, OperationSpec

__all__ = ["AGENT", "COFOUNDER", "OWNER", "Actor", "Do", "OpContext", "Operation", "Undo"]


@dataclass(frozen=True)
class Actor:
    kind: Literal["owner", "cofounder", "agent"]
    name: str = ""

    @property
    def label(self) -> str:
        return f"agent:{self.name}" if self.kind == "agent" else self.kind


OWNER = Actor("owner")
COFOUNDER = Actor("cofounder")


def AGENT(member: str) -> Actor:
    return Actor("agent", member)


@dataclass(frozen=True)
class OpContext:
    actor: Actor
    workspace_id: str | None
    idempotency_key: str | None
    run_id: int


Do = Callable[[Any, OpContext, Any], dict[str, Any]]
Undo = Callable[[Any, OpContext, dict[str, Any]], None]


@dataclass(frozen=True)
class Operation(Generic[In]):
    spec: OperationSpec[In]
    do: Do
    undo: Undo | None = None
