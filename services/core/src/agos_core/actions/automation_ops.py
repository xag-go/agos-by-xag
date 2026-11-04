"""The Automation service's Co-Founder kinds (declared in ops/specs/automation.py),
bound to the page actions the Co-Founder already ran: each now runs through the
registry, which validates its fields, checks the caller and its workspace and writes
the audit row; its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import automation_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import automation as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(specs.SAVE_PIPELINE_RULE, automation_actions.do_save_rule, automation_actions.undo_rule)
bind_page(
    specs.DELETE_PIPELINE_RULE, automation_actions.do_delete_rule, automation_actions.undo_rule
)
bind_page(
    specs.SET_HEARTBEAT, automation_actions.do_set_heartbeat, automation_actions.undo_heartbeat
)
bind_page(
    specs.RESTORE_AUTOMATION_REVISION,
    automation_actions.do_restore_automation,
    automation_actions.undo_automation,
)
bind_page(
    specs.SET_AUTOMATION_CATCH_UP, automation_actions.do_catch_up, automation_actions.undo_catch_up
)
bind_page(specs.REMOVE_SCHEDULED_JOB, automation_actions.do_remove_job)
bind_page(
    specs.SET_HOOKS_ADDRESS,
    automation_actions.do_hooks_address,
    automation_actions.undo_hooks_address,
)
bind_page(specs.WATCH_TREE, automation_actions.do_watch_tree, automation_actions.undo_watch_tree)
