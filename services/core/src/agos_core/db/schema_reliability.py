"""Migration 147: reliability's own tables, listed by name in db/migrations.py
MIGRATIONS (ADR 0026).

- `jobs`: AGOS's own background work as durable rows (agos_core/jobs): claimed with
  a lease so one worker runs it, retried with backoff, kept as a dead letter after
  its last try. Its dedupe key keeps one waiting job per (kind, key); a finished
  job lets the key go, so the next round of recurring work can be queued.
- `slo_samples`: the measured SLIs of docs/compliance/sre.md (page probe, chat first
  output, automation due-vs-start delay, core health probe), read by
  `scripts/slo.py` for the monthly report. `once_key` records a sample at most once
  (one turn's first output, one automation run's start).

A workspace's rows go with it (ON DELETE CASCADE); `workspace_id` is NULL for the
installation's own rows. Additive only (expand/contract rule, docs/operations.md):
new tables, IF NOT EXISTS everywhere, so a replay is a no-op.

Must not: change once shipped (add a new migration instead).
"""

__all__ = ["RELIABILITY"]

RELIABILITY = """
  CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    payload      TEXT NOT NULL DEFAULT '{}',
    dedupe_key   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','running','done','dead')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    run_at       TEXT NOT NULL,
    lease_until  TEXT,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    finished_at  TEXT
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS jobs_once ON jobs (kind, dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('pending','running');
  CREATE INDEX IF NOT EXISTS jobs_due ON jobs (status, run_at);
  CREATE INDEX IF NOT EXISTS jobs_by_kind ON jobs (kind, finished_at);
  CREATE TABLE IF NOT EXISTS slo_samples (
    id           INTEGER PRIMARY KEY,
    sli          TEXT NOT NULL
                 CHECK (sli IN ('page','first_output','automation_delay','health')),
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    subject      TEXT NOT NULL DEFAULT '',
    value_ms     INTEGER,
    ok           INTEGER NOT NULL DEFAULT 1 CHECK (ok IN (0, 1)),
    once_key     TEXT,
    at           TEXT NOT NULL
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS slo_samples_once ON slo_samples (sli, once_key)
    WHERE once_key IS NOT NULL;
  CREATE INDEX IF NOT EXISTS slo_samples_by_sli ON slo_samples (sli, at);
  """
