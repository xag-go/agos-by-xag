"""Status cards (Step 55, Paperclip F33): a scope of the workspace and a short
summary of it written by the Co-Founder, on a schedule or on demand.

A status card is:
- its definition, AGOS's row (`status_cards`): a title, the scope (the whole
  workspace, a goal, a project, a member, or the cards matching a few words) and
  the update policy (daily, weekly, on demand). Hermes has no such notion;
- its timing: ONE Hermes cron job in the Co-Founder's own cron (`AGOS status card
  <id>`): its schedule is the card's time, Hermes's scheduler fires it, Run now is
  Hermes's own `POST /api/jobs/{id}/run`. The job is a Hermes MONITOR job
  (cron/monitor.py): its monitor script (`agos-status-<id>.py`, in the root's
  scripts folder) prints the scope's facts (each card's status, who has it, its
  comments; the goal's key results), and Hermes wakes the agent only when that
  output changed since the last run that woke it. Nothing changed = no model call.
  An on-demand card prints only its last \"refresh asked\" time, so only Refresh now
  wakes it;
- its summary: a document in the workspace folder, `status/<id>/summary.md`, each
  save a revision kept as `.revisions/summary/v<N>.md` with a CHANGES.md line
  (who, why, when), the same revision files as a card's documents
  (engine/card_docs.py). The Co-Founder writes it with its `agos_status_card` tool;
  the page shows the latest and every revision.

This module is a compatibility facade: the code lives in actions/services/board/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.board.status_defs import (
    log as log,
    FOLDER as FOLDER,
    SUMMARY as SUMMARY,
    KEY as KEY,
    CHANGES as CHANGES,
    SCOPES as SCOPES,
    POLICIES as POLICIES,
    JOB_NAME as JOB_NAME,
    SCRIPT as SCRIPT,
    MAX_SUMMARY as MAX_SUMMARY,
    DEFAULT_TIME as DEFAULT_TIME,
    DEFAULT_DAY as DEFAULT_DAY,
    PROMPT as PROMPT,
    _row as _row,
    titles as titles,
    _check as _check,
    _folder as _folder,
    scope_label as scope_label,
    _schedule as _schedule,
    _when as _when,
)
from agos_core.actions.services.board.status_summaries import (
    write_summary as write_summary,
    revision as revision,
)
from agos_core.actions.services.board.status_monitor import (
    _board as _board,
    monitor as monitor,
    read_for_agent as read_for_agent,
    tool as tool,
)
from agos_core.actions.services.board.status_jobs import (
    script_text as script_text,
    _job_of as _job_of,
    create as create,
    update as update,
    refresh as refresh,
    delete as delete,
    _shown as _shown,
    one as one,
    page as page,
)
# isort: on
