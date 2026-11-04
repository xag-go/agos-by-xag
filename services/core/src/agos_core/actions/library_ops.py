"""The Library service's Co-Founder kinds (declared in ops/specs/library.py), bound to
the page actions the Co-Founder already ran: each now runs through the registry,
which validates its fields, checks the caller and its workspace and writes the audit
row; its card's Undo is the operation's undo of that run.

Owns: the binding. Must not: hold a kind's steps (its page action does).
"""

from __future__ import annotations

from agos_core.actions.services.cofounder import skill_actions
from agos_core.actions.services.cofounder.op_binding import bind_page
from agos_core.ops.specs import library as specs

__all__: list[str] = []  # binds at import; nothing to call

bind_page(specs.DELETE_LIBRARY_ITEM, skill_actions.do_delete_item)
bind_page(specs.DUPLICATE_SKILL, skill_actions.do_duplicate, skill_actions.undo_duplicate)
bind_page(specs.APPLY_SKILL_UPDATE, skill_actions.do_apply_update, skill_actions.undo_version)
bind_page(specs.SET_SKILL_AUTO_UPDATE, skill_actions.do_auto_update, skill_actions.undo_auto_update)
bind_page(
    specs.SAVE_SKILL_TEST_SETTINGS, skill_actions.do_test_settings, skill_actions.undo_test_settings
)
bind_page(specs.ADD_SKILL_TEST_INPUT, skill_actions.do_add_input, skill_actions.undo_add_input)
bind_page(
    specs.UPDATE_SKILL_TEST_INPUT, skill_actions.do_update_input, skill_actions.undo_update_input
)
bind_page(
    specs.DELETE_SKILL_TEST_INPUT, skill_actions.do_delete_input, skill_actions.undo_delete_input
)
bind_page(specs.RUN_SKILL_TEST, skill_actions.do_run_test)
bind_page(specs.RERUN_SKILL_TEST, skill_actions.do_rerun_test)
bind_page(specs.GRADE_SKILL_TEST, skill_actions.do_grade_test)
bind_page(specs.RESTORE_SKILL_VERSION, skill_actions.do_restore_version, skill_actions.undo_version)
bind_page(
    specs.SET_SKILL_REQUEST_LIMIT, skill_actions.do_request_limit, skill_actions.undo_request_limit
)
bind_page(specs.SET_SKILL_REVIEW, skill_actions.do_skill_review, skill_actions.undo_skill_review)
bind_page(specs.INSTALL_SKILL, skill_actions.do_install_skill)
bind_page(specs.MCP_SIGN_IN, skill_actions.do_mcp_sign_in)
bind_page(specs.MCP_SIGN_OUT, skill_actions.do_mcp_sign_out)
bind_page(specs.REMOVE_GITHUB_TOKEN, skill_actions.do_github_token)
