# SRE: SLOs, error budget, incident severity

Proposed 2026-11-02 for one AGOS install (one host, one owner). Window: rolling 28 days. Numbers are starting
targets; re-set them after the first full month of real measurements. `core/` = `services/core/src/agos_core/`.
`$DB` = `$AGOS_DATA_DIR/agos.db` (set in `/etc/agos/agos.conf`, `deploy/install-server.sh:447`).

## SLOs

Measured since migration 147 (ADR 0026): the core writes each sample into the `slo_samples` table of `$DB`
(`core/actions/slis.py`; the probes are jobs of the job queue, `core/background/schedule.py`), and
`python3 scripts/slo.py [--month YYYY-MM] [--json]` prints the month's table (read-only on `$DB`).

| #   | SLI (what is counted)                                                                                | SLO                                                                  | How it is measured (built)                                                                                                                                                                                                    | Sample (`slo_samples.sli`) |
| --- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| S1  | **Page load**: time to first byte of the web's home page, probed from the host                       | 95% of probes TTFB ≤ 800 ms                                          | Job `slo.probes` every 5 min: one GET of `AGOS_SLO_WEB_URL` (default `http://127.0.0.1:3000/`, redirects not followed), time until the response headers. Browser LCP (web vitals) is not measured yet (follow-up).            | `page`                     |
| S2  | **Chat first output**: owner message sent → first visible agent output (activity line or reply text) | 90% ≤ 6 s, 99% ≤ 20 s                                                | `LiveTurn.first_output_at` (`core/engine/chat.py`) is stamped on the first change that shows text or an activity line; when the turn ends, `first_output_at − chat_turns.started_at` is written once per turn.                | `first_output`             |
| S3  | **Core availability**: minutes with an ok `/health` probe                                            | 99.5% (≤ 3 h 22 min down per 28 days)                                | Job `slo.health` every minute: GET `AGOS_SLO_CORE_URL/health` (default `http://127.0.0.1:8766`). A minute with no ok sample since the month's first probe counts as down (the core was not there to probe).                   | `health`                   |
| S4  | **Automation on time**: scheduled runs that start within 2 min of their due time                     | 99% on time, 0 silently missed                                       | Job `slo.probes` every 5 min reads each workspace's Hermes cron jobs; Hermes's own `last_dispatch` stamp (`scheduled_at` = due, `dispatched_at` = start) gives the delay, once per run. Webhook automations have no schedule. | `automation_delay`         |
| S5  | **Backup freshness** (supporting)                                                                    | Last good backup younger than 26 h, 99% of the time (daily schedule) | `GET /backups` status (`core/api/backups.py:31`); not sampled into `slo_samples` yet.                                                                                                                                         | —                          |

Probes are on by default on an install with Hermes and off on a test rig (no Hermes); `AGOS_SLO_CORE_URL=off` /
`AGOS_SLO_WEB_URL=off` turn one off. Samples are kept 400 days (retention, `docs/operations.md`).

### Measured numbers

| Month   | S1 page | S2 first output (≤ 6 s / ≤ 20 s) | S3 availability | S4 on time | Source                                                                                                        |
| ------- | ------- | -------------------------------- | --------------- | ---------- | ------------------------------------------------------------------------------------------------------------- |
| 2026-11 | —       | —                                | —               | —          | Not measured yet: the samplers ship with branch eng/m3-reliability; the first full month is the first report. |

Fill a row each month from `python3 scripts/slo.py --month <YYYY-MM>` on the live host; a "NO" in its `met` column
feeds the error budget policy below.

## Error budget policy

- Budget = 1 − SLO over 28 days (S3: 0.5% = 201 min; S2: 10% of turns slower than 6 s; S4: 1% of runs).
- **Burn alert**: the owner is told (Notifications path: AGOS + push + Telegram) when a day burns more than 10% of the
  monthly budget, or when S3 has 3 failed probes in a row (lane C's dead-man threshold, 180 s).
- **More than 50% spent**: the next ship must contain at least one reliability fix for the SLO that burned; no
  risky refactor ships (Wave 2/3 PRs wait) until the burn rate is back under 1×.
- **Budget exhausted**: feature freeze for that area. Only fixes, tests and rollbacks ship until the 28-day
  window is back within the SLO. Every exhaustion gets a postmortem.
- **Ship gate**: a ship that causes a P0/P1 or burns > 25% of a budget in 24 h is rolled back first (`agos update`
  rollback path), investigated second.
- Monthly review ([README.md](README.md)): the SLO numbers, budget spent, the top 3 burners, and whether a target
  should move (never tighter than what was met, never looser without the owner's OK).

## Incident severity

| Sev    | Definition (AGOS)                                                                                     | Examples                                                                                          | Acknowledge                                  | Mitigate                                 | Fix + test                  | Postmortem                |
| ------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------- | --------------------------- | ------------------------- |
| **P0** | Data loss, workspace isolation broken, security hole exploitable or exploited, core/web down > 15 min | Next RCE reachable; a workspace reads another's files; migration corrupts `agos.db`; backups lost | 15 min after the alert (dead-man / Telegram) | 4 h (rollback, kill switch, block route) | 24 h, regression test first | Required, within 48 h     |
| **P1** | Owner-visible outage of a main feature, or a bug that came back                                       | Chats do not answer; automations stop firing; Telegram silent; approvals skipped                  | 1 h                                          | 8 h                                      | 3 days                      | Required, within 5 days   |
| **P2** | Degraded feature with a workaround; wrong data shown but not lost                                     | One page slow; one automation kind fails; a count is off                                          | 1 day                                        | —                                        | Next ship, ≤ 7 days         | Optional (note in the PR) |
| **P3** | Cosmetic or minor                                                                                     | Copy, alignment, a log line                                                                       | Weekly triage                                | —                                        | ≤ 30 days or close          | No                        |

Security reports map: critical → P0, high → P1, medium → P2, low → P3 (SECURITY.md should state the same).
Every P0/P1 gets `docs/postmortems/YYYY-MM-DD-<slug>.md` from [postmortem-template.md](postmortem-template.md) and a
regression test that failed before the fix (bug rule, skill `agos-engineering-standards`).

## What is built and what is left

1. Built: S1 page probe, S2 first output per turn, S3 health probe ledger, S4 due-vs-start per scheduled run, all in
   `slo_samples` (migration 147), and `scripts/slo.py` (monthly table, `--json`).
2. Left: browser web vitals (LCP/INP) for S1, a deep `/health` (DB write, loops alive) for S3, S5 sampling, and the
   burn alert (the owner told when a day burns > 10% of a budget).
