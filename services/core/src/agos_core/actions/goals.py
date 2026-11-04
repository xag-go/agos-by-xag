"""The workspace's plan (Step 51 goals, Step 53 Vision): AGOS's rows, carried to the
agents through Hermes's own prompt (each profile's SOUL.md, one marked section) and
linked to Hermes's cards by their bodies ("## Goal" line, engine/goals.py).

- The Vision (sentence, why, strategy) is the owner's: he writes it on the Vision
  page; an agent may only suggest a change (a proposal he approves).
- Goals (with key results) and projects: the owner edits them on the Vision page;
  the Co-Founder proposes them (its `agos_goals` tool, or `agos_propose` kind
  'goal') and the owner approves in his Inbox, editing the numbers first if he
  wants (actions/proposals.py kind 'goal' calls `apply_change`).
- Every change writes the plan section into the Co-Founder's SOUL.md and each
  member's (its own goals and projects first): the next conversation or run reads it.
- The rollup (done / open / blocked per row, progress) is one read of Hermes's board.

This module is a compatibility facade: the code lives in actions/services/vision/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.vision.plan_rows import (
    log as log,
    GOALS_MAX as GOALS_MAX,
    PROJECTS_MAX as PROJECTS_MAX,
    RESULTS_MAX as RESULTS_MAX,
    _goal as _goal,
    _result as _result,
    rows as rows,
    results as results,
    top as top,
    _one as _one,
    _one_result as _one_result,
    prompt_for as prompt_for,
    refresh as refresh,
)
from agos_core.actions.services.vision.plan_board import (
    board_tasks as board_tasks,
    board_cards as board_cards,
    rollup as rollup,
    view as view,
    status_text as status_text,
    card_line as card_line,
    set_card_goal as set_card_goal,
)
from agos_core.actions.services.vision.plan_edits import (
    _owner as _owner,
    set_vision as set_vision,
    add_goal as add_goal,
    add_project as add_project,
    update_item as update_item,
    delete_item as delete_item,
    add_result as add_result,
    update_result as update_result,
    delete_result as delete_result,
    member_left as member_left,
    note_owner_change as note_owner_change,
)
from agos_core.actions.services.vision.plan_changes import (
    check_change as check_change,
    apply_change as apply_change,
)
# isort: on
