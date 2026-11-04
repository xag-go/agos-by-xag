"""An agent's proposal to the owner (a hire, a change to its own instructions, a
plan), decided from AGOS: Approve / Revise / Reject.

The proposal itself is a Hermes Kanban card (engine/proposals.py says its shape):
the agent creates it and blocks it for the owner; Hermes's kanban_task_blocked
hook (through the agos-guard plugin) tells AGOS, which reads the card's body from
the board and records the ask (actions/kanban_asks.py keeps the row: its kind,
payload, round). The owner's decision is written on the card as a comment with a
stable marker (Hermes's `kanban comment`), then acted on:
- approve a hire: the member is created through the team's own code (its Hermes
  profile, its DM and, when asked, its Telegram topic), the card is completed;
- approve an instructions change: a consent token goes into the agent's profile
  home (the guard lets exactly that write through once), the card is unblocked;
- approve a plan: unblocked with "approved";
- revise: the note goes on the card, the card is unblocked (the agent proposes
  again on a NEW card: Hermes routes a second needs_input block of the same card
  to triage, hermes_cli/kanban_db.py BLOCK_RECURRENCE_LIMIT);
- reject: completed with the result "rejected".
Every decision is idempotent: the same decision again is a no-op (read from the
row, and from the card's own comments when the row was never updated), another
terminal decision after one is a 409. Undo of an approved hire removes the member.

This module is a compatibility facade: the code lives in actions/services/proposals/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.proposals.proposal_states import (
    log as log,
    _json as _json,
    Choice as Choice,
    STATUS_OF as STATUS_OF,
    CHOICE_OF as CHOICE_OF,
    FAILED as FAILED,
    TERMINAL as TERMINAL,
    CONSENT_FILE as CONSENT_FILE,
    KEEP_TOKENS as KEEP_TOKENS,
    REFUSED as REFUSED,
    member_of as member_of,
)
from agos_core.actions.services.proposals.hire_checks import (
    check_new as check_new,
    hire_lead_problems as hire_lead_problems,
    OPEN_GOALS as OPEN_GOALS,
    hire_goal_problems as hire_goal_problems,
    _skill_here as _skill_here,
    hire_skill_problems as hire_skill_problems,
)
from agos_core.actions.services.proposals.intake import (
    arrived as arrived,
    record as record,
    _tell as _tell,
    propose as propose,
)
from agos_core.actions.services.proposals.inbox_view import ask_view as ask_view
from agos_core.actions.services.proposals.inbox_view import waiting as waiting
from agos_core.actions.services.proposals.inbox_view import count as count
from agos_core.actions.services.proposals.inbox_view import ask_row as ask_row
from agos_core.actions.services.proposals.hiring import (
    hire as hire,
    own_hire as own_hire,
    unhire as unhire,
    consent as consent,
)
from agos_core.actions.services.proposals.decisions import (
    edited as edited,
    decide as decide,
    undo as undo,
)
# isort: on
