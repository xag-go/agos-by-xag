# ADR 0029: "Only if" per automation step, checked before the step's first model call

Date: 2026-11-11. Status: accepted (built on `auto/b`). Spec:
`docs/specs/2026-11-11-step-only-if.md`.

## The problem

A team automation puts one Hermes Kanban card per step on the board (the run script
`engine/automation_run.py`, no agent); Hermes's dispatcher starts each card once
its parents are done. A step that has nothing to do in a run still starts its
agent, which reads its brief, runs a gate script and answers "nothing": every such
start costs a model call. Live, "Inspiration Watcher" (content-creation) starts
brand-voice-developer for every Editing-Inspiration link and video-editor for every
Ideas/Scripts link, only to end with SKIP.

The decision needs data that may exist only once earlier steps are done (an
earlier step writes the record files), so it can't be taken when the run's cards
are made; it must be taken when the step would start.

## Options

1. **Decide in the run script, when the cards are made.** Free, but blind to what
   earlier steps write, and a delivery that joins a waiting run would come too late.
2. **A no-agent "gate card" before each conditional step.** Hermes's Kanban has no
   card that runs a script by itself; AGOS would have to run it (a second engine).
3. **Hold the card unassigned and assign it from the dispatcher's tick hook**
   (`on_kanban_dispatch_tick`). Promotion and spawn happen in the same tick, so a
   held card needs AGOS to re-implement "parents done" and costs a tick of delay;
   unassigned ready cards also collide with `kanban.default_assignee`.
4. **Veto the worker's first model call** (Hermes's `pre_llm_call` hook, `{"action":
"block"}`). Hermes has started the card (parents done, the dispatcher's own
   rules), the worker exists but has made no model request; Hermes's veto skips
   the request, the turn-start compaction, the title and the memory prefetch
   (`agent/turn_context.py`). The plugin closes the card itself with Hermes's
   `complete_task` under the worker's own run id.

## Decision

Option 4. Hermes stays the engine: its dispatcher decides when a step starts, its
Kanban releases the steps waiting on a skipped (done) card, its terminal runs a
check script in the step agent's own sandbox, its hook vetoes the call. AGOS adds:

- the lines on the step (`engine/step_conditions.py`, checked on save for the
  owner's page and the Co-Founder alike via `team_steps.parse_plan`);
- one file per run beside the board, written by the run script before the run's
  first card: `<root>/agos-automations/<automation>.runs/<run>.only-if.json` = the run's
  lines (frozen), values and deliveries (a delivery that joins a waiting run is
  appended). No line in the plan = no file: an automation without lines runs
  exactly as before;
- `hermes_plugin/agos_guard/step_gate.py`, registered on `pre_llm_call`: only a
  Kanban worker's own first turn (`HERMES_KANBAN_TASK`, `is_first_turn`, no parent
  session) of a card whose idempotency key is an automation step with lines.

The card's result and summary are exactly `agos-skipped: <plain reason>` (the
contract with Runs, lane auto-c). A skipped last card wakes nobody (like "WALO").

### Older Hermes (live runs 0.22.2 today)

The veto (`{"action": "block"}` from `pre_llm_call`) came with a newer Hermes; 0.22.2
ignores the answer and calls the model. There the plugin, once the card is done,
ends the card's own worker process (`os._exit(0)`, after Hermes's `cleanup_vm` of
the sandbox a check line started). A Kanban worker is its own `hermes -p <profile>
chat -q` process (H: hermes_cli/kanban_db_dispatch.py _default_spawn), its first
turn has made no model request at that point (turn-start compaction has nothing to
compact on a first turn; titling and memory prefetch come after the hook), and the
dispatcher reads a done card's exited worker as clean. The plugin tells the two
apart by Hermes's own marker (`agent.turn_context.PRE_LLM_BLOCK_EXIT_REASON`); the
fallback goes away by itself at the Hermes upgrade.

## Rules that keep it safe

- When in doubt the step runs: no run file, unreadable file, a check that fails,
  times out, or gives no YES/AH/NO/LA word on its last line, a card Hermes won't
  complete (another run), any error in the hook.
- Hermes bounds `pre_llm_call` (30 s default) and abandons a slower callback: a
  check gets 18 s, and the card is never closed after 25 s, so an abandoned check
  can't close a card whose agent already works.
- A check runs through Hermes's terminal of the worker itself (the member's own
  sandbox, `/workspace`), never on the host; the path must be inside
  `/workspace`, no shell characters (refused on save).
- Match lines are free and checked first; a run with no delivery can't judge
  `payload.` lines (they hold); a run with several deliveries runs the step when
  any of them makes all its lines hold.

## Costs

A skipped step still spawns its worker process (seconds of CPU, no tokens): Hermes
has no pre-spawn veto. If Hermes adds one (a `kanban_task_claimed` hook whose
answer can hold a card), the check moves there unchanged.
