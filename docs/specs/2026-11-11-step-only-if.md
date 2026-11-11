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

The run script (`engine/automation_run.py`, no agent) writes, only when a step has
lines, one small file per run: `<root>/agos-automations/<automation>.runs/<run>.only-if.json`
= `{"only_if": {step: [lines]}, "values": {...}, "payloads": [...]}` (the lines are
frozen for the run; a delivery that joins a waiting run is appended). 50 newest kept.

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
