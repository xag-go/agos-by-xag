"""Migration 144: a kit for a member already on the team (actions/member_kits.py):
the Co-Founder's 'Kit for @<member>' proposal waits in the Inbox like a hire
(kanban_asks kind 'kit', rebuilt the way 139 did). Replayable: the rebuild starts
from a fresh kanban_asks_new. Moved out of db/migrations.py verbatim (its hash is
unchanged), listed by name in MIGRATIONS.

Must not: change once shipped (add a new migration instead).
"""

__all__ = ["KANBAN_ASKS_KIT"]

KANBAN_ASKS_KIT = """
  -- agos: foreign-keys-off
  CREATE TABLE kanban_asks_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    card         TEXT NOT NULL,
    member       TEXT NOT NULL,
    action       TEXT NOT NULL,
    label        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'waiting'
                 CHECK (status IN ('waiting','allowed','denied',
                                   'approved','revised','rejected','undone','answered')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    kind         TEXT NOT NULL DEFAULT 'ask'
                 CHECK (kind IN ('ask','hire','instructions','plan','question','goal','skill',
                                 'kit')),
    payload      TEXT NOT NULL DEFAULT '',
    round        INTEGER NOT NULL DEFAULT 1,
    note         TEXT,
    result       TEXT
  ) STRICT;
  INSERT INTO kanban_asks_new (id, workspace_id, card, member, action, label, detail, status,
      created_at, decided_at, kind, payload, round, note, result)
    SELECT id, workspace_id, card, member, action, label, detail, status, created_at,
      decided_at, kind, payload, round, note, result FROM kanban_asks;
  DROP TABLE kanban_asks;
  ALTER TABLE kanban_asks_new RENAME TO kanban_asks;
  CREATE UNIQUE INDEX IF NOT EXISTS kanban_asks_once ON kanban_asks (workspace_id, card, action)
    WHERE status = 'waiting';
  CREATE INDEX IF NOT EXISTS kanban_asks_by_ws ON kanban_asks (workspace_id, status);
  """
