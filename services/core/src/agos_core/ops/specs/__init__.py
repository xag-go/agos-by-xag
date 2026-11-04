"""Every operation's declaration, one module per service (SPECS, in a fixed order).

Owns: the list. Must not: declare an operation here (its service module does).
"""

from __future__ import annotations

from typing import Any

from agos_core.ops.spec import OperationSpec
from agos_core.ops.specs import (
    automation,
    connector,
    library,
    portability,
    settings,
    team,
    vision,
    workspace,
)

__all__ = ["SPECS"]

SPECS: tuple[OperationSpec[Any], ...] = (
    *workspace.SPECS,
    *automation.SPECS,
    *team.SPECS,
    *library.SPECS,
    *vision.SPECS,
    *settings.SPECS,
    *connector.SPECS,
    *portability.SPECS,
)
