# Check an automation before it is saved (lane auto-d)

Owner standing go: build without waiting. Private-only: not decided here (the integrator asks).

## What the owner gets

- **Save** in the automation dialog first asks the core. If there are problems, a dialog
  "Fix this before saving" lists them all (Back to the form). If not, a dialog
  "This is how it will run" shows the plain preview and any warnings, with **Save** and **Back**.
  Same look as the app's other dialogs (`useAsk`). Nothing is written until Save.
- The Co-Founder gets the same words: a create / update with problems is refused with the whole
  list (before any card waits for the owner); a saved one answers with a `report` of how it
  will run; `check_automation` is a dry run (nothing saved).

## Rules (engine/automation_check.py, pure)

Problems (block the save, all returned at once, each names its step by its title):
no name; no instructions; nothing starts it (no schedule, no webhook); schedule refused by the
scheduler; unreadable / repeated / unusable step key; empty step title; unknown step kind; agent
not in the team (never hired or removed); review that names no step, itself, a missing step or a
non-work step; wait on a step that does not exist or on itself; a circle (the steps named);
a step that can never start (it waits on a circle); every step an approval (nobody does any
work); a `{variable}` used in a step's text (or the instructions of a one-agent automation) that
is not defined in Variables.

Warnings (never block): an agent that is turned off (the Co-Founder does the step); an approval
that names an agent (you approve it); a work step whose result no later step uses; a step with
nothing to wait for that is not first (starts with the first step, not after the step above);
more than 8 steps one after another; webhook delivery data used while the webhook is off.

## Run order mirrored (engine/automation_run.py `start`)

Steps become cards in list order; a card waits on the cards of the steps it waits on that already
exist (earlier in the list). A step with no such parent starts with the first steps (it waits on the
last run's last cards). Level = 1 + deepest earlier parent. The preview groups by level, so
two branches off one step read "A and B work at the same time". To make that the real behaviour
for a plan written out of order, every save stores the steps in a stable order where each step
comes after the ones it waits on (`ordered`, used by `check_who`).

## Lane contact points

- Lane b's optional `only_if` on a step is read defensively (`step.get("only_if")`, text or
  `{text|condition|when}`) and shown as ", only if <condition>" on that step's line. It also needs
  `only_if` in `check_who`'s step dict once lane b lands (merge point: actions/services/automation/jobs.py).
- Lane a owns `step-levels.ts`; the Python twin of its level rule lives only in the check module.

## Where

- Core: `engine/automation_check.py`, `actions/services/automation/check.py` (the service),
  `owner.save` (gate; `unchecked=True` only for Undo), `api/automations.py` `POST .../automations/check`,
  `ops/specs/automation.py` `check_automation` (read, once), `cofounder/automation_kinds.py`
  (`new_automation`, `changed_automation`, `precheck`, `how_it_runs`, `dry_run`),
  `cofounder/agent_tools.py` (precheck before a card is made).
- Web: `features/setup/actions.ts` (`checkAutomation`), `automation-modal.tsx`, `shared/ui/confirm.tsx`
  (`cancelLabel`, null = no Cancel).
