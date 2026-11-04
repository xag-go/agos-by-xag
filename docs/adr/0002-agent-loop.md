# ADR 0002 — Agent loop: one run per task step, stable prompt, event log

- Status: superseded by [0010](0010-hermes-engine.md) — Hermes Agent provides this; kept for history
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3`, `agent/conversation_loop.py`, `agent/turn_*.py`, `agent/AGENTS.md` (read only)

## What problem does Hermes's design solve?

- **Long, open-ended conversations** (CLI, chat apps) where one session can
  run hundreds of model calls. Hermes splits each iteration into ~25 phase
  files (preflight, request assembly, API call, error handling, truncation,
  overflow, empty-response recovery, stop gates, liveness…) so each failure
  mode is handled in one place.
- **Cost.** A byte-stable system prompt keeps the provider's prompt cache
  valid; anything new mid-conversation enters as a user message or tool
  result. Only compression may break the cache.
- **Control while running**: interrupt, `/steer` (inject after the next tool
  call), queue; an iteration budget; a loop guard; a liveness watchdog.
- **Many providers with different quirks**: several transports, an error
  classifier, credential pools, automatic fallback chains.

## Do we have that problem?

- **Long runs: yes**, but bounded. Our unit of work is a **task step on the
  board**, with a plan, a model chosen by the owner and success criteria.
  Chats are open-ended, tasks are not.
- **Cost: yes**, same rule applies.
- **Control: yes** — steer/queue/interrupt are useful in chats and in a task's
  Chat tab.
- **Many providers: less.** Claude, OpenAI and Gemini first; in cli mode the
  official CLI already handles its own provider quirks.
- **Automatic model fallback: no** — the owner chooses models (ARCHITECTURE §8).

## Simpler version for us

```
Run = (workspace, task or chat, model choice, roots, tools)
  loop:
    assemble request (stable system prompt + history)
    call model ──► classify error? ─► retry with backoff | stop as Blocked
    tool calls? ─► guard (loop detector, limits) ─► execute in workspace container
    append results, write events
  until: final answer | budget | owner stop | limit
```

- **One `Run` module** with a small state machine, not 25 phase files. Each
  failure mode is a function in `runner/recovery.ts`, tested on its own.
- **Event log first.** Every run appends events (`run.started`, `token`,
  `tool.called`, `tool.result`, `plan.updated`, `comment`, `blocked`,
  `run.finished`) to SQLite. The UI, Telegram and the usage meter all read
  that log. The Hermes Web UI's hardest bugs came from streaming state with
  no single source of truth; we avoid that by design.
- **Stable system prompt** per run; the task's plan and new owner messages
  come in as user messages.
- **Busy input** (steer / queue / interrupt) as a per-workspace setting.
- **Errors**: a small classifier (rate limit, overloaded, context too long,
  auth, billing, bad request) → retry with backoff, compress, or stop the
  task as **Blocked** with an explanation. No silent model switch; an owner
  may list fallback models per workspace, and each switch is written in
  Comments.
- **Two engines behind one interface**: cli mode drives the provider's
  official CLI (tools served by our MCP broker, ARCHITECTURE §12); api mode
  runs our own loop. Both emit the same events.

## Deliberately simpler than Hermes

| Hermes                                              | Us                                            | Why                                             |
| --------------------------------------------------- | --------------------------------------------- | ----------------------------------------------- |
| ~25 turn-phase files, mixins, `AIAgent(~60 params)` | One run state machine + recovery functions    | Our runs are task-shaped; fewer modes to handle |
| Credential pools, rotation strategies               | One key per provider (api) or one login (cli) | Single owner                                    |
| Auto fallback chain, cooldowns                      | Owner-listed fallback only, reported          | Owner chooses models                            |
| Goal loops, Mixture-of-Agents, `/btw` forks         | Board tasks + sub-tasks + review step         | The board already gives structure               |
| Turn leases across processes                        | One gateway process owns runs                 | Single machine                                  |
