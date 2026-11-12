"""Every operation's declaration, one module per service (SPECS, in a fixed order).

Owns: the list. Must not: declare an operation here (its service module does).
"""

from __future__ import annotations

from typing import Any

from agos_core.ops.spec import OperationSpec
from agos_core.ops.specs import (
    automation,
    board,
    channels,
    chat_base,
    connector,
    folders,
    founder,
    hermes_admin,
    library,
    portability,
    preferences,
    rules_docs,
    settings,
    team,
    vision,
    work_hours,
    workspace,
)

__all__ = ["SPECS"]

# The order is the Co-Founder's KINDS order: the hidden skill lists each domain's kinds in it.
SPECS: tuple[OperationSpec[Any], ...] = (
    *board.SPECS,
    *work_hours.SPECS,
    *rules_docs.SPECS,
    *channels.SPECS,
    *preferences.SPECS,
    *folders.SPECS,
    *workspace.SPECS,
    *automation.SPECS,
    *team.SPECS,
    *library.SPECS,
    *vision.SPECS,
    *settings.SPECS,
    *connector.SPECS,
    *portability.SPECS,
    *chat_base.SPECS,
    *hermes_admin.SPECS,
    *founder.SPECS,
)
