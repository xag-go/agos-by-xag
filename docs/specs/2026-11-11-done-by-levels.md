# "Done by" as parallel levels (lane auto-a)

Every "Done by" summary follows each step's `waits_on`, not the list order. Display only; runs are unchanged.

- Levels = Kahn layering mirroring engine/automation_run.py: a step with no known waits starts with level 0 (it has no in-run parent); a review also waits on the step it reviews (team_steps.py); unknown keys ignored; a cycle's leftovers form a last level.
- Web: `features/setup/step-levels.ts` (`stepLevels`, `doneBy`), used by the Automations list / page. Same level = `( @a + @b )`, tooltip "These work at the same time". A straight chain renders as before.
- Core: `engine/step_levels.py` (`step_levels`, `done_by`) feeds the Co-Founder's `team: …` line.
