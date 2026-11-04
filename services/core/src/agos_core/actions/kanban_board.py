"""The workspace's Kanban, shown and driven in AGOS: Hermes's own board.

Everything goes through Hermes's Kanban CLI on the workspace's profile (its own
Kanban home): AGOS keeps no copy of the cards. A card's assignee is a team member's
profile; AGOS shows the member's name.

Compatibility facade of the Board service (actions/services/board/): every name
callers and tests reach here lives in its part and is re-exported, so each import
path keeps working. The one port to Hermes's Kanban CLI is kanban_cli.py; patch
the part that owns a name (`kanban_cli.run`, `card_writes.create`, ...), not this
facade.

Must not: hold code of its own (only `_cli`, which forwards to the port so a
patch on the port is seen by callers that still reach it here).
"""

from __future__ import annotations

from agos_core.actions.services.board import (
    board_list,
    card_bulk,
    card_detail,
    card_files,
    card_members,
    card_shape,
    card_writes,
    kanban_cli,
    kanban_db,
)
from agos_core.actions.services.board.board_list import _listed_cache as _listed_cache
from agos_core.actions.services.board.board_list import _stats_cache as _stats_cache
from agos_core.actions.services.board.board_list import board as board
from agos_core.actions.services.board.board_list import by_where as by_where
from agos_core.actions.services.board.board_list import counters as counters
from agos_core.actions.services.board.board_list import read_ahead as read_ahead
from agos_core.actions.services.board.card_bulk import BULK_ARGV as BULK_ARGV
from agos_core.actions.services.board.card_bulk import act_many as act_many
from agos_core.actions.services.board.card_bulk import assign_many as assign_many
from agos_core.actions.services.board.card_bulk import edit_bodies as edit_bodies
from agos_core.actions.services.board.card_chats import chat_of as chat_of
from agos_core.actions.services.board.card_chats import (
    move_card_chat_titles as move_card_chat_titles,
)
from agos_core.actions.services.board.card_detail import card as card
from agos_core.actions.services.board.card_files import attach as attach
from agos_core.actions.services.board.card_files import attachment_path as attachment_path
from agos_core.actions.services.board.card_files import attachments as attachments
from agos_core.actions.services.board.card_files import remove_attachment as remove_attachment
from agos_core.actions.services.board.card_members import COFOUNDER as COFOUNDER
from agos_core.actions.services.board.card_members import OWNER as OWNER
from agos_core.actions.services.board.card_members import latest_of as latest_of
from agos_core.actions.services.board.card_questions import OWNER_OK as OWNER_OK
from agos_core.actions.services.board.card_questions import answer as answer
from agos_core.actions.services.board.card_questions import questions as questions
from agos_core.actions.services.board.card_text import PINS_BLOCK as PINS_BLOCK
from agos_core.actions.services.board.card_text import _event_detail as _event_detail
from agos_core.actions.services.board.card_text import _question as _question
from agos_core.actions.services.board.card_text import complete_args as complete_args
from agos_core.actions.services.board.card_text import done_needs_summary as done_needs_summary
from agos_core.actions.services.board.card_text import readable_result as readable_result
from agos_core.actions.services.board.card_text import skill_pins as skill_pins
from agos_core.actions.services.board.card_text import with_criteria as with_criteria
from agos_core.actions.services.board.card_text import without_pins as without_pins
from agos_core.actions.services.board.card_writes import ACTIONS as ACTIONS
from agos_core.actions.services.board.card_writes import act as act
from agos_core.actions.services.board.card_writes import assign as assign
from agos_core.actions.services.board.card_writes import comment as comment
from agos_core.actions.services.board.card_writes import create as create
from agos_core.actions.services.board.card_writes import estimate as estimate
from agos_core.actions.services.board.kanban_db import EVENTS as EVENTS
from agos_core.actions.services.board.kanban_db import _event_actors as _event_actors
from agos_core.actions.services.board.kanban_db import _extra as _extra
from agos_core.actions.services.board.kanban_db import _stamp as _stamp
from agos_core.actions.services.board.kanban_db import done_since as done_since
from agos_core.actions.services.board.kanban_db import events as events
from agos_core.actions.services.board.kanban_db import facts as facts
from agos_core.actions.services.board.kanban_db import keyed as keyed
from agos_core.actions.services.board.kanban_db import made_in as made_in
from agos_core.actions.services.board.kanban_workflow import ARCHIVED as ARCHIVED
from agos_core.actions.services.board.kanban_workflow import BLOCKED as BLOCKED
from agos_core.actions.services.board.kanban_workflow import DISPATCH_KEY as DISPATCH_KEY
from agos_core.actions.services.board.kanban_workflow import DONE as DONE
from agos_core.actions.services.board.kanban_workflow import MANUAL as MANUAL
from agos_core.actions.services.board.kanban_workflow import STATUSES as STATUSES
from agos_core.actions.services.board.kanban_workflow import _columns as _columns
from agos_core.actions.services.board.kanban_workflow import _manual as _manual
from agos_core.actions.services.board.kanban_workflow import _workflow as _workflow
from agos_core.actions.services.board.kanban_workflow import card_actions as card_actions
from agos_core.actions.services.board.kanban_workflow import columns as columns
from agos_core.actions.services.board.kanban_workflow import dispatch_seconds as dispatch_seconds
from agos_core.context import Core

# Their old private names (callers in other services and tests still reach them).
_listed = board_list.listed
_bulk = card_bulk.bulk
_plan = card_detail.plan
_shown = card_detail.shown
_attached = card_files.attached
_creator = card_members.creator
_legacy_member = card_members.legacy_member
_members = card_members.members
_profile_of = card_members.profile_of
_shown_members = card_members.shown_members
_card = card_shape.card_of
_with_actions = card_shape.with_actions
_moved = card_writes.moved
_json = kanban_cli.answer
_board_file = kanban_db.board_file


def _cli(core: Core, workspace_id: str, *args: str) -> str:
    """`hermes kanban <args>` (actions/services/board/kanban_cli.py run)."""
    return kanban_cli.run(core, workspace_id, *args)
