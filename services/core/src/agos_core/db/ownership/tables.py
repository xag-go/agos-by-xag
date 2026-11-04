"""Every AGOS table and column in one dict, merged from the per-area modules in a
fixed order (chats, automations, system, board, service layer).

Owns: the merge order. Must not: hold an entry (each lives in its area module).
"""

from __future__ import annotations

from agos_core.db.ownership import automations, board, chats, service_layer, system
from agos_core.db.ownership.base import Table

__all__ = ["TABLES"]

TABLES: dict[str, Table] = {
    **chats.TABLES,
    **automations.TABLES,
    **system.TABLES,
    **board.TABLES,
    **service_layer.TABLES,
}
