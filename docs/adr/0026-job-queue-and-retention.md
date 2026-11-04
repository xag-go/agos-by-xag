# ADR 0026: A durable job queue for AGOS's own background work, and retention

Date: 2026-11-03. Status: accepted (built on `eng/m3-reliability`, migration 147).

## The problem

AGOS's own background work (the idle round, the trash purge, the probes) ran as
`asyncio` loops with in-memory timers. A core restart lost the round in progress,
a failure was a log line and nothing else, and two loops could do the same work
twice. Nothing deleted AGOS's machine records: `system_log`, `op_runs`, the
outbox and the saga journals only grew. And the SLOs of `docs/compliance/sre.md`
were targets with no measurement behind them.

## Decision

1. **Job queue** (`agos_core/jobs/`, table `jobs` in migration 147,
   `db/jobs.py` its only writer).
   - `queue.enqueue` writes a row on the caller's connection: inside a Unit of
     Work it commits or rolls back with the change.
   - A dedupe key keeps one waiting job per (kind, key).
   - `runner` claims a due job in one SQL statement with a 10-minute lease (one
     worker per job), runs its kind's handler, and on failure retries with
     exponential backoff (30 s doubling, at most 1 h, `MAX_ATTEMPTS` 5 by default).
   - The last failed try is a **dead letter**: the row stays `dead` and the error
     is logged on `agos.jobs`, so it shows in the System Log and **Settings →
     Errors** through the existing error pattern. No new screen.
   - At start every lease is let go (the core is the only worker, so a running
     job was cut by the restart).
   - Recurring work (`jobs/recurring.py`) queues its next job `interval` after
     the last one finished. The kinds are `idle.chores` (1 min), `trash.purge`
     (6 h), `retention.daily` (1 day), `slo.health` (1 min) and `slo.probes`
     (5 min), listed in `background/schedule.py`.
2. **Every outgoing message is an outbox row.** A web push is queued by
   `web_push.queue` and sent only by the delivery loop (`outbox/delivery.py`,
   `actions/outbox_push.py`): never before commit, and once per dedupe key. A
   Telegram line is already a `channel_outbox` row handed to Hermes's gateway.
3. **Retention** (`background/retention.py`, the daily job) deletes machine
   records only, each table through its own repository:
   `system_log` after 90 days, `op_runs` 180, delivered `outbox` rows 30 (failed
   ones stay), finished `jobs` 30, completed sagas' journals 90, `slo_samples` 400. The owner's content (chats, cards, Inbox, activity, files, settings,
   anything Hermes keeps) is never touched. These are the owner's defaults; Settings
   shows nothing new. See `docs/operations.md`, "Retention".
4. **SLIs** are measured into `slo_samples` (migration 147): page probe, chat
   first output, core health, and automation due-vs-start from Hermes's own
   dispatch stamp. `scripts/slo.py` prints the monthly report.
5. **Create saga at start**: `actions/engine.resync_all` calls the Workspace
   service's `finish_setup` for every workspace whose create saga needs
   attention, so a half-made workspace finishes after a crash.
6. **Idempotency from the web**: Create workspace, the owner's own hire and Run
   now carry an invisible `Idempotency-Key`. A retry or a double click gets the
   first answer (`ops/idempotency.py`, the same `op_runs` rows as the registry).
7. **Expand/contract migrations**: from 140 on, a migration only adds. A removal
   is its own named step (`-- agos: contract <table>[.<column>]`) after the
   release that stopped reading it. `services/core/scripts/migration_check.py`
   checks this in CI.

## Why not

- **A separate queue service (Redis, Celery)**: one more process and more RAM on
  a single-owner box. SQLite with a lease is enough at AGOS's volume (a few jobs a
  minute) and is backed up with everything else.
- **Hermes's cron for AGOS's chores**: Hermes's cron runs agent turns. AGOS's
  chores are AGOS code, and Hermes stays the engine of the agents only.
- **Retention settings in the UI**: the owner asked for none. The defaults live
  in one table (`retention.POLICY`), changed in code.

## Consequences

- Migration 147 is additive (two new tables). Rolling back to the previous
  release leaves them unread.
- A job handler must be idempotent: a lease that ends mid-run means another try.
- A dead letter is an error issue; it never pages by itself beyond the existing
  error alerts.
