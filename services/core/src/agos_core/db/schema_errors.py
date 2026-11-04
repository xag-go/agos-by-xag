"""Migration 145, listed by name in db/migrations.py MIGRATIONS: Settings → Errors
(actions/error_issues.py). Each ERROR of AGOS
itself (the core, the web app, a workspace's Hermes errors.log) is counted on one
row per issue (its fingerprint, per workspace; none = the installation), with
its first/last time and the AGOS version, so 1000 identical errors are one row.
The owner marks an issue fixed; one that happens again is open again (came back).

Must not: change once shipped (add a new migration instead).
"""

__all__ = ["ERROR_ISSUES"]

ERROR_ISSUES = """
  CREATE TABLE IF NOT EXISTS error_issues (
    id            INTEGER PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    workspace_id  TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    source        TEXT NOT NULL CHECK (source IN ('core','web','hermes')),
    where_from    TEXT NOT NULL DEFAULT '',
    error_type    TEXT NOT NULL DEFAULT '',
    message       TEXT NOT NULL,
    route         TEXT NOT NULL DEFAULT '',
    trace         TEXT NOT NULL DEFAULT '',
    count         INTEGER NOT NULL DEFAULT 1,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    first_version TEXT NOT NULL DEFAULT '',
    version       TEXT NOT NULL DEFAULT '',
    request_id    TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','fixed')),
    fixed_at      TEXT,
    came_back     INTEGER NOT NULL DEFAULT 0,
    hour_start    TEXT NOT NULL DEFAULT '',
    hour_count    INTEGER NOT NULL DEFAULT 0,
    spike_told_at TEXT
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS error_issues_once
    ON error_issues (fingerprint, COALESCE(workspace_id, ''));
  CREATE INDEX IF NOT EXISTS error_issues_by_last ON error_issues (last_seen);
  """
