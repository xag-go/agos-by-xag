"""The base Co-Founder kinds (declared in ops/specs/chat_base.py, hermes_admin.py and
founder.py) bound to the code the action cards already run them with: dispatch.py's `do` /
`undo` of one kind. A card still runs its kind through that code directly (the same
steps, the same result, no audit row of its own); bound here, the same kind also runs
through the registry like every other declared kind.

Owns: the binding. Must not: hold a kind's steps (dispatch.py and its helpers do).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.context import Core
from agos_core.ops.specs import chat_base, founder, hermes_admin

__all__ = ["NAMES", "bind"]

# The kinds whose card runs through dispatch.py, not through the registry's adapter.
NAMES = frozenset(s.name for s in (*chat_base.SPECS, *hermes_admin.SPECS, *founder.SPECS))

Do = Callable[[Core, str, str, dict[str, Any]], dict[str, Any]]
Undo = Callable[[Core, str, str, dict[str, Any]], None]


def bind(do: Do, undo: Undo) -> None:
    for spec in (*chat_base.SPECS, *hermes_admin.SPECS, *founder.SPECS):
        name = spec.name

        def run(core: Core, ws: str, p: dict[str, Any], name: str = name) -> dict[str, Any]:
            return do(core, ws, name, p)

        def back(core: Core, ws: str, r: dict[str, Any], name: str = name) -> None:
            undo(core, ws, name, r)

        bind_page(spec, run, back if spec.has_undo else None)
