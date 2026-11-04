"""A card's review stages and its plan-first rule, driven on Hermes's board (Step 52).

The rules and where everything lives: engine/reviews.py. In short: Hermes's review
column and the card's assignee hold the card at a reviewer (the dispatcher wakes a
profile reviewer, `owner` is a name Hermes never starts: he decides from the Inbox);
the card's body block holds its policy and its marker comments say what happened.
AGOS keeps only the workspace's defaults (app_settings `review.<workspace>`).

Who moves the card:
- an agent, through its `agos_review` tool (the guard's review.py): AGOS checks the
  call here (`verdict`) and answers the one Hermes step to take; the guard takes it
  on Hermes's board with the agent's own run id (request_review, request_changes,
  complete, block, ...) and writes the marker comment, then tells AGOS it landed
  (`landed`: the owner hears when the card waits for him);
- the owner, from the Inbox / the card / a Telegram button (`owner_act`), through
  Hermes's CLI (assign, complete, reopen-review, unblock, archive, create, link);
- the guard refuses the agent's own finishing calls on a card under review rules
  (`check`: kanban_complete / kanban_request_review / kanban_request_changes /
  kanban_create while a plan waits) with the words that say what to call instead.

This module is a compatibility facade: the code lives in actions/services/board/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.board.review_rules import (
    log as log,
    SETTING as SETTING,
    OWNER as OWNER,
    CHECKED as CHECKED,
    VERDICTS as VERDICTS,
    OWNER_ACTIONS as OWNER_ACTIONS,
    PLAN_FIRST as PLAN_FIRST,
    PLAN_WAITING as PLAN_WAITING,
    SUBMIT as SUBMIT,
    REVIEWING as REVIEWING,
    NOT_REVIEWER as NOT_REVIEWER,
    STUCK as STUCK,
    IN_REVIEW as IN_REVIEW,
    OWN_RUN as OWN_RUN,
    defaults as defaults,
    save_defaults as save_defaults,
    Org as Org,
    org as org,
    reviewer_of as reviewer_of,
    label as label,
)
from agos_core.actions.services.board.review_situation import (
    Situation as Situation,
    situation as situation,
    view as view,
    chip as chip,
)
from agos_core.actions.services.board.review_verdicts import (
    check as check,
    verdict as verdict,
    decompose as decompose,
    landed as landed,
)
from agos_core.actions.services.board.review_owner import (
    _cli as _cli,
    owner_act as owner_act,
    button as button,
    set_card as set_card,
)
from agos_core.actions.services.board.review_lists import (
    board_rows as board_rows,
    inbox as inbox,
)
# isort: on
