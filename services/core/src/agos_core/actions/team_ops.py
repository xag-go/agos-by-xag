"""The Team service's Co-Founder kinds (declared in ops/specs/team.py), bound to the
page actions the Co-Founder already ran: each now runs through the registry, which
validates its fields, checks the caller and its workspace and writes the audit row;
its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import connection_actions, team_actions, workspace_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import team as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(specs.CREATE_GROUP, team_actions.do_create_group, team_actions.undo_create_group)
bind_page(specs.SET_GROUP_MEMBERS, team_actions.do_set_group, team_actions.undo_set_group)
bind_page(specs.SAVE_KIT, team_actions.do_save_kit, team_actions.undo_kit)
bind_page(specs.SUGGEST_MEMBER_KIT, team_actions.do_suggest_kit)
bind_page(specs.CHOOSE_READINESS, team_actions.do_readiness, team_actions.undo_readiness)
bind_page(specs.SET_OFFICE_LOOK, team_actions.do_office_look, team_actions.undo_office_look)
bind_page(specs.INSTALL_TEMPLATE, connection_actions.do_install_template)
bind_page(
    specs.RESTORE_AGENT_VERSION,
    workspace_actions.do_restore_agent,
    workspace_actions.undo_restore_agent,
)
bind_page(
    specs.RESTORE_AGENT_REVISION,
    workspace_actions.do_agent_revision,
    workspace_actions.undo_agent_revision,
)
