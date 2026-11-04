"""Binds a declared Co-Founder kind (ops/specs) to the page action the Co-Founder
runs it with: `do(core, workspace_id, fields) -> result` and `undo(core,
workspace_id, result)`, the shape of every actions/services/cofounder/*_actions.py
function. The registry calls the bound operation with its validated input; the
page action gets the fields as the Co-Founder sent them and the workspace it runs in.

Owns: that adapter. Must not: hold a kind's steps or run one itself (the registry
does, ops/cofounder.py for the Co-Founder).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.action_args import Fields, Result
from agos_core.context import Core
from agos_core.ops import registry
from agos_core.ops.operation import OpContext, Operation
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["bind_page"]

PageDo = Callable[[Core, str, Fields], Result]
PageUndo = Callable[[Core, str, Result], None]


def _where(ctx: OpContext) -> str:
    if not ctx.workspace_id:
        raise ActionError("This runs inside a workspace.")
    return ctx.workspace_id


def bind_page(spec: OperationSpec[Any], do: PageDo, undo: PageUndo | None = None) -> Operation[Any]:
    def run(core: Core, ctx: OpContext, data: CofounderFields) -> dict[str, Any]:
        return do(core, _where(ctx), data.model_dump(exclude_unset=True))

    def back(core: Core, ctx: OpContext, result: dict[str, Any]) -> None:
        assert undo is not None
        undo(core, _where(ctx), result)

    return registry.bind(spec, do=run, undo=back if undo is not None else None)
