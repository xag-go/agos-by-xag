"""The Co-Founder's team-design skill (Step 51): how it grows the team against the
workspace goal. AGOS's own skill, in the background: it lives in the workspace's
skill folder like any other (its root's skills/agos-library/team-design, written by
Hermes's skill_manage through actions/workspace_skills.py), so the Co-Founder loads
it from its own skill index, but the owner never sees it (workspace_skills.hidden
keeps it off the Skills page, the pickers, the counts and the exports) and never
edits it. AGOS owns its text: at every start a copy that differs from the shipped
text (an older AGOS version, a Co-Founder's edit) is written back to it, through
Hermes, as a version labelled 'agos'. Its rules are also held at the door
(actions/proposals.py check_new): a hire without a why, without the goal it serves
(while one is open), asking for a skill the workspace lacks, without its whole kit or
without its whole model is refused.
"""

from __future__ import annotations

import threading

from agos_core.context import Core

NAME = "team-design"
TITLE = "Team design"
DESCRIPTION = "Use when proposing a hire or changing who reports to whom."

BODY = """\
# Team design: grow the team against the goal

Read the workspace goal and its sub-goals first (your SOUL.md, or agos_goals with
action status). A team exists to move that goal; every change to it says how.

## Before any hire
1. Name the exact gap: which sub-goal (or part of the goal) has no one who can do
   the work, and what work exactly. "We need more help" is not a gap.
2. Check the team: read each member's role (your view of the team). If a member can
   cover the gap with a clear change to its role, propose that change instead.
3. Prefer moving reports_to over hiring: a member put under the right lead often
   closes the gap with no new agent (the owner moves it in Hierarchy, or you ask).
4. Start small: one hire at a time, the smallest team that moves the goal. Add the
   next hire only when the work shows the gap again.

## The hire itself (hire_agent / agos_propose kind 'hire')
Every new agent is a hire, in every autonomy mode: it becomes a card in the owner's
Inbox, he sees and edits its kit and model, and only his Approve creates it. There is
no other way to a new agent (create_agent makes none). A hire missing any line below
is refused with exactly what is missing: fix it and send it again.
- One clear role: what it does, what it does NOT do, who it hands work to.
- A real job title (the one a company would write), lowercase-with-dashes name.
- reports_to: the lead it works for (leave it out = you, the Co-Founder). Never a
  member that reports to it: AGOS refuses a loop.
- why (required: AGOS refuses a hire without it): the gap against the goal, the
  sub-goal it serves (#id), and why no member on the team covers it.
- goal_id: the number of the sub-goal (or project) it serves. While the workspace
  has an open one, AGOS refuses a hire without it.
- A sub-goal it will own, if one fits: say it, and propose it with agos_goals.
- model (required): size it to the work, on the workspace's own provider (a big
  model often does small work). Small, repetitive work (fact checks, formatting,
  captions): the small model, effort low (Claude: haiku). Everyday writing and
  editing: the middle one, medium (sonnet). Deep work (strategy, long scripts, code):
  the big one, high (opus). Give `"model": {"model": <the exact id of one version
  Hermes's catalog lists for the workspace's provider>, "effort": "low" | "medium" |
  "high"}` and, in its OWN field, `"model_why": "small repetitive work -> Haiku, low"`.
  A family alone ("sonnet"), a model without its effort, or a why or any other words
  inside model are refused; AGOS lists the versions it can use. The owner may change
  it before Approve.

## Before you send the hire
Check each line; fix the proposal until all of them hold.
- role is a short paragraph, not a generic manual: who it is, what it owns, what it
  does NOT do, and who it hands its work to.
- Same style as the team: read how the existing members' roles are written and
  write this one the same way (length, tone, the same words for the same things).
- skills: only the ones this role needs, and only skills this workspace's library
  has (AGOS refuses any other: install it first, or leave it out).
- Wider reach: a skill that gives browser, terminal, network, files outside its
  own folder or secrets gets one line in why saying what the role needs it for.
- No heartbeat or routines unless the role has scheduled work; say what and when.
- No secrets in any text (keys, passwords, tokens): the owner connects those himself.
- goal_id names the sub-goal it serves; source_card is the card the need came from,
  when there is one.
- After the owner approves, you review the hire in 7 days: AGOS schedules it.

## The kit: everything it needs to do the work well
Every hire carries its WHOLE kit (the `kit` field): tools, skills, docs and the
onboarding test may not be empty, and at least one of its skills must be in this
workspace's library (a hire without it is refused). Think as the member on its first
day: what would it need to do this job as well as possible?
- tools: each service or account the work touches (Instagram, Google Drive,
  CapCut...), with why. AGOS maps each to Hermes's connector when one exists; for an
  API with no connector give `key` (the name its key will have in Settings → Keys).
- skills: the methods the job needs. `library` = this workspace has it; `find` = a
  skill to look for (Hermes's skills hub, the Brain); `write` = one you will write.
- docs: the files it must follow and good examples to copy the style of
  (`path` of a workspace file, or `url`; `kind` doc or example). Read the workspace's
  files first and name the real ones; a file that doesn't exist yet is still worth
  listing: the owner is asked for it.
- team: `works_with` (the members it hands work to or gets work from) and
  `project` (what the team works on, in words).
- onboarding: ONE small task of real work in its role ("edit this 30 s clip in our
  style", "write 3 hooks for this week's video") and the criteria a good result
  shows (2 to 5 lines). AGOS runs it once the member is ready and grades it.
After the approve, AGOS gives what it can and shows the owner a Readiness checklist;
what is missing comes back to you on ONE card ('Make @<member> ready'): resolve
each item as that card says, and give the member no other work until it is ready.

## A kit for a member already on the team
A member hired before kits existed has none, and some kits miss a part (the owner
sees "No kit yet" or "Kit incomplete" on Hierarchy). When asked for one (a 'Suggest
a kit for @<member>' card), read the member as it is: its role, the skills it loads,
its model, its latest cards and the files it uses. Then send ONE agos_propose, kind
"kit": member, kit (whole, as above; keep what its kit has that still fits), model
and model_why (sized to the work its cards show), why (what its role and work show
it needs), source_card. Change nothing of the member yourself: the owner's Approve
writes it, and its Readiness runs as a new hire's.

## Leads
- A lead is worth it when it reviews and routes the work of 3 or more members on
  the same sub-goal; under that, members report to you directly.
- A paused or stuck lead stalls its whole team (the owner sees it in his Inbox):
  when a lead stops, move its reports or unblock it first.
"""


def text() -> str:
    from agos_core.engine import library as lib

    return lib.skill_template(NAME, DESCRIPTION, BODY)


_lock = threading.Lock()
_done: set[str] = set()


def ensure(core: Core, workspace_id: str) -> bool:
    """The skill in the workspace, at the shipped text (True when it was made or
    rewritten now). A copy whose text differs from this AGOS's is written back to
    it (Hermes's skill_manage, a recorded version); one already equal is left alone.
    Once per core start. Never raises: a hire is never stopped because the skill
    wasn't written."""
    from agos_core.actions import workspace_skills

    return workspace_skills.ensure_shipped(
        core, workspace_id, NAME, TITLE, text(), done=_done, lock=_lock
    )


def ensure_all(core: Core) -> int:
    """At start (live): every workspace that has a root gets it, at the shipped text."""
    from agos_core.db import workspaces as workspaces_repo

    return sum(ensure(core, w.id) for w in workspaces_repo.list_workspaces(core.db))
