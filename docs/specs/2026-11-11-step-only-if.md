# Spec: "Only if" per automation step (lane auto-b)

Date: 2026-11-11. Decision record: `docs/adr/0029-step-only-if.md`.

## Problem

Live workspace content-creation, automation "Inspiration Watcher" (webhook from the
Inspiration Google Sheet, payload `{"event": "inspiration.link_added", "sheet":
"<tab>", "row": N, "links": [...]}`). Steps today (live, read 2026-11-11):
s2 @brand-voice-developer (ideas, scripts), s4 @video-editor (editing), both waiting
on nothing, and s3 Co-Founder waiting on [s2, s4]. Each step's agent starts, runs
`/workspace/tools/media_intake.py --kinds ...` (which pulls the Sheet rows, then runs
the gate `inspiration_gate.py`, last line `GATE: AH|LA`) and ends with SKIP when its
tab had no new link. The agent's start already spends tokens: an Editing link
starts brand-voice-developer for nothing.

## What the owner gets

Each step can have **Only if** lines. No line = the step always runs (exactly as
today). With lines, the step starts its agent only when every line holds; otherwise
its card is closed at once with the result `agos-skipped: <plain reason>` and the
agent never calls the model (0 tokens).

Two kinds of line:

1. **Match line** on the run's values, the same shape and tests as the webhook's
   "Only if" lines: `{"field": "payload.sheet", "op": "is", "values":
["Editing-Inspiration"]}`. `field` = `payload.<path>` (the webhook delivery) or a
   variable name of the automation. `op` = `is` (one of) | `is_not` | `contains` |
   `not_contains`; compared trimmed, case-insensitive.
   - A run with no delivery (schedule, Run now): `payload.` lines hold (nothing to
     judge: the step runs as today). An unknown variable reads as empty.
   - A webhook run that took more deliveries before it began (a burst): the step
     runs when ANY of its deliveries makes all match lines hold.
2. **Check line**: `{"check": "/workspace/tools/inspiration_gate.py"}` — a workspace
   script, run in the step agent's own sandbox (Hermes's terminal, the member's
   container, `/workspace` as working folder), no agent, no model. Its LAST non-empty
   output line answers: a word `YES` or `AH` = yes, `NO` or `LA` = no
   (`GATE: AH` / `GATE: LA` work as they are). Exit code non-zero, no answer word,
   a time-out (20 s) or any error = unsure = the step runs ("when in doubt it runs":
   it may cost a run, it never loses work). Scripts must sit inside `/workspace`
   (no `..`, no shell characters); `.py` runs with `python3`.

Match lines are checked first (free); check lines only when they all hold.

## When it is checked

At the moment the step would start: Hermes's dispatcher has released the card (its
parents are done) and spawned its worker; before that worker's first model call,
the agos-guard plugin's `pre_llm_call` hook reads the step's lines and the run's
values, decides, and on "no" completes the card itself (Hermes's own
`complete_task`, the worker's own run id) and vetoes the turn (Hermes's
`{"action": "block"}`: no model request, no compaction, no title, no memory
prefetch). Data written by an earlier step is there because the check runs after
the parents are done.

Two small files beside the board, in the workspace's engine root (no sandbox mounts
it; `/workspace` is the files folder):

- on every save, AGOS writes the automation's lines:
  `<root>/agos-automations/<automation>.lines.json` = `{step: [lines]}`
  (`engine/step_conditions.py keep_saved`; no line = no file). The plugin takes a
  step's lines from here only, and checks each line again by the save rules;
- the run script (`engine/automation_run.py`, no agent) writes, only when a step has
  lines, one file per run with the run's values only:
  `<root>/agos-automations/<automation>.runs/<run>.only-if.json` = `{"values": {...},
"payloads": [...]}` (a delivery that joins a waiting run is appended). 50 newest
  kept, never one of a run still on the board.

The lines in force are the saved ones at the moment the step starts (an edit during
a run applies to its steps that haven't started).

## Safety rules (review of lane b, fixed with a failing-first test each:

`services/core/tests/test_step_only_if_safety.py`)

- **What runs comes only from AGOS (M1).** A card key is read only when its parts
  are exactly what the run script makes (automation digits, run
  `YYYYMMDDTHHMMSSffffffZ`, source manual/schedule/webhook, a step key); the files
  are read only when they sit right inside their folder (no link, no `..`, no
  absolute path); the lines come from the saved file, never from the run's file;
  a line that breaks the save rules is never run (the step runs). An agent can set
  a card's key (`kanban_create`) and write `/workspace`, but neither reaches these.
- **A burst loses nothing (M2).** Deliveries run side by side: the run script
  writes the run file and the deliveries log under a lock, each write through its
  own temp file; a delivery joining a run that began meanwhile starts its own run;
  the plugin reads under a shared lock. A join that can't write drops the run's
  values (its steps then run) and the delivery is still commented and noted.
- **Decided once per card (M3).** Only a card's first attempt checks. A later
  attempt (a retry after a crash or a time-out, an unblock, review rework) sees an
  earlier run of the card in Hermes's own run history and runs, without running
  the check again (a check script with state, like `inspiration_gate.py`, would
  answer differently the second time). An attempt whose worker never started
  (`spawn_failed`) doesn't count.
- **Unsure = run (L2, L3, L4).** A delivery too big to keep is kept as "can't
  judge" (its payload lines hold), never as a key a sender could send; a run whose
  values can't be written still starts its cards (its steps run); pruning never
  removes a run's file while that run has an open card.
- **One log line per check (L6).** `AGOS: Only if check of card <id> ran <script>
(exit <code>): yes|no|unsure` on the guard's logger (the worker's log).

## Decisions

- **Late close and the old-Hermes exit (L1): keep, bounded.** Hermes waits for a
  plugin hook up to `plugins.hook_callback_timeout` (the owner's "A stuck plugin
  step", AGOS default 600 s). The plugin closes a card only within that wait minus
  5 s (never later than 25 s after the hook started); a close that lands later
  still stands (the card is done, Hermes refuses the worker's own result) but the
  worker is never ended then, since it may already be working. On a Hermes without
  the veto (live's), ending the worker right after a timely close stays: the card
  is done, so its worker has nothing left to do and would only spend tokens.
- **A Co-Founder change keeps what it doesn't name (L5): kept.** Before this lane,
  an `update_automation` step without `waits_on` or `kind` reset them to `[]` /
  `"work"`. Now it keeps the old values, like every other step field: the base
  rule is that a Co-Founder update never wipes what it doesn't name. Pinned by
  `test_a_cofounder_change_keeps_a_steps_kind_and_waits_it_does_not_name`.

## Never blocks the chain

A skipped card is DONE, so Hermes releases the cards waiting on it. A step whose
work parents were all skipped still runs (it may need to report) unless it has its
own lines. A skipped last card wakes nobody (like "WALO").

## Runs (lane c)

Exact marker: the card's result and summary are `agos-skipped: <plain reason>`,
e.g. `agos-skipped: Only if sheet is one of Ideas-Inspiration, Scripts-Inspiration
(this run: Editing-Inspiration)` or `agos-skipped: /workspace/tools/x.py said LA`.

## Save rules (owner and Co-Founder alike: `engine/team_steps.parse_plan`)

- `only_if` = a list (max 20 lines); each line is a match line (`field`, `op`,
  `values`; optional nothing else) or a check line (`check` only). Any other key,
  an unknown `op`, an empty `values`, a bad field, or a check outside `/workspace`
  is refused with a plain message naming the step and the line.
- Approval steps can't have lines (they wait for the owner).
- Undo: the steps (lines included) are in the automation's revisions as before.

## Co-Founder parity

create_automation / update_automation steps accept `only_if` (same lines); the
Co-Founder's help text says how. Same check, same Undo (revisions).

## Owner UI

Step editor (Who does it → The team): per step an "Only if" section with the same
look as the webhook's Only-if lines (field, test, values, Remove; "+ Add a line";
"+ Add a check script"). Empty = "No line: this step always runs."

## Check (what he will see)

- Editing link → brand-voice-developer's card closes `agos-skipped: ...` with no
  model call (0 tokens); video-editor runs; Co-Founder runs last.
- Ideas link → video-editor's card skipped; brand-voice-developer runs.
- Daily Ideas (no lines): runs exactly as before (existing tests green).

## Not in this lane

"Done by" display (lane a), Runs/cost display (lane c), save-preview (lane d).
