"""The Co-Founder's do / undo for the declared kinds (the ones of a Co-Founder
domain): actions/services/cofounder/page_actions.py merges them into its DOES /
UNDOES, so a declared kind runs through the registry like the owner's own action,
with its permission check, workspace scope and audit row; its card's Undo is the
operation's undo of that run (a card made before the kind was declared, with no run
in its result, gets the operation's undo of its result).

Owns: that adapter. Must not: hold a kind's logic (its service binds it).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agos_core.ops.operation import COFOUNDER
from agos_core.ops.registry import REGISTRY, Registry

__all__ = ["RUN_KEY", "adapters"]

RUN_KEY = "op_run"  # the card's result keeps its run, for its Undo

CofounderDo = Callable[[Any, str, dict[str, Any]], dict[str, Any]]
CofounderUndo = Callable[[Any, str, dict[str, Any]], None]


def adapters(
    registry: Registry = REGISTRY,
) -> tuple[dict[str, CofounderDo], dict[str, CofounderUndo]]:
    does: dict[str, CofounderDo] = {}
    undoes: dict[str, CofounderUndo] = {}
    for spec in registry.specs():
        if spec.cofounder_domain is None:
            continue
        does[spec.name] = _do_of(registry, spec.name)
        if spec.has_undo:
            undoes[spec.name] = _undo_of(registry, spec.name)
    return does, undoes


def _do_of(registry: Registry, name: str) -> CofounderDo:
    def do(core: Any, workspace_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        run_id, result = registry.execute(
            core, name, fields, actor=COFOUNDER, workspace_id=workspace_id
        )
        return {**result, RUN_KEY: run_id}

    return do


def _undo_of(registry: Registry, name: str) -> CofounderUndo:
    def undo(core: Any, workspace_id: str, result: dict[str, Any]) -> None:
        if RUN_KEY not in result:  # a card made before its kind was declared here
            registry.undo_unrecorded(
                core, name, result, actor=COFOUNDER, workspace_id=workspace_id or None
            )
            return
        registry.undo(core, int(result[RUN_KEY]), actor=COFOUNDER, workspace_id=workspace_id)

    return undo
