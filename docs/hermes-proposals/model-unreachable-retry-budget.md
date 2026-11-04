# Proposal for Hermes: end a turn when the model stays unreachable

Found by AGOS's failure tests (`services/core/tests/failure/test_recovery.py`,
[resilience-tests.md](../guides/resilience-tests.md#found-by-these-tests)), read
against Hermes `d923a5eb48` (2026-10-15).

## What happens

With the model's endpoint down (connection refused, timeouts), one turn retries
for 20 minutes or more, and the user sees "Thinking…" the whole time. Nothing
tells the chat that the model is down, and the turn does not end with an error.

The retry stages in Hermes's code multiply:

1. `agent.api_max_retries` attempts (AGOS sets 10, so a short provider hiccup is
   waited out), with backoff (`agent/turn_api_error.py`).
2. When those are spent on a transient transport error, the primary client is
   rebuilt once ("one last primary attempt", `try_recover_primary_transport`).
   `retry_count` goes back to 0, so this is a **full new block** of
   `api_max_retries` attempts, not one attempt.
3. With no fallback provider configured, the auto-recovery ladder
   (`agent/turn_recovery_autorecover.py`, `agent.auto_recovery_cycles`, default 5)
   parks the turn for 15/30/60/60/60 s. Each cycle sets `retry_count = 0` again,
   so each cycle is another full block of `api_max_retries` attempts.

Worst case, that is `api_max_retries × (2 + auto_recovery_cycles)` attempts: 70
with AGOS's settings, each with its own backoff. To the user, that looks like a
turn that never ends. AGOS only closes it after its stale-turn limit of 3 hours
(`gateway_platform.STALE_AFTER_S`).

## Proposal

1. **A wall-clock budget for one turn's retries.** For example,
   `agent.retry_budget_seconds` (default: today's behavior, so no limit). Once
   the budget is spent, the turn ends with Hermes's existing
   `max_retries_exhausted_result`, whatever stage it is in.
2. **One probe per ladder cycle, not a full block.** After the wait, a cycle
   tries once. If that try fails, the next cycle starts (or the turn ends). The
   same goes for the "one last primary attempt": it should be one attempt.
3. **Say it in the chat while it waits.** The ladder's countdown notice already
   exists. Send it to messaging platforms as well, once per cycle, worded as "the
   model can't be reached".

With (1) and (2), a gateway could set a budget like 5 minutes and still wait out a
short outage. The user then gets an error they can act on, and AGOS already
records and shows a Hermes error in the workspace's Log.

## Why not in AGOS

Hermes is the engine: AGOS must not patch or wrap Hermes's retry loop. AGOS
could set `agent.auto_recovery_cycles: 0` and a lower `api_max_retries`, but that
also gives up waiting out a real short outage. Only the stages above can tell a
hiccup from a dead endpoint.

## How to check it

In AGOS's failure tests, the model-unreachable case ends `xfail` while this
holds. With a budget, it should pass: the turn ends with the error inside the
budget plus one backoff.
