"""Automations: AGOS's row (who does it, team steps, "check with me first", the
link to the job), a job in the workspace's own Hermes cron, which holds the timing:
schedule, on/off, next and last run, and the runs of a one-agent automation, and
its webhook: a route of the workspace's Hermes webhook platform (actions/hooks.py).
AGOS shows those live from Hermes and writes changes only into it.

The instructions have one copy. A one-agent automation on a schedule: its Hermes
job's prompt (what `hermes cron edit --prompt` changes; engine/cron.py
instructions_of reads them back). Its readable file in the workspace exists only
while Hermes doesn't hold them yet (the owner's request Hermes refused, kept like
the schedule) and goes once the job has them. A Kanban automation (team steps,
"check with me first") or a webhook-only one has no Hermes job to hold them: its
file is their one copy.

Who does a one-agent automation is the profile whose Hermes cron holds its job:
a member's own profile (`<root>/profiles/a-<agent>`, what `hermes -p a-<agent>
cron` writes), or the Co-Founder's (the root). The root's one gateway ticks every
profile's cron (Hermes's multiplexed scheduler), and Hermes runs the job as that
profile, with its own SOUL.md (its role and the workspace's rules), memory and
skills. AGOS pastes no role text into the prompt.

A team automation's job runs a small script (no agent, no tokens) with which
Hermes puts its steps on the Kanban itself (automation_cards: AGOS writes the
script's plan and reads the runs from the board). The
agents' own jobs (their cronjob tool) are listed in Automations → Scheduled by
agents. The profile's Hermes gateway must be running for the scheduler to tick,
so an enabled automation keeps it on.

Where each value comes from (see `_view`):
- the job is in Hermes: schedule, on/off, next and last run are Hermes's;
- Hermes refused the owner's change (sync_error): his request (DB), shown with the problem;
- the job is gone from Hermes: no schedule, shown as needing a re-save;
- no job (a webhook only): on/off is its Hermes route's;
- who does it: the profile whose cron holds the job; the row's agent is the owner's
  pick only while Hermes doesn't hold it there (the agent is off, so the Co-Founder
  does it; a new agent's profile is still being made; no one-agent job).

The code lives by responsibility in this package: instructions.py (the readable
file), cron.py (reading Hermes cron, the view), jobs.py (writing jobs), run_history.py,
owner.py (the owner's actions), sync_loop.py (the background loop). This module
only re-exports what other modules use.
"""

from agos_core.actions.services.automation.check import review_form as review_form
from agos_core.actions.services.automation.cron import COFOUNDER as COFOUNDER
from agos_core.actions.services.automation.cron import MISSING as MISSING
from agos_core.actions.services.automation.cron import TICK_SECONDS as TICK_SECONDS
from agos_core.actions.services.automation.cron import Jobs as Jobs
from agos_core.actions.services.automation.cron import Source as Source
from agos_core.actions.services.automation.cron import cron_bridge as cron_bridge
from agos_core.actions.services.automation.cron import describe_schedule as describe_schedule
from agos_core.actions.services.automation.cron import get as get
from agos_core.actions.services.automation.cron import hermes_jobs as hermes_jobs
from agos_core.actions.services.automation.cron import home_of as home_of
from agos_core.actions.services.automation.cron import homes as homes
from agos_core.actions.services.automation.cron import list_all as list_all
from agos_core.actions.services.automation.cron import schedule_problem as schedule_problem
from agos_core.actions.services.automation.instructions import (
    read_instructions as read_instructions,
)
from agos_core.actions.services.automation.jobs import check_who as check_who
from agos_core.actions.services.automation.jobs import gone_notice as gone_notice
from agos_core.actions.services.automation.jobs import park as park
from agos_core.actions.services.automation.jobs import pinned_skills as pinned_skills
from agos_core.actions.services.automation.jobs import resync_workspace as resync_workspace
from agos_core.actions.services.automation.jobs import runner as runner
from agos_core.actions.services.automation.jobs import sync_job as sync_job
from agos_core.actions.services.automation.jobs import team_notice as team_notice
from agos_core.actions.services.automation.jobs import who_label as who_label
from agos_core.actions.services.automation.owner import POLICIES as POLICIES
from agos_core.actions.services.automation.owner import delete as delete
from agos_core.actions.services.automation.owner import list_revisions as list_revisions
from agos_core.actions.services.automation.owner import restore as restore
from agos_core.actions.services.automation.owner import run_now as run_now
from agos_core.actions.services.automation.owner import save as save
from agos_core.actions.services.automation.owner import toggle as toggle
from agos_core.actions.services.automation.run_history import proposed_cards as proposed_cards
from agos_core.actions.services.automation.run_history import runs as runs
from agos_core.actions.services.automation.sync_loop import RETRY_FIRST_S as RETRY_FIRST_S
from agos_core.actions.services.automation.sync_loop import RETRY_MAX_S as RETRY_MAX_S
from agos_core.actions.services.automation.sync_loop import TOOLS_LOOK_S as TOOLS_LOOK_S
from agos_core.actions.services.automation.sync_loop import hand_over as hand_over
from agos_core.actions.services.automation.sync_loop import keep_in_step as keep_in_step
from agos_core.actions.services.automation.sync_loop import run_forever as run_forever
from agos_core.actions.services.automation.sync_loop import sync_agent_jobs as sync_agent_jobs
