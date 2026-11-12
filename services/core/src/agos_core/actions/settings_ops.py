"""The Settings service's Co-Founder kinds (declared in ops/specs/settings.py), bound
to the page actions the Co-Founder already ran: each now runs through the registry,
which validates its fields, checks the caller and its workspace and writes the audit
row; its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import settings_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import settings as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(
    specs.SET_WORKSPACE_SETTINGS, settings_actions.do_ws_settings, settings_actions.undo_ws_settings
)
bind_page(specs.SET_HERMES_LIMITS, settings_actions.do_limits, settings_actions.undo_limits)
bind_page(specs.SET_TIME_LIMITS, settings_actions.do_time_limits, settings_actions.undo_time_limits)
bind_page(specs.SET_HELPER_MODELS, settings_actions.do_helpers)
bind_page(specs.SET_VOICE, settings_actions.do_voice, settings_actions.undo_voice)
bind_page(specs.SET_FALLBACK, settings_actions.do_fallback, settings_actions.undo_fallback)
bind_page(specs.CHECK_UPDATES, settings_actions.do_check_updates)
bind_page(specs.RUN_UPDATES, settings_actions.do_run_updates)
