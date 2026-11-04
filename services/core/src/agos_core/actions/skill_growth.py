"""Skills that grow (Step 63): SkillClaw's evolution loop on Hermes, once a week.

- Evidence (`evidence`): what the week says about each workspace skill, read where it
  lives, read-only: the team's Hermes sessions (each member profile's state.db: an
  owner correction after an agent's answer, a tool error; the skills a session used =
  its skill_view calls), the owner's 👎 (feedback_votes, Step 49), review "Changes"
  notes (Step 52 marker comments on Hermes's board) and failed Skill Studio runs.
  Grouped by skill like SkillClaw's aggregation; what names no skill is listed apart.
- The Co-Founder's weekly Hermes cron job 'AGOS skill review' (Fridays 18:00 on the owner's clock,
  after the weekly review) runs in monitor mode: its script prints the evidence and
  Hermes wakes the agent only when that changed (`No evidence this week.` twice =
  no model call). The agent proposes a candidate per skill with agos_skill_candidate
  (never skill_manage itself).
- A candidate (`skill_candidates`) is tested in Skill Studio: each of the skill's
  saved inputs runs with the candidate's text as the revision under test, and the
  current version runs the same inputs (an earlier graded run of the current version
  is reused). `judge`: every candidate run passes AND its mean score is at least the
  current version's -> it becomes the next version through Hermes's skill_manage
  ('evolved from evidence', with its evidence refs); else it is discarded with a
  note. A skill with no tests takes 1-2 from the evidence the agent gives.
- When the week's candidates are all decided, ONE Inbox note 'Skills improved' lists
  them (Skill Studio shows each diff and Restore), and when a skill changed, Hermes's
  own curator gets one pass (`hermes curator run --background`: its consolidation
  merges overlaps, its ledger records it).
Nothing leaves the workspace: each reads only its own profiles, board and rows.

This module is a compatibility facade: the code lives in actions/services/library/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.actions.services.library.growth_evidence import (
    log as log,
    WINDOW_DAYS as WINDOW_DAYS,
    NO_SKILL as NO_SKILL,
    NOTHING as NOTHING,
    MAX_LINES_PER_SKILL as MAX_LINES_PER_SKILL,
    MAX_TESTS as MAX_TESTS,
    NOTE_KIND as NOTE_KIND,
    JOB_NAME as JOB_NAME,
    JOB_TIME as JOB_TIME,
    JOB_DAY as JOB_DAY,
    SCRIPT as SCRIPT,
    OFF_REASON as OFF_REASON,
    CORRECTION as CORRECTION,
    PROMPT as PROMPT,
    Evidence as Evidence,
    session_evidence as session_evidence,
    _sessions as _sessions,
    _board as _board,
    editable_skills as editable_skills,
    gather as gather,
    render as render,
    evidence as evidence,
)
from agos_core.actions.services.library.growth_job import (
    script_text as script_text,
    job as job,
    set_job as set_job,
    _jobs_done as _jobs_done,
    ensure_job as ensure_job,
)
from agos_core.actions.services.library.growth_candidates import (
    batch_of as batch_of,
    candidate as candidate,
    judge as judge,
    advance as advance,
    _close_batch as _close_batch,
    _curator_soon as _curator_soon,
    candidates as candidates,
    card_moved as card_moved,
    sweep as sweep,
)
# isort: on
