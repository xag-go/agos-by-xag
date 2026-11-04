"""The Vision service's Co-Founder kinds (declared in ops/specs/vision.py), bound to
the page actions the Co-Founder already ran: each now runs through the registry,
which validates its fields, checks the caller and its workspace and writes the audit
row; its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import workspace_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import vision as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(specs.SET_RHYTHM, workspace_actions.do_rhythm, workspace_actions.undo_rhythm)
bind_page(specs.SAVE_VISION_NOTES, workspace_actions.do_notes, workspace_actions.undo_notes)
bind_page(specs.ORGANIZE_VISION_NOTES, workspace_actions.do_organize)
bind_page(specs.TICK_TODAY, workspace_actions.do_tick)
