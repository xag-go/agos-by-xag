"""Migration 146: the Service Layer's own tables (ARCHITECTURE.md §10), listed by
name in db/migrations.py MIGRATIONS.

- `op_runs`: one row per run of a registered operation (agos_core/ops): who ran
  it, its audit title, how it ended and its result. Its idempotency key makes a
  retry or a double click return the first run's result instead of doing the work
  twice (one key per operation).
- `sagas` + `saga_steps`: the journal of a multi-step change that touches Hermes
  (agos_core/saga.py): each step done, failed or compensated, so a failure is
  visible ("needs attention") and a later sync can finish the steps left.
- `outbox`: notifications written inside the change's transaction and delivered
  after it by one loop with retry and backoff (agos_core/outbox); its dedupe key
  keeps one row per notification.

A workspace's rows go with it (ON DELETE CASCADE); `workspace_id` is NULL until the
workspace exists (a create) or for the installation's own rows. Replayable: IF NOT
EXISTS everywhere.

Must not: change once shipped (add a new migration instead).
"""

__all__ = ["SERVICE_LAYER"]

SERVICE_LAYER = """
  CREATE TABLE IF NOT EXISTS op_runs (
    id              INTEGER PRIMARY KEY,
    operation       TEXT NOT NULL,
    workspace_id    TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    actor           TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','done','failed','undone')),
    result          TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS op_runs_once ON op_runs (operation, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
  CREATE INDEX IF NOT EXISTS op_runs_by_ws ON op_runs (workspace_id, created_at);
  CREATE TABLE IF NOT EXISTS sagas (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','done','needs_attention','compensated',
                                   'compensation_failed')),
    data         TEXT NOT NULL DEFAULT '{}',
    error        TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
  ) STRICT;
  CREATE INDEX IF NOT EXISTS sagas_by_status ON sagas (status, workspace_id);
  CREATE TABLE IF NOT EXISTS saga_steps (
    id      INTEGER PRIMARY KEY,
    saga_id INTEGER NOT NULL REFERENCES sagas(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,
    name    TEXT NOT NULL,
    status  TEXT NOT NULL CHECK (status IN ('done','failed','compensated','compensation_failed')),
    error   TEXT,
    at      TEXT NOT NULL,
    UNIQUE (saga_id, seq)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS outbox (
    id           INTEGER PRIMARY KEY,
    channel      TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    payload      TEXT NOT NULL,
    dedupe_key   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','sending','sent','failed')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_at      TEXT NOT NULL,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    sent_at      TEXT
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS outbox_once ON outbox (channel, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
  CREATE INDEX IF NOT EXISTS outbox_due ON outbox (status, next_at);
  """
