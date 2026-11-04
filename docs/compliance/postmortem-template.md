# Postmortem: <short title>

Copy to `docs/postmortems/YYYY-MM-DD-<slug>.md`. Blameless: describe systems and decisions, not people.
Required for every P0/P1 ([sre.md](sre.md)); keep it to one page.

- **Severity:** P0 / P1
- **Status:** draft / reviewed / closed
- **Date of incident:** YYYY-MM-DD **Written:** YYYY-MM-DD
- **AGOS version / SHA live:** `0.x.y` / `<sha>` **Hermes pin:** `<sha>`
- **Detected by:** alert (which) / owner / test / user report
- **Duration:** start → detected → mitigated → resolved (UTC)
- **SLO budget burned:** S1-S5, minutes or %

## Impact

What the owner (or users) could not do, for how long, which workspaces, data lost or exposed (yes/no, what).

## Timeline (UTC)

| Time  | Event                                           |
| ----- | ----------------------------------------------- |
| hh:mm | Change shipped (`<sha>`, PR #)                  |
| hh:mm | First symptom                                   |
| hh:mm | Detected (how)                                  |
| hh:mm | Mitigated (rollback / flag / block)             |
| hh:mm | Fixed (`<sha>`) and verified (command + output) |

## Root cause

The technical cause, down to the line (`file:line`). Then the "why" chain: why the code allowed it, why review
allowed it.

## Why tests and CI missed it

Which test should have caught it, why it did not (not written, skipped in CI, needs real Hermes, mocked away).

## Fix

- Regression test: `tests/...::test_...` (failed before the fix: paste the output line).
- Code fix: PR / commit.
- Guard that stops the whole class (Semgrep rule, ratchet test, type, layer rule, alert).

## Variants

Same root cause elsewhere (`variant-analysis`): list each place and its fix or ticket.

## Action items

| Action | Type (prevent / detect / mitigate) | Owner | Due | Done |
| ------ | ---------------------------------- | ----- | --- | ---- |
|        |                                    |       |     |      |

## Lessons

What went well, what went badly, where we got lucky. One line each.
