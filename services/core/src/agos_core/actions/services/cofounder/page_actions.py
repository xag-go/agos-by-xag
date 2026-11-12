"""The table of the Co-Founder's page actions: each kind's do and undo, and running them.
Must not: hold any kind's logic (that lives in its page's module above).

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

from agos_core.actions import (  # noqa: F401 - each binds its service's declared kinds
    automation_ops,
    board_ops,
    cofounder_prefs,
    connector_ops,
    library_ops,
    portability_ops,
    settings_ops,
    team_ops,
    vision_ops,
    workspace_admin_ops,
)
from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.action_args import Fields, Result
from agos_core.context import Core
from agos_core.engine import cofounder_parity as parity
from agos_core.ops import cofounder as ops_cofounder

__all__ = [
    "DOES",
    "KINDS",
    "UNDOES",
    "Do",
    "Undo",
    "do",
    "undo",
]

Do = Callable[[Core, str, Fields], Result]
Undo = Callable[[Core, str, Result], None]

# The registry's Co-Founder kinds (ops/specs), run through ops.registry like the owner's.
_OPS_DOES, _OPS_UNDOES = ops_cofounder.adapters()

# Every kind is declared (ops/specs) and bound by its service (the *_ops modules above).
DOES: dict[str, Do] = dict(_OPS_DOES)
UNDOES: dict[str, Undo] = dict(_OPS_UNDOES)

KINDS = frozenset(parity.KINDS)


def do(core: Core, workspace_id: str, action: str, p: Fields) -> Result:
    """Runs one of these kinds through its page's own action; returns what Undo needs.
    It runs inside the Co-Founder's own turn: a gateway restart its page's code asks
    for waits until the turn's answer is out (hermes_channel.inside_turn)."""
    from agos_core.actions import hermes_channel

    with hermes_channel.inside_turn():
        return DOES[action](core, workspace_id, p)


def undo(core: Core, workspace_id: str, action: str, result: Result) -> None:
    found = UNDOES.get(action)
    if found is None:
        raise ActionError("This can't be undone.", 409)
    found(core, workspace_id, result)
