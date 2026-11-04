"""The Portability service's Co-Founder kinds (declared in ops/specs/portability.py),
bound to the page actions the Co-Founder already ran: each now runs through the
registry, which validates its fields, checks the caller and its workspace and writes
the audit row; its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import connection_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import portability as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(specs.IMPORT_BUNDLE, connection_actions.do_import)
bind_page(specs.EXPORT_BUNDLE, connection_actions.do_export)
