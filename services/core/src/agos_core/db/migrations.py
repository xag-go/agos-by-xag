"""Schema changes, in order. Each runs once in a transaction and bumps
`PRAGMA user_version`. Never edit a shipped entry: add a new one.

Identical to the earlier TypeScript migrations, so existing databases open
unchanged. The newest entries live in db/schema_<area>.py, listed here by name.
"""

from agos_core.db.schema_errors import ERROR_ISSUES
from agos_core.db.schema_kanban_kit import KANBAN_ASKS_KIT
from agos_core.db.schema_reliability import RELIABILITY
from agos_core.db.schema_service_layer import SERVICE_LAYER

MIGRATIONS: tuple[str, ...] = (
    """
  CREATE TABLE workspaces (
    id             TEXT PRIMARY KEY,               -- fixed; the folder name
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    default_model  TEXT NOT NULL,                  -- JSON ModelSelection
    telegram_group TEXT,
    telegram_topic TEXT,
    limits         TEXT NOT NULL,                  -- JSON WorkspaceLimits
    archived_at    TEXT,
    deleted_at     TEXT,                           -- in the trash
    trash_name     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
  ) STRICT;

  -- Folders the owner added. The workspace's own folder is implicit.
  CREATE TABLE workspace_folders (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,                    -- /shared/<name>
    host_path    TEXT NOT NULL,                    -- never shown to a model
    access       TEXT NOT NULL CHECK (access IN ('read', 'read-write')),
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, name),
    UNIQUE (workspace_id, host_path)
  ) STRICT;

  CREATE TABLE tasks (
    id               INTEGER PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_id        INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    position         INTEGER NOT NULL DEFAULT 0,
    title            TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    success_criteria TEXT NOT NULL DEFAULT '[]',   -- JSON string[]
    status           TEXT NOT NULL CHECK (status IN
                       ('todo','clarify','start','progress','review','complete')),
    flags            TEXT NOT NULL DEFAULT '[]',   -- JSON TaskFlag[]
    model            TEXT NOT NULL,                -- JSON ModelSelection
    autonomy         TEXT NOT NULL CHECK (autonomy IN ('return','decide','on_problem')),
    plan_assumptions TEXT NOT NULL DEFAULT '[]',
    plan_risks       TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
  ) STRICT;
  CREATE INDEX tasks_by_workspace ON tasks (workspace_id, status);
  CREATE INDEX tasks_by_parent ON tasks (parent_id);

  -- Sub-tasks go one level deep and stay in their parent's workspace.
  CREATE TRIGGER tasks_one_level BEFORE INSERT ON tasks
  WHEN NEW.parent_id IS NOT NULL AND (
    (SELECT parent_id FROM tasks WHERE id = NEW.parent_id) IS NOT NULL OR
    (SELECT workspace_id FROM tasks WHERE id = NEW.parent_id) IS NOT NEW.workspace_id
  )
  BEGIN SELECT RAISE(ABORT, 'sub-tasks go one level deep, in the same workspace'); END;

  CREATE TABLE plan_steps (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    step    INTEGER NOT NULL,
    text    TEXT NOT NULL,
    model   TEXT NOT NULL,
    status  TEXT NOT NULL CHECK (status IN ('pending','doing','done')),
    PRIMARY KEY (task_id, step)
  ) STRICT;

  CREATE TABLE comments (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    stage      TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
  ) STRICT;

  CREATE TABLE suggestions (
    id               INTEGER PRIMARY KEY,
    comment_id       INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    accepted_task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL
  ) STRICT;

  CREATE TABLE chats (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    channel      TEXT NOT NULL CHECK (channel IN ('web','telegram')),
    model        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
  ) STRICT;

  -- A message belongs to a chat or to a task's Chat tab, never both.
  CREATE TABLE messages (
    id         INTEGER PRIMARY KEY,
    chat_id    INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    author     TEXT NOT NULL CHECK (author IN ('owner','agent')),
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK ((chat_id IS NULL) <> (task_id IS NULL))
  ) STRICT;
  CREATE INDEX messages_by_chat ON messages (chat_id, id);
  CREATE INDEX messages_by_task ON messages (task_id, id);

  CREATE TABLE automations (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    file         TEXT NOT NULL,                    -- relative to the workspace
    instructions TEXT NOT NULL,
    schedule     TEXT NOT NULL,                    -- 5-field cron
    model        TEXT NOT NULL,
    enabled      INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    last_run_at  TEXT,
    last_result  TEXT CHECK (last_result IN ('ok','failed')),
    last_summary TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (workspace_id, file)
  ) STRICT;

  -- What happened, for the Dashboard and as an audit trail (folder grants,
  -- owner decisions…).
  CREATE TABLE activity (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX activity_by_workspace ON activity (workspace_id, id DESC);
  """,
    """
  -- The one owner of this installation. The CHECK keeps it to a single row.
  CREATE TABLE owner (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
  ) STRICT;

  -- Browser sessions. Only the token's SHA-256 is stored.
  CREATE TABLE sessions (
    token_hash   TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    user_agent   TEXT NOT NULL DEFAULT ''
  ) STRICT;
  CREATE INDEX sessions_by_expiry ON sessions (expires_at);

  -- Failed sign-ins, to slow down guessing.
  CREATE TABLE login_failures (
    id         INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
  ) STRICT;
  """,
    """
  -- One row per time the agent works on a task (ADR 0010: a Hermes run).
  CREATE TABLE task_runs (
    id              INTEGER PRIMARY KEY,
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    workspace_id    TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    hermes_run_id   TEXT,                           -- set once Hermes accepted it
    session_id      TEXT NOT NULL,                  -- one Hermes session per task
    status          TEXT NOT NULL CHECK (status IN
                      ('starting','running','stopping','completed','failed','stopped')),
    last_message_id INTEGER NOT NULL DEFAULT 0,     -- task chat read up to here
    provider        TEXT,                           -- what really served it
    model           TEXT,
    usage           TEXT,                           -- JSON, from Hermes
    error           TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT
  ) STRICT;
  CREATE INDEX task_runs_by_task ON task_runs (task_id, id DESC);
  -- At most one live run per task.
  CREATE UNIQUE INDEX task_runs_one_live ON task_runs (task_id)
    WHERE status IN ('starting','running','stopping');

  -- What the agent ran to prove its work: command, exit code, output.
  CREATE TABLE evidence (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id     INTEGER NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
    command    TEXT NOT NULL,
    exit_code  INTEGER,
    output     TEXT NOT NULL,
    created_at TEXT NOT NULL
  ) STRICT;
  CREATE INDEX evidence_by_task ON evidence (task_id, id);
  """,
    """
  -- One row per agent turn in a workspace chat (ADR 0010: a Hermes run in the
  -- chat's own session). The reply lands in messages; tools and thinking stay here.
  CREATE TABLE chat_turns (
    id            INTEGER PRIMARY KEY,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    hermes_run_id TEXT,
    status        TEXT NOT NULL CHECK (status IN
                    ('starting','running','stopping','completed','failed','stopped')),
    asked_up_to   INTEGER NOT NULL,                  -- owner messages sent up to this id
    reply_id      INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    activity      TEXT NOT NULL DEFAULT '[]',        -- JSON: tools, thinking, approvals
    provider      TEXT,
    model         TEXT,
    usage         TEXT,
    error         TEXT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT
  ) STRICT;
  CREATE INDEX chat_turns_by_chat ON chat_turns (chat_id, id);
  CREATE UNIQUE INDEX chat_turns_one_live ON chat_turns (chat_id)
    WHERE status IN ('starting','running','stopping');

  -- Board tasks the agent proposed in a chat; task_id once the owner added one.
  CREATE TABLE chat_proposals (
    id          INTEGER PRIMARY KEY,
    turn_id     INTEGER NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL
  ) STRICT;
  CREATE INDEX chat_proposals_by_turn ON chat_proposals (turn_id);
  """,
    # Chat access (ask before risky commands, or full access inside the sandbox)
    # and what the owner attached to a message (screenshots, voice notes, files).
    """
  ALTER TABLE workspaces ADD COLUMN chat_access TEXT NOT NULL DEFAULT 'ask'
    CHECK (chat_access IN ('ask','full'));
  ALTER TABLE chats ADD COLUMN access TEXT NOT NULL DEFAULT 'ask'
    CHECK (access IN ('ask','full'));

  -- Files live in the workspace's own folder (files/.agos/uploads), never elsewhere.
  CREATE TABLE message_attachments (
    id          INTEGER PRIMARY KEY,
    message_id  INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('image','audio','file')),
    name        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    path        TEXT NOT NULL,                     -- relative to the workspace files
    duration    REAL,                              -- seconds, voice notes
    transcript  TEXT                               -- voice notes, once Hermes heard them
  ) STRICT;
  CREATE INDEX message_attachments_by_message ON message_attachments (message_id, id);
  """,
    # SQLite reuses the id of a deleted chat, so the chat's Hermes session and
    # run keys hang off a random key instead (old chats keep their session).
    """
  ALTER TABLE chats ADD COLUMN hermes_key TEXT;
  UPDATE chats SET hermes_key = 'agos-chat-' || id;
  CREATE UNIQUE INDEX chats_by_hermes_key ON chats (hermes_key);
  """,
    # Deleting a chat only hides it: its messages, files, Hermes session and the
    # workspace's memory stay, so the project keeps what it learned.
    """
  ALTER TABLE chats ADD COLUMN deleted_at TEXT;
  """,
    # The owner's own identity text for the workspace's agent (SOUL.md). Empty =
    # built from the name and description.
    """
  ALTER TABLE workspaces ADD COLUMN identity TEXT NOT NULL DEFAULT '';
  """,
    # Automations run by the workspace's Hermes cron: the job id, the last sync
    # problem, and every run with its report and proposed To do cards.
    """
  ALTER TABLE automations ADD COLUMN hermes_job_id TEXT;
  ALTER TABLE automations ADD COLUMN sync_error TEXT;
  ALTER TABLE automations ADD COLUMN next_run_at TEXT;
  CREATE TABLE automation_runs (
    id            INTEGER PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    hermes_run_id TEXT NOT NULL,
    result        TEXT NOT NULL CHECK (result IN ('ok','failed')),
    source        TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    report        TEXT NOT NULL DEFAULT '',
    error         TEXT,
    UNIQUE (automation_id, hermes_run_id)
  ) STRICT;
  CREATE INDEX automation_runs_by_automation ON automation_runs (automation_id, id DESC);
  CREATE TABLE automation_proposals (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES automation_runs(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL
  ) STRICT;
  """,
    # The global library (definitions only, no secrets) and what each workspace
    # turns on from it, with its own allowed tools, instructions and credential.
    """
  CREATE TABLE library_items (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('skill','agent','mcp','plugin','tool')),
    name        TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    definition  TEXT NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL DEFAULT 'created',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (kind, name)
  ) STRICT;
  CREATE TABLE workspace_connectors (
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_id       INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    enabled       INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    allowed_tools TEXT NOT NULL DEFAULT '[]',
    local         TEXT NOT NULL DEFAULT '',
    secret        TEXT,
    secret_last4  TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (workspace_id, item_id)
  ) STRICT;
  """,
    # When the owner last clicked "Run now" (Hermes labels every fire the same).
    """
  ALTER TABLE automations ADD COLUMN manual_at TEXT;
  """,
    # A task or chat can act as one of the library's agents (on in its workspace).
    """
  ALTER TABLE tasks ADD COLUMN agent TEXT;
  ALTER TABLE chats ADD COLUMN agent TEXT;
  """,
    # Account-wide owner settings (usage thresholds, notification rules…) as JSON.
    """
  CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
  ) STRICT;
  """,
    # Channels (step 7): Telegram bots and Buzz connections, where each chat lives
    # (one address = one chat), a cursor per connection, delivered/seen messages.
    """
  CREATE TABLE channel_connections (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('telegram','buzz')),
    name         TEXT NOT NULL,
    secret       TEXT NOT NULL,
    secret_last4 TEXT NOT NULL,
    relay        TEXT NOT NULL DEFAULT '',
    allowed      TEXT NOT NULL DEFAULT '[]',
    enabled      INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    cursor       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'connecting'
                   CHECK (status IN ('connecting','connected','error')),
    status_reason TEXT NOT NULL DEFAULT '',
    identity     TEXT NOT NULL DEFAULT '',
    last_ok_at   TEXT,
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE TABLE chat_addresses (
    id            INTEGER PRIMARY KEY,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    connection_id INTEGER NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    address       TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    notify        INTEGER NOT NULL DEFAULT 0 CHECK (notify IN (0, 1)),
    created_at    TEXT NOT NULL DEFAULT '',
    UNIQUE (connection_id, address)
  ) STRICT;
  CREATE TABLE channel_seen (
    connection_id INTEGER NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    message_id    TEXT NOT NULL,
    seen_at       TEXT NOT NULL,
    PRIMARY KEY (connection_id, message_id)
  ) STRICT;
  CREATE TABLE channel_outbox (
    id            INTEGER PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    address       TEXT NOT NULL,
    body          TEXT NOT NULL,
    buttons       TEXT NOT NULL DEFAULT '[]',
    task_id       INTEGER,
    source        TEXT NOT NULL DEFAULT '',
    sent_id       TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (connection_id, address, source)
  ) STRICT;
  """,
    # Workers (Slack-like): direct messages with one agent and groups of agents.
    # "chat" = the classic workspace chats; a DM keeps its agent in `agent`
    # (NULL = the Co-Founder); a group lists its members. Who wrote an agent
    # message / who a turn is for (NULL = the Co-Founder / the chat's agent).
    """
  ALTER TABLE chats ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'
    CHECK (kind IN ('chat','dm','group'));
  ALTER TABLE chats ADD COLUMN members TEXT NOT NULL DEFAULT '[]';
  CREATE UNIQUE INDEX chats_one_dm ON chats (workspace_id, COALESCE(agent, ''))
    WHERE kind = 'dm';
  ALTER TABLE messages ADD COLUMN speaker TEXT;
  ALTER TABLE chat_turns ADD COLUMN speaker TEXT;
  ALTER TABLE chat_turns ADD COLUMN note TEXT NOT NULL DEFAULT '';
  """,
    # The workspace's own agent (the Hermes profile's agent) was called "Manager";
    # step 44 (126) names it the Co-Founder.
    """
  UPDATE chats SET title = 'Manager' WHERE kind = 'dm' AND agent IS NULL;
  """,
    # Team plans (ADR 0014): the Co-Founder proposes a chain of steps, the owner
    # approves it once, then AGOS's code runs it. Steps are board tasks that may
    # wait on others; notes between steps are typed task messages.
    """
  CREATE TABLE plans (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id      INTEGER REFERENCES chats(id) ON DELETE SET NULL,
    turn_id      INTEGER REFERENCES chat_turns(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    steps        TEXT NOT NULL,                 -- JSON, the proposal as the Manager wrote it
    status       TEXT NOT NULL CHECK (status IN ('proposed','running','done','rejected')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT
  ) STRICT;
  CREATE INDEX plans_by_workspace ON plans (workspace_id, status);
  CREATE UNIQUE INDEX plans_one_per_turn ON plans (turn_id) WHERE turn_id IS NOT NULL;
  ALTER TABLE tasks ADD COLUMN plan_id INTEGER REFERENCES plans(id) ON DELETE SET NULL;
  ALTER TABLE tasks ADD COLUMN step_key TEXT;
  ALTER TABLE tasks ADD COLUMN step_kind TEXT NOT NULL DEFAULT 'work'
    CHECK (step_kind IN ('work','review','approval'));
  ALTER TABLE tasks ADD COLUMN waits_on TEXT NOT NULL DEFAULT '[]';  -- JSON task ids
  ALTER TABLE tasks ADD COLUMN reviews_task INTEGER;
  ALTER TABLE tasks ADD COLUMN rounds INTEGER NOT NULL DEFAULT 0;     -- times sent back
  CREATE INDEX tasks_by_plan ON tasks (plan_id);
  ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'
    CHECK (kind IN ('chat','handoff','review','question','answer'));
  CREATE TABLE desk_runs (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (kind IN ('route','ask')),
    member        TEXT,
    question      TEXT NOT NULL,
    hermes_run_id TEXT,
    status        TEXT NOT NULL CHECK (status IN ('starting','running','done','failed')),
    created_at    TEXT NOT NULL
  ) STRICT;
  CREATE UNIQUE INDEX desk_one_live ON desk_runs (task_id) WHERE status IN ('starting','running');
  """,
    # A board run waiting for the owner to allow a command (Hermes approval).
    """
  ALTER TABLE task_runs ADD COLUMN approval TEXT;  -- JSON {command, description} while waiting
  """,
    # Several members answering one group message, one after the other.
    """
  ALTER TABLE chat_turns ADD COLUMN queue TEXT NOT NULL DEFAULT '[]';  -- JSON [[member, note]]
  """,
    # Connectors (apps with an account): connected once in Settings, turned on
    # per workspace. The login itself lives in AGOS's connectors home (tokens are
    # Hermes files there), never in this database.
    """
  CREATE TABLE app_connections (
    name          TEXT PRIMARY KEY,               -- catalog name (Hermes optional-mcps)
    status        TEXT NOT NULL CHECK (status IN ('connected','error')),
    tools         TEXT NOT NULL DEFAULT '[]',     -- JSON [{name, description}]
    error         TEXT,
    connected_at  TEXT,
    updated_at    TEXT NOT NULL
  ) STRICT;
  CREATE TABLE workspace_apps (
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    app           TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (workspace_id, app)
  ) STRICT;
  """,
    # A bot made for one workspace: its private chat with the owner is that
    # workspace's Co-Founder chat (linked on the first message, or at creation).
    """
  ALTER TABLE channel_connections ADD COLUMN workspace_id TEXT
    REFERENCES workspaces(id) ON DELETE SET NULL;
  """,
    # Link the owner's Telegram account by a one-time /start code (no id to type).
    """
  ALTER TABLE channel_connections ADD COLUMN claim_code TEXT;
  ALTER TABLE channel_connections ADD COLUMN claim_expires REAL;
  """,
    # The Co-Founder asks, from a chat, to turn a capability on/off (or connect an
    # app); nothing changes until the owner approves the card.
    """
  CREATE TABLE capability_requests (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id      INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    turn_id      INTEGER REFERENCES chat_turns(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('app','skill','agent','mcp','tool')),
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    turn_on      INTEGER NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','connecting','done','rejected','failed')),
    error        TEXT,
    flow_id      TEXT,
    notified     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
  ) STRICT;
  CREATE INDEX capability_requests_by_turn ON capability_requests (turn_id);
  CREATE INDEX capability_requests_by_ws ON capability_requests (workspace_id, status);
  """,
    # The Co-Founder does what the owner asks from a chat (automations, skills,
    # agents, MCP) through the owner's own actions; each shows as a card.
    """
  CREATE TABLE manager_actions (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id      INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    turn_id      INTEGER REFERENCES chat_turns(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,
    title        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','done','rejected','failed','undone')),
    error        TEXT,
    result       TEXT,
    notified     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
  ) STRICT;
  CREATE INDEX manager_actions_by_turn ON manager_actions (turn_id);
  """,
    # DMs with agents carry the agent's current name (they kept the old one).
    """
  UPDATE chats SET title = (
    SELECT l.title FROM library_items l WHERE l.kind = 'agent' AND l.name = chats.agent
  )
  WHERE kind = 'dm' AND agent IS NOT NULL
    AND EXISTS (SELECT 1 FROM library_items l WHERE l.kind = 'agent' AND l.name = chats.agent);
  """,
    # Agents belong to one workspace (its team), never shared between projects.
    # Each agent goes to the workspace that uses it; one used by several becomes
    # one copy per workspace. Skills, MCP servers, plugins and tools stay global.
    """
  CREATE TABLE _agos_connectors AS SELECT * FROM workspace_connectors;
  CREATE TABLE library_items_v2 (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('skill','agent','mcp','plugin','tool')),
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    definition   TEXT NOT NULL DEFAULT '{}',
    source       TEXT NOT NULL DEFAULT 'created',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    CHECK (kind = 'agent' OR workspace_id IS NULL)
  ) STRICT;
  INSERT INTO library_items_v2
    (id, kind, name, title, summary, definition, source, created_at, updated_at, workspace_id)
  SELECT l.id, l.kind, l.name, l.title, l.summary, l.definition, l.source, l.created_at,
         l.updated_at,
         CASE WHEN l.kind = 'agent' THEN (
           SELECT c.workspace_id FROM _agos_connectors c WHERE c.item_id = l.id
           ORDER BY c.enabled DESC, c.workspace_id LIMIT 1) END
  FROM library_items l;
  INSERT INTO library_items_v2
    (kind, name, title, summary, definition, source, created_at, updated_at, workspace_id)
  SELECT l.kind, l.name, l.title, l.summary, l.definition, l.source, l.created_at,
         l.updated_at, c.workspace_id
  FROM library_items l JOIN _agos_connectors c ON c.item_id = l.id
  WHERE l.kind = 'agent'
    AND c.workspace_id != (SELECT v.workspace_id FROM library_items_v2 v WHERE v.id = l.id);
  UPDATE _agos_connectors SET item_id = (
    SELECT v.id FROM library_items_v2 v JOIN library_items l ON l.id = _agos_connectors.item_id
    WHERE v.kind = 'agent' AND v.name = l.name AND v.workspace_id = _agos_connectors.workspace_id)
  WHERE item_id IN (SELECT id FROM library_items WHERE kind = 'agent');
  DROP TABLE library_items;
  ALTER TABLE library_items_v2 RENAME TO library_items;
  DELETE FROM workspace_connectors;
  INSERT INTO workspace_connectors SELECT * FROM _agos_connectors;
  DROP TABLE _agos_connectors;
  CREATE UNIQUE INDEX library_items_unique ON library_items (kind, name, COALESCE(workspace_id, ''));
  CREATE INDEX library_items_by_workspace ON library_items (workspace_id);
  """,
    # Automations say who does them: one agent (NULL = the Co-Founder), or a
    # team plan (steps) that AGOS starts on the board at each fire.
    """
  ALTER TABLE automations ADD COLUMN agent TEXT;
  ALTER TABLE automations ADD COLUMN steps TEXT;
  ALTER TABLE automations ADD COLUMN job_digest TEXT;
  ALTER TABLE automations ADD COLUMN notice TEXT;
  ALTER TABLE plans ADD COLUMN automation_id INTEGER
    REFERENCES automations(id) ON DELETE SET NULL;
  """,
    # Automations can also start the moment something happens outside (a
    # webhook): a secret address per automation, an optional signing secret
    # (sealed), which events count, and every delivery received (kept once).
    """
  ALTER TABLE automations ADD COLUMN hook_token TEXT;
  ALTER TABLE automations ADD COLUMN hook_secret TEXT;
  ALTER TABLE automations ADD COLUMN hook_filter TEXT;
  CREATE UNIQUE INDEX automations_by_hook ON automations (hook_token)
    WHERE hook_token IS NOT NULL;
  CREATE TABLE automation_events (
    id            INTEGER PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    delivery      TEXT NOT NULL,
    event         TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN
                    ('pending','started','duplicate','filtered','rejected','off')),
    detail        TEXT NOT NULL DEFAULT '',
    plan_id       INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    received_at   TEXT NOT NULL,
    UNIQUE (automation_id, delivery)
  ) STRICT;
  CREATE INDEX automation_events_pending ON automation_events (automation_id, status);
  """,
    # Events (start the moment something happens outside) are kept apart from
    # scheduled automations: an event has no schedule. And either can "check
    # with me first": the owner approves before the work goes on.
    """
  ALTER TABLE automations ADD COLUMN check_first INTEGER NOT NULL DEFAULT 0
    CHECK (check_first IN (0, 1));
  UPDATE automations SET schedule = '', next_run_at = NULL WHERE hook_token IS NOT NULL;
  """,
    # The task chat is a conversation: each owner message there gets an answer
    # from the task's agent right away (one answer at a time per task).
    """
  CREATE TABLE task_replies (
    id            INTEGER PRIMARY KEY,
    task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    hermes_run_id TEXT,
    asked_up_to   INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
    started_at    TEXT NOT NULL,
    ended_at      TEXT
  ) STRICT;
  CREATE UNIQUE INDEX task_replies_one_live ON task_replies (task_id) WHERE ended_at IS NULL;
  """,
    # The last state of each task told to the owner (done / stopped / needs him), so
    # the Co-Founder chat notes a change once. Today's states count as already told.
    """
  CREATE TABLE task_notes (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    state   TEXT,
    at      TEXT NOT NULL
  ) STRICT;
  INSERT INTO task_notes (task_id, state, at)
    SELECT id,
      CASE
        WHEN flags LIKE '%"cancelled"%' THEN NULL
        WHEN status = 'complete' THEN 'done'
        WHEN flags LIKE '%"blocked"%' THEN 'stopped'
        WHEN status = 'clarify' OR flags LIKE '%"waiting_owner"%'
          OR flags LIKE '%"needs_decision"%' THEN 'needs'
      END,
      strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    FROM tasks;
  """,
    # The owner's three kinds of wait are told apart (a question / a decision / an
    # Approve), and a question still with the Co-Founder isn't his yet.
    """
  UPDATE task_notes SET state = (
    SELECT CASE
        WHEN t.flags LIKE '%"cancelled"%' THEN NULL
        WHEN t.status = 'complete' THEN 'done'
        WHEN t.flags LIKE '%"blocked"%' THEN 'stopped'
        WHEN t.status = 'clarify' AND t.flags LIKE '%"waiting_answer"%' THEN NULL
        WHEN t.status = 'clarify' THEN 'question'
        WHEN t.flags LIKE '%"needs_decision"%' THEN 'decision'
        WHEN t.flags LIKE '%"waiting_owner"%' THEN 'approve'
      END
    FROM tasks t WHERE t.id = task_notes.task_id);
  """,
    # AGOS's own warnings and errors, for the workspace Log.
    """
  CREATE TABLE system_log (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT,
    level        TEXT NOT NULL CHECK (level IN ('warn','error')),
    source       TEXT NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX system_log_by_workspace ON system_log (workspace_id, id);
  """,
    # A run that ended before the work was done: why, carried into the next run
    # so the agent goes on where it stopped (the task never ends "stopped" by itself).
    """
  ALTER TABLE task_runs ADD COLUMN resume TEXT;
  """,
    # A task using far more tokens than usual: the level already told the owner
    # (1 = past the mark, 2 = twice it, ...). He decides; the work isn't stopped.
    """
  CREATE TABLE token_alerts (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    level   INTEGER NOT NULL,
    tokens  INTEGER NOT NULL,
    at      TEXT NOT NULL
  ) STRICT;
  """,
    # The owner writes while an answer is still working: a quick reply on the side
    # (the work isn't stopped; his words are also passed into it).
    """
  CREATE TABLE chat_asides (
    id            INTEGER PRIMARY KEY,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    turn_id       INTEGER NOT NULL,
    speaker       TEXT,
    asked_up_to   INTEGER NOT NULL,
    hermes_run_id TEXT,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
    started_at    TEXT NOT NULL,
    ended_at      TEXT
  ) STRICT;
  CREATE UNIQUE INDEX chat_asides_one_live ON chat_asides (chat_id) WHERE ended_at IS NULL;
  """,
    # The owner can answer a precise message (a reply, like in any messenger).
    """
  ALTER TABLE messages ADD COLUMN reply_to INTEGER;
  """,
    # Documentation: every version of every rule file (who, why), agent text
    # versions (kept when an agent changes or is deleted), per-workspace doc settings.
    """
  CREATE TABLE doc_versions (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    path         TEXT NOT NULL,
    body         TEXT NOT NULL,
    hash         TEXT NOT NULL,
    author       TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX doc_versions_by_file ON doc_versions (workspace_id, path, id DESC);
  CREATE TABLE agent_versions (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    definition   TEXT NOT NULL,
    event        TEXT NOT NULL CHECK (event IN ('changed','deleted')),
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX agent_versions_by_name ON agent_versions (workspace_id, name, id DESC);
  CREATE TABLE doc_settings (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    latin_only   INTEGER NOT NULL DEFAULT 0
  ) STRICT;
  INSERT INTO doc_settings (workspace_id, latin_only)
    SELECT id, CASE WHEN id = 'content-creation' THEN 1 ELSE 0 END FROM workspaces;
  """,
    # Self-improvement + proactive work: the owner's Autonomy rules per agent, the
    # watcher (reads only, suggests To do cards), feedback, and the learning log.
    """
  CREATE TABLE autonomy_rules (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent        TEXT NOT NULL,            -- agent id, '' = the Manager, '*' = everyone
    action       TEXT NOT NULL,
    choice       TEXT NOT NULL CHECK (choice IN ('do','ask','never')),
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, agent, action)
  ) STRICT;
  CREATE TABLE watcher_settings (
    workspace_id    TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    enabled         INTEGER NOT NULL DEFAULT 0,
    every_hours     INTEGER NOT NULL DEFAULT 6,
    max_suggestions INTEGER NOT NULL DEFAULT 5,
    model           TEXT,                  -- JSON ModelSelection; NULL = workspace default
    last_run_at     TEXT,
    hermes_run_id   TEXT,
    status          TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle','running','failed')),
    error           TEXT
  ) STRICT;
  CREATE TABLE watch_suggestions (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    key          TEXT NOT NULL,            -- normalized title, for dedupe
    title        TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    evidence     TEXT NOT NULL DEFAULT '[]',
    plan         TEXT NOT NULL DEFAULT '',
    agent        TEXT,
    state        TEXT NOT NULL DEFAULT 'open'
                 CHECK (state IN ('open','started','dismissed','snoozed','done')),
    reason       TEXT,
    snooze_until TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX watch_suggestions_by_ws ON watch_suggestions (workspace_id, state);
  CREATE TABLE feedback (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent        TEXT,
    kind         TEXT NOT NULL,            -- approve, reject, undo, dismiss, changes, edit...
    subject      TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    ref          TEXT,                     -- task:12, chat:4, suggestion:9
    learned_at   TEXT,                     -- given to the agent's learning
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX feedback_by_ws ON feedback (workspace_id, id DESC);
  """,
    # Reply to a selected part of a message (not the whole), and the owner's edits.
    """
  ALTER TABLE messages ADD COLUMN reply_excerpt TEXT;
  ALTER TABLE messages ADD COLUMN edited_at TEXT;
  CREATE TABLE chat_edits (
    id         INTEGER PRIMARY KEY,
    chat_id    INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL,
    before     TEXT NOT NULL,
    after      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    told_at    TEXT
  ) STRICT;
  """,
    # Board runs' agos-actions: cards on the task, then a follow-up run by itself.
    """
  ALTER TABLE manager_actions ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE;
  ALTER TABLE manager_actions ADD COLUMN run_id INTEGER;
  CREATE INDEX manager_actions_by_run ON manager_actions (run_id);
  ALTER TABLE task_runs ADD COLUMN follow_up INTEGER NOT NULL DEFAULT 0;
  """,
    # The owner's rules for every workspace (about him, not about one project).
    """
  -- Board tasks made before the app was named AGOS keep their Hermes sessions
  -- (xag-task-N): remember the last one, so a task moved back to Start goes on.
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'legacy.task_sessions_upto', CAST(COALESCE(MAX(id), 0) AS TEXT),
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    FROM tasks;
  CREATE TABLE owner_rules (
    id             INTEGER PRIMARY KEY,
    text           TEXT NOT NULL,
    from_workspace TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
  ) STRICT;
  """,
    # Goal mode (a judge checks the goal; rounds until done) and "starts after".
    """
  ALTER TABLE tasks ADD COLUMN goal_mode INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE tasks ADD COLUMN goal_turns INTEGER NOT NULL DEFAULT 10;
  ALTER TABLE task_runs ADD COLUMN goal INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE task_runs ADD COLUMN goal_check TEXT;
  """,
    # General check: one row per workspace (on by default, new workspaces too).
    """
  CREATE TABLE general_checks (
    workspace_id  TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    enabled       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'idle' CHECK (status IN ('idle','running')),
    hermes_run_id TEXT,
    started_at    TEXT,
    manual        INTEGER NOT NULL DEFAULT 0,
    last_check_at TEXT,
    last_result   TEXT,
    error         TEXT,
    retry_at      TEXT
  ) STRICT;
  """,
    # "check general" from a chat: its report goes back to that chat.
    """
  ALTER TABLE general_checks ADD COLUMN report_chat INTEGER;
  """,
    # /check-general in a chat: it first asks "suggest tasks, or just tell me?".
    """
  ALTER TABLE general_checks ADD COLUMN ask_chat INTEGER;
  ALTER TABLE general_checks ADD COLUMN ask_at TEXT;
  ALTER TABLE general_checks ADD COLUMN suggest INTEGER NOT NULL DEFAULT 1;
  """,
    # Looking ahead has two checks: simple (on its schedule, Hermes summarises a long
    # context) and general (only when asked, the whole context with no summary).
    # In a chat, /check-simple and /check-general first ask on a card: suggestions?
    """
  ALTER TABLE general_checks ADD COLUMN mode TEXT NOT NULL DEFAULT 'simple';
  ALTER TABLE general_checks ADD COLUMN suggest_count INTEGER;
  ALTER TABLE general_checks ADD COLUMN lifted INTEGER NOT NULL DEFAULT 0;
  CREATE TABLE check_asks (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL,
    chat_id       INTEGER NOT NULL,
    turn_id       INTEGER NOT NULL,
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'asking',
    suggest       INTEGER,
    count         INTEGER,
    error         TEXT,
    created_at    TEXT NOT NULL,
    answered_at   TEXT
  ) STRICT;
  CREATE INDEX check_asks_by_turn ON check_asks (turn_id);
  """,
    # Chat task proposals can ask for goal mode, its rounds and "after" tasks.
    """
  ALTER TABLE chat_proposals ADD COLUMN goal_mode INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE chat_proposals ADD COLUMN goal_turns INTEGER NOT NULL DEFAULT 10;
  ALTER TABLE chat_proposals ADD COLUMN waits_on TEXT NOT NULL DEFAULT '[]';
  """,
    # Follow-ups the owner and an agent agreed on: at due_at the agent starts the
    # talk itself in the same chat. AUTOINCREMENT: an id is never handed out twice,
    # so a deleted project's follow-up number can't point at another's.
    """
  CREATE TABLE followups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id      INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    speaker      TEXT,
    topic        TEXT NOT NULL,
    context      TEXT NOT NULL DEFAULT '',
    due_at       TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'scheduled'
                 CHECK (state IN ('scheduled', 'starting', 'running', 'sent', 'cancelled', 'stopped')),
    turn_id      INTEGER,
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_turn INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    sent_at      TEXT
  ) STRICT;
  CREATE INDEX followups_due ON followups (state, due_at);
  CREATE INDEX followups_chat ON followups (chat_id, state);
  """,
    # Watches: a job the owner handed an agent to keep an eye on until it is done.
    # Checked in the background on its own Hermes session; speaks only with news.
    """
  CREATE TABLE watches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    speaker       TEXT,
    goal          TEXT NOT NULL,
    context       TEXT NOT NULL DEFAULT '',
    notes         TEXT NOT NULL DEFAULT '',
    every_minutes REAL NOT NULL DEFAULT 60,
    state         TEXT NOT NULL DEFAULT 'active'
                  CHECK (state IN ('active', 'checking', 'done', 'stopped')),
    next_at       TEXT NOT NULL,
    run_id        TEXT,
    run_started   TEXT,
    checks        INTEGER NOT NULL DEFAULT 0,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    last_check_at TEXT,
    last_told_at  TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    ended_at      TEXT
  ) STRICT;
  CREATE INDEX watches_due ON watches (state, next_at);
  """,
    # Goal mode in chats (like Hermes's /goal): a judge checks work done in a chat
    # and the agent goes on until it is finished, up to the workspace's rounds.
    """
  ALTER TABLE workspaces ADD COLUMN chat_goal_rounds INTEGER NOT NULL DEFAULT 10;
  ALTER TABLE chat_turns ADD COLUMN goal_state TEXT;
  ALTER TABLE chat_turns ADD COLUMN goal_round INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE chat_turns ADD COLUMN goal_text TEXT;
  ALTER TABLE chat_turns ADD COLUMN goal_response TEXT;
  ALTER TABLE chat_turns ADD COLUMN goal_reason TEXT;
  ALTER TABLE chat_turns ADD COLUMN goal_at TEXT;
  CREATE INDEX chat_turns_goal ON chat_turns (goal_state);
  """,
    # AGOS Brain: ways of working shared by every workspace (no project in them);
    # a workspace can turn one off. AUTOINCREMENT: an id is never reused.
    """
  CREATE TABLE brain_methods (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    text           TEXT NOT NULL,
    from_workspace TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
  ) STRICT;
  CREATE TABLE brain_mutes (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    method_id    INTEGER NOT NULL REFERENCES brain_methods(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, method_id)
  ) STRICT;
  """,
    # Channel messages marked 👀 that still wait for their answer; the answer
    # going out turns the mark into 👍 (like Hermes on Telegram).
    """
  CREATE TABLE channel_reads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    address       TEXT NOT NULL,
    message_id    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    done_at       TEXT
  ) STRICT;
  CREATE INDEX channel_reads_open ON channel_reads (done_at, connection_id, address);
  """,
    # A Telegram bot can run on the workspace's own Hermes gateway (engine 'hermes'):
    # Hermes receives and answers, AGOS mirrors the conversation (`via` on its turns).
    """
  ALTER TABLE channel_connections ADD COLUMN engine TEXT NOT NULL DEFAULT 'agos';
  ALTER TABLE chat_turns ADD COLUMN via TEXT;
  """,
    # What he writes in AGOS for a chat that lives on Hermes's Telegram: handed to
    # that workspace's Hermes, which takes it into the same conversation.
    """
  CREATE TABLE hermes_inbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_ref     TEXT NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    taken_at     TEXT,
    done_at      TEXT
  ) STRICT;
  CREATE INDEX hermes_inbox_open ON hermes_inbox (workspace_id, done_at, taken_at);
  """,
    # An inbox item is his message, or his answer to an approval Hermes asks for.
    """
  ALTER TABLE hermes_inbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'message';
  """,
    # 👀 → 👍 is Hermes's own on its Telegram: AGOS's copy of it is gone.
    """
  DROP TABLE channel_reads;
  """,
    # Every Telegram bot is a workspace's, received by that workspace's Hermes
    # gateway (AGOS's own receiver is gone). A bot without a workspace is turned off.
    """
  UPDATE channel_connections SET engine = 'hermes' WHERE kind = 'telegram';
  UPDATE channel_connections SET enabled = 0, status = 'error',
    status_reason = 'Add this bot in a workspace''s settings: each workspace has its own channels.'
    WHERE kind = 'telegram' AND workspace_id IS NULL;
  """,
    # Buzz is gone (Hermes has no Buzz): its connections and their chat links go too.
    """
  DELETE FROM chat_addresses WHERE connection_id IN
    (SELECT id FROM channel_connections WHERE kind = 'buzz');
  DELETE FROM channel_outbox WHERE connection_id IN
    (SELECT id FROM channel_connections WHERE kind = 'buzz');
  DELETE FROM channel_connections WHERE kind = 'buzz';
  """,
    # A card with buttons answered (in AGOS or in Telegram): when it was closed.
    """
  ALTER TABLE channel_outbox ADD COLUMN closed_at TEXT;
  UPDATE channel_outbox SET closed_at = created_at WHERE buttons != '[]';
  """,
    # AGOS's own conversations on Hermes: his voice notes / files go as files.
    """
  ALTER TABLE hermes_inbox ADD COLUMN media TEXT NOT NULL DEFAULT '[]';
  """,
    # Goal mode and quick replies while an answer works are Hermes's own now (/goal,
    # its steer / queue): AGOS's copies and their table go.
    """
  DROP TABLE IF EXISTS chat_asides;
  UPDATE chat_turns SET goal_state = NULL WHERE goal_state IS NOT NULL;
  """,
    # A task an agent proposed can be turned down (No), not only added to To do.
    """
  ALTER TABLE chat_proposals ADD COLUMN declined_at TEXT;
  """,
    # Board tasks as Hermes conversations: AGOS's instructions for the run (given
    # once, when the answer starts) and the answer Hermes reported back.
    """
  ALTER TABLE task_runs ADD COLUMN brief TEXT;
  ALTER TABLE task_runs ADD COLUMN result TEXT;
  """,
    # Follow-ups and watches are the agents' own Hermes cron jobs now (its cronjob
    # tool is always on): AGOS's own ones end, and the tool's on/off switch goes.
    """
  UPDATE watches SET state = 'stopped' WHERE state IN ('active', 'checking');
  UPDATE followups SET state = 'cancelled' WHERE state IN ('scheduled', 'starting', 'running');
  DELETE FROM workspace_connectors WHERE item_id IN
    (SELECT id FROM library_items WHERE kind = 'tool' AND name = 'cronjob');
  DELETE FROM library_items WHERE kind = 'tool' AND name = 'cronjob';
  """,
    # Limits: no monthly cap on task runs any more (the token watch asks him
    # instead); the loop detector is Hermes's own loop guard.
    """
  UPDATE workspaces SET limits = json_remove(limits, '$.taskLimit');
  """,
    # A task's cards go back to the chat it came from (not to every place).
    """
  ALTER TABLE tasks ADD COLUMN origin_chat INTEGER REFERENCES chats(id) ON DELETE SET NULL;
  UPDATE tasks SET origin_chat = (
    SELECT t.chat_id FROM chat_proposals p JOIN chat_turns t ON t.id = p.turn_id
    WHERE p.task_id = tasks.id LIMIT 1);
  """,
    # Telegram cards go out through the workspace's Hermes gateway (its own bot):
    # a row it took, and the closing edit it still has to make.
    """
  ALTER TABLE channel_outbox ADD COLUMN claimed_at TEXT;
  ALTER TABLE channel_outbox ADD COLUMN close_text TEXT;
  """,
    # A board run's report and actions come from the agent's Hermes tools
    # (agos_report, agos_action), kept on the run until its answer ends.
    """
  ALTER TABLE task_runs ADD COLUMN report TEXT;
  ALTER TABLE task_runs ADD COLUMN actions TEXT;
  """,
    # The Co-Founder passes a group's request to members with its agos_handoff tool:
    # kept on its turn, the members answer when it ends.
    """
  ALTER TABLE chat_turns ADD COLUMN handoffs TEXT;
  """,
    # Cards an automation's run proposes with agos_add_task, until the run is read.
    """
  CREATE TABLE automation_proposed (
    id INTEGER PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
  );
  """,
    # A card an automation proposed: his No, and whether it reached his Telegram.
    """
  ALTER TABLE automation_proposals ADD COLUMN declined_at TEXT;
  ALTER TABLE automation_proposals ADD COLUMN notified INTEGER NOT NULL DEFAULT 1;
  """,
    # The Brain lives in Hermes now (shared skills + each profile's skills.disabled);
    # AGOS's copies are gone (both were empty when this shipped).
    """
  DROP TABLE brain_mutes;
  DROP TABLE brain_methods;
  """,
    # Members: people the owner shares workspaces with. Each signs in with his own
    # username and password (set from an invite link) and sees only his own chats in
    # the workspaces shared with him.
    """
  CREATE TABLE members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT,
    invite_hash TEXT,
    invite_expires_at TEXT,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
  CREATE TABLE member_workspaces (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'chat' CHECK (role IN ('chat')),
    PRIMARY KEY (member_id, workspace_id)
  );
  ALTER TABLE sessions ADD COLUMN member_id INTEGER REFERENCES members(id) ON DELETE CASCADE;
  ALTER TABLE chats ADD COLUMN member_id INTEGER REFERENCES members(id) ON DELETE SET NULL;
  CREATE INDEX chats_member ON chats(member_id) WHERE member_id IS NOT NULL;
  """,
    # AGOS's own Google server is gone: Google is Google's own MCP servers in Hermes
    # (google-drive / google-sheets / google-docs).
    """
  DELETE FROM workspace_apps WHERE app = 'google';
  DELETE FROM app_connections WHERE name = 'google';
  """,
    # The old Looking ahead is gone: its suggestions are normal cards now.
    """
  DROP TABLE IF EXISTS watch_suggestions;
  DROP TABLE IF EXISTS watcher_settings;
  """,
    # A library skill lives once: its Hermes skill folder (global/skills/<name>);
    # the database keeps only where it came from.
    """
  UPDATE library_items SET definition = json_remove(definition, '$.text', '$.files')
   WHERE kind = 'skill';
  """,
    # A member working a Kanban card asks the owner (his "Ask me" Autonomy rules):
    # the card waits (blocked) until he answers, in the Co-Founder's chat and phone.
    """
  CREATE TABLE kanban_asks (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    card         TEXT NOT NULL,
    member       TEXT NOT NULL,
    action       TEXT NOT NULL,
    label        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'waiting'
                 CHECK (status IN ('waiting','allowed','denied')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT
  ) STRICT;
  CREATE UNIQUE INDEX kanban_asks_once ON kanban_asks (workspace_id, card, action)
    WHERE status = 'waiting';
  CREATE INDEX kanban_asks_by_ws ON kanban_asks (workspace_id, status);
  """,
    # A Kanban card's own chat: talks with the card's member (its own Hermes).
    """
  ALTER TABLE chats ADD COLUMN kanban_card TEXT;
  ALTER TABLE chat_proposals ADD COLUMN kanban_card TEXT;
  ALTER TABLE automation_proposals ADD COLUMN kanban_card TEXT;
  CREATE UNIQUE INDEX chats_kanban_card ON chats (workspace_id, kanban_card)
    WHERE kanban_card IS NOT NULL AND deleted_at IS NULL;
  """,
    # The old board's engine is gone (Hermes's Kanban runs the work; the old
    # tasks were moved there): its tables that nothing reads go. `tasks` and
    # `plans` stay for now: live tables (messages, activity, proposals) still
    # point at them. The automations' timing lives in Hermes's cron and their
    # Kanban runs are read from Hermes's cards, so those copies go too.
    """
  DROP TABLE IF EXISTS suggestions;
  DROP TABLE IF EXISTS comments;
  DROP TABLE IF EXISTS evidence;
  DROP TABLE IF EXISTS token_alerts;
  DROP TABLE IF EXISTS task_notes;
  DROP TABLE IF EXISTS task_replies;
  DROP TABLE IF EXISTS desk_runs;
  DROP TABLE IF EXISTS plan_steps;
  DROP TABLE IF EXISTS task_runs;
  DROP TABLE IF EXISTS general_checks;
  DROP TABLE IF EXISTS check_asks;
  DROP TABLE IF EXISTS followups;
  DROP TABLE IF EXISTS watches;
  ALTER TABLE automations DROP COLUMN next_run_at;
  ALTER TABLE automations DROP COLUMN last_run_at;
  ALTER TABLE automations DROP COLUMN last_result;
  ALTER TABLE automations DROP COLUMN last_summary;
  DELETE FROM app_settings WHERE key LIKE 'automation.cards.%';
  """,
    # The old board's last tables go: each workspace's tasks, plans and task chats
    # are first written to files/archive/old-board-<date>.json (db/old_board.py).
    # The tables that pointed at them are rebuilt without those links (SQLite's
    # own recipe, foreign keys off, every link checked before commit). The old ids
    # stay as plain numbers where they say something (an accepted proposal).
    """
  -- agos: foreign-keys-off
  -- agos: archive-old-board
  -- agos: ensure-column chat_proposals.kanban_card TEXT
  -- agos: ensure-column automation_proposals.kanban_card TEXT
  DELETE FROM message_attachments
    WHERE message_id IN (SELECT id FROM messages WHERE task_id IS NOT NULL);
  UPDATE chat_turns SET reply_id = NULL
    WHERE reply_id IN (SELECT id FROM messages WHERE task_id IS NOT NULL);
  DELETE FROM messages WHERE task_id IS NOT NULL;
  CREATE TABLE messages_new (
    id            INTEGER PRIMARY KEY,
    chat_id       INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    author        TEXT NOT NULL CHECK (author IN ('owner','agent')),
    body          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    speaker       TEXT,
    kind          TEXT NOT NULL DEFAULT 'chat'
                  CHECK (kind IN ('chat','handoff','review','question','answer')),
    reply_to      INTEGER,
    reply_excerpt TEXT,
    edited_at     TEXT
  ) STRICT;
  INSERT INTO messages_new (id, chat_id, author, body, created_at, speaker, kind, reply_to,
      reply_excerpt, edited_at)
    SELECT id, chat_id, author, body, created_at, speaker, kind, reply_to, reply_excerpt,
      edited_at FROM messages;
  DROP TABLE messages;
  ALTER TABLE messages_new RENAME TO messages;
  CREATE INDEX messages_by_chat ON messages (chat_id, id);

  CREATE TABLE activity_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id      INTEGER,
    kind         TEXT NOT NULL,
    text         TEXT NOT NULL,
    created_at   TEXT NOT NULL
  ) STRICT;
  INSERT INTO activity_new SELECT id, workspace_id, task_id, kind, text, created_at FROM activity;
  DROP TABLE activity;
  ALTER TABLE activity_new RENAME TO activity;
  CREATE INDEX activity_by_workspace ON activity (workspace_id, id DESC);

  CREATE TABLE chat_proposals_new (
    id          INTEGER PRIMARY KEY,
    turn_id     INTEGER NOT NULL REFERENCES chat_turns(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    task_id     INTEGER,
    goal_mode   INTEGER NOT NULL DEFAULT 0,
    goal_turns  INTEGER NOT NULL DEFAULT 10,
    waits_on    TEXT NOT NULL DEFAULT '[]',
    declined_at TEXT,
    kanban_card TEXT
  ) STRICT;
  INSERT INTO chat_proposals_new SELECT id, turn_id, title, description, task_id, goal_mode,
    goal_turns, waits_on, declined_at, kanban_card FROM chat_proposals;
  DROP TABLE chat_proposals;
  ALTER TABLE chat_proposals_new RENAME TO chat_proposals;
  CREATE INDEX chat_proposals_by_turn ON chat_proposals (turn_id);

  CREATE TABLE automation_proposals_new (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES automation_runs(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_id     INTEGER,
    declined_at TEXT,
    notified    INTEGER NOT NULL DEFAULT 1,
    kanban_card TEXT
  ) STRICT;
  INSERT INTO automation_proposals_new SELECT id, run_id, title, description, task_id,
    declined_at, notified, kanban_card FROM automation_proposals;
  DROP TABLE automation_proposals;
  ALTER TABLE automation_proposals_new RENAME TO automation_proposals;

  CREATE TABLE manager_actions_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id      INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    turn_id      INTEGER REFERENCES chat_turns(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,
    title        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed'
                 CHECK (status IN ('proposed','done','rejected','failed','undone')),
    error        TEXT,
    result       TEXT,
    notified     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    task_id      INTEGER,
    run_id       INTEGER
  ) STRICT;
  INSERT INTO manager_actions_new SELECT id, workspace_id, chat_id, turn_id, action, title,
    payload, status, error, result, notified, created_at, decided_at, task_id, run_id
    FROM manager_actions;
  DROP TABLE manager_actions;
  ALTER TABLE manager_actions_new RENAME TO manager_actions;
  CREATE INDEX manager_actions_by_turn ON manager_actions (turn_id);
  CREATE INDEX manager_actions_by_run ON manager_actions (run_id);

  CREATE TABLE automation_events_new (
    id            INTEGER PRIMARY KEY,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    delivery      TEXT NOT NULL,
    event         TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN
                    ('pending','started','duplicate','filtered','rejected','off')),
    detail        TEXT NOT NULL DEFAULT '',
    plan_id       INTEGER,
    received_at   TEXT NOT NULL,
    UNIQUE (automation_id, delivery)
  ) STRICT;
  INSERT INTO automation_events_new SELECT id, automation_id, workspace_id, delivery, event,
    payload, status, detail, plan_id, received_at FROM automation_events;
  DROP TABLE automation_events;
  ALTER TABLE automation_events_new RENAME TO automation_events;
  CREATE INDEX automation_events_pending ON automation_events (automation_id, status);

  DROP TRIGGER IF EXISTS tasks_one_level;
  DROP TABLE tasks;
  DROP TABLE plans;
  """,
    # A workspace's model lives in its Hermes profile only (model.*,
    # agent.reasoning_effort): AGOS reads it there and writes the owner's pick there.
    # The old per-workspace limits are Hermes's own settings now (hermes_limits.py).
    """
  ALTER TABLE workspaces DROP COLUMN default_model;
  ALTER TABLE workspaces DROP COLUMN limits;
  """,
    # Automations: the file is the one copy of the instructions (the old column
    # goes), and a one-agent job's model is Hermes's (NULL here once the job has it).
    """
  -- agos: foreign-keys-off
  CREATE TABLE automations_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    file         TEXT NOT NULL,                    -- relative to the workspace
    schedule     TEXT NOT NULL,                    -- 5-field cron (until Hermes has it)
    model        TEXT,                             -- NULL: Hermes's job holds it
    enabled      INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    hermes_job_id TEXT,
    sync_error   TEXT,
    manual_at    TEXT,
    agent        TEXT,
    steps        TEXT,
    job_digest   TEXT,
    notice       TEXT,
    hook_token   TEXT,
    hook_secret  TEXT,
    hook_filter  TEXT,
    check_first  INTEGER NOT NULL DEFAULT 0 CHECK (check_first IN (0, 1)),
    UNIQUE (workspace_id, file)
  ) STRICT;
  INSERT INTO automations_new (id, workspace_id, name, file, schedule, model, enabled,
      created_at, updated_at, hermes_job_id, sync_error, manual_at, agent, steps, job_digest,
      notice, hook_token, hook_secret, hook_filter, check_first)
    SELECT id, workspace_id, name, file, schedule, model, enabled, created_at, updated_at,
      hermes_job_id, sync_error, manual_at, agent, steps, job_digest, notice, hook_token,
      hook_secret, hook_filter, check_first FROM automations;
  DROP TABLE automations;
  ALTER TABLE automations_new RENAME TO automations;
  CREATE UNIQUE INDEX automations_by_hook ON automations (hook_token)
    WHERE hook_token IS NOT NULL;
  """,
    # Dead data out. The owner's decisions are said to Hermes (its learning
    # conversation keeps them) and the old engine's feed lines are history: both
    # are written to files/archive/history-<date>.json first (db/old_board.py).
    # The chat goal columns are Hermes's /goal now; settings no code reads go.
    """
  -- agos: archive-history
  DELETE FROM activity WHERE (task_id IS NOT NULL OR kind LIKE 'plan.%' OR kind LIKE 'check.%'
                   OR kind LIKE 'watcher.%');
  DROP TABLE feedback;
  DROP INDEX IF EXISTS chat_turns_goal;
  ALTER TABLE chat_turns DROP COLUMN goal_state;
  ALTER TABLE chat_turns DROP COLUMN goal_round;
  ALTER TABLE chat_turns DROP COLUMN goal_text;
  ALTER TABLE chat_turns DROP COLUMN goal_response;
  ALTER TABLE chat_turns DROP COLUMN goal_reason;
  ALTER TABLE chat_turns DROP COLUMN goal_at;
  ALTER TABLE workspaces DROP COLUMN chat_goal_rounds;
  ALTER TABLE chat_proposals DROP COLUMN goal_turns;
  DELETE FROM app_settings WHERE key LIKE 'tasks.%' OR key LIKE 'hermes.platform.%'
    OR key LIKE 'hermes.model.agos:t%'
    OR (key LIKE 'hooks.port.%' AND substr(key, 12) NOT IN (SELECT id FROM workspaces));
  DELETE FROM hermes_inbox WHERE done_at IS NOT NULL
    AND created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day');
  """,
    # A chat's model: NULL = it follows the workspace's (Hermes's own default);
    # only the owner's own pick for a chat is kept (Hermes keeps a conversation's
    # model and provider, not its reasoning effort). agos-core clears the copies
    # that equal the workspace's model when it starts (it reads Hermes then).
    """
  -- agos: foreign-keys-off
  CREATE TABLE chats_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    channel      TEXT NOT NULL CHECK (channel IN ('web','telegram')),
    model        TEXT,                             -- NULL: the workspace's (Hermes's)
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    access       TEXT NOT NULL DEFAULT 'ask' CHECK (access IN ('ask','full')),
    hermes_key   TEXT,
    deleted_at   TEXT,
    agent        TEXT,
    kind         TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat','dm','group')),
    members      TEXT NOT NULL DEFAULT '[]',
    member_id    INTEGER REFERENCES members(id) ON DELETE SET NULL,
    kanban_card  TEXT
  ) STRICT;
  INSERT INTO chats_new (id, workspace_id, title, channel, model, created_at, updated_at, access,
      hermes_key, deleted_at, agent, kind, members, member_id, kanban_card)
    SELECT id, workspace_id, title, channel, model, created_at, updated_at, access, hermes_key,
      deleted_at, agent, kind, members, member_id, kanban_card FROM chats;
  DROP TABLE chats;
  ALTER TABLE chats_new RENAME TO chats;
  CREATE UNIQUE INDEX chats_by_hermes_key ON chats (hermes_key);
  CREATE UNIQUE INDEX chats_one_dm ON chats (workspace_id, COALESCE(agent, ''))
    WHERE kind = 'dm';
  CREATE INDEX chats_member ON chats(member_id) WHERE member_id IS NOT NULL;
  CREATE UNIQUE INDEX chats_kanban_card ON chats (workspace_id, kanban_card)
    WHERE kanban_card IS NOT NULL AND deleted_at IS NULL;
  """,
    # A chat's words live in Hermes (its sessions): AGOS keeps where each message is
    # (profile, session, Hermes message id) and reads the text through agos_text(),
    # a function registered on each connection (db/hermes_text.py). The text column
    # stays for what isn't in Hermes yet.
    """
  ALTER TABLE messages RENAME TO message_rows;
  ALTER TABLE message_rows ADD COLUMN hermes_profile TEXT;
  ALTER TABLE message_rows ADD COLUMN hermes_session TEXT;
  ALTER TABLE message_rows ADD COLUMN hermes_uid TEXT;
  CREATE INDEX message_rows_unlinked ON message_rows (chat_id, id) WHERE hermes_uid IS NULL;
  CREATE VIEW messages AS
    SELECT m.id, m.chat_id, m.author,
           agos_text(m.body, m.hermes_profile, m.hermes_uid, c.workspace_id) AS body,
           m.created_at, m.speaker, m.kind, m.reply_to, m.reply_excerpt, m.edited_at,
           m.hermes_profile, m.hermes_session, m.hermes_uid
      FROM message_rows m LEFT JOIN chats c ON c.id = m.chat_id;
  """,
    # A linked message is read from its own session: Hermes copies a message (same
    # uid) into the next session when it compacts one, with a summary put in front.
    """
  DROP VIEW messages;
  CREATE VIEW messages AS
    SELECT m.id, m.chat_id, m.author,
           agos_text5(m.body, m.hermes_profile, m.hermes_session, m.hermes_uid,
                      c.workspace_id) AS body,
           m.created_at, m.speaker, m.kind, m.reply_to, m.reply_excerpt, m.edited_at,
           m.hermes_profile, m.hermes_session, m.hermes_uid
      FROM message_rows m LEFT JOIN chats c ON c.id = m.chat_id;
  """,
    # Tokens are Hermes's to count (its sessions, its Kanban): AGOS keeps no
    # per-answer copy.
    """
  UPDATE chat_turns SET usage = NULL;
  """,
    # App logins are per workspace: each workspace connects its own accounts.
    # The one shared login goes to each workspace that had the app on (its token
    # files are copied there when the core starts: apps.move_shared_logins).
    """
  CREATE TABLE workspace_app_logins (
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    app           TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('connected','error')),
    tools         TEXT NOT NULL DEFAULT '[]',     -- JSON [{name, description}]
    error         TEXT,
    connected_at  TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (workspace_id, app)
  ) STRICT;
  INSERT INTO workspace_app_logins
      (workspace_id, app, status, tools, error, connected_at, updated_at)
    SELECT a.workspace_id, c.name, c.status, c.tools, c.error, c.connected_at, c.updated_at
      FROM app_connections c JOIN workspace_apps a ON a.app = c.name AND a.enabled = 1;
  DROP TABLE app_connections;
  """,
    # MCP servers belong to ONE workspace too (like agents): created and seen only
    # inside it. Each MCP goes to the workspace that uses it (on, else with a key,
    # else any); one set up in several becomes one copy per workspace. A copy's key
    # can't move (it is sealed to the old id), so it is entered again there.
    """
  -- agos: foreign-keys-off
  CREATE TABLE library_items_v3 (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('skill','agent','mcp','plugin','tool')),
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    definition   TEXT NOT NULL DEFAULT '{}',
    source       TEXT NOT NULL DEFAULT 'created',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    CHECK (kind IN ('agent','mcp') OR workspace_id IS NULL)
  ) STRICT;
  INSERT INTO library_items_v3
    (id, kind, name, title, summary, definition, source, created_at, updated_at, workspace_id)
  SELECT l.id, l.kind, l.name, l.title, l.summary, l.definition, l.source, l.created_at,
         l.updated_at,
         CASE WHEN l.kind = 'mcp' THEN (
           SELECT c.workspace_id FROM workspace_connectors c WHERE c.item_id = l.id
           ORDER BY c.enabled DESC, (c.secret IS NOT NULL) DESC, c.workspace_id LIMIT 1)
         ELSE l.workspace_id END
  FROM library_items l;
  INSERT INTO library_items_v3
    (kind, name, title, summary, definition, source, created_at, updated_at, workspace_id)
  SELECT l.kind, l.name, l.title, l.summary, l.definition, l.source, l.created_at,
         l.updated_at, c.workspace_id
  FROM library_items l JOIN workspace_connectors c ON c.item_id = l.id
  WHERE l.kind = 'mcp' AND (c.enabled = 1 OR c.secret IS NOT NULL)
    AND c.workspace_id != (SELECT v.workspace_id FROM library_items_v3 v WHERE v.id = l.id);
  UPDATE workspace_connectors SET secret = NULL, secret_last4 = NULL,
    item_id = (SELECT v.id FROM library_items_v3 v JOIN library_items l
               ON l.id = workspace_connectors.item_id
               WHERE v.kind = 'mcp' AND v.name = l.name
                 AND v.workspace_id = workspace_connectors.workspace_id)
  WHERE item_id IN (SELECT id FROM library_items WHERE kind = 'mcp')
    AND (enabled = 1 OR secret IS NOT NULL)
    AND workspace_id != (SELECT v.workspace_id FROM library_items_v3 v
                         WHERE v.id = workspace_connectors.item_id);
  DELETE FROM workspace_connectors
  WHERE item_id IN (SELECT id FROM library_items_v3 WHERE kind = 'mcp')
    AND workspace_id IS NOT (SELECT v.workspace_id FROM library_items_v3 v
                             WHERE v.id = workspace_connectors.item_id);
  DROP TABLE library_items;
  ALTER TABLE library_items_v3 RENAME TO library_items;
  CREATE UNIQUE INDEX library_items_unique ON library_items (kind, name, COALESCE(workspace_id, ''));
  CREATE INDEX library_items_by_workspace ON library_items (workspace_id);
  """,
    # Composio can also be on through the owner's project key: the workspace is its
    # own Composio user, with a session (its MCP server) kept here.
    """
  ALTER TABLE workspace_app_logins ADD COLUMN via TEXT NOT NULL DEFAULT 'login'
    CHECK (via IN ('login', 'key'));
  ALTER TABLE workspace_app_logins ADD COLUMN session TEXT;
  """,
    # His Telegram messages AGOS has answered itself (a group's or a member's topic):
    # Hermes keeps its 👀 on them until that answer is out, then Hermes's own
    # reaction (👍 / 👎) replaces it.
    """
  CREATE TABLE channel_reactions (
    id            INTEGER PRIMARY KEY,
    connection_id INTEGER NOT NULL REFERENCES channel_connections(id) ON DELETE CASCADE,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    tg_chat       TEXT NOT NULL,                 -- Telegram chat id
    tg_message    TEXT NOT NULL,                 -- his message there
    created_at    TEXT NOT NULL,
    outcome       TEXT CHECK (outcome IN ('success','failure','cancelled')),
    claimed_at    TEXT,
    done_at       TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (connection_id, tg_chat, tg_message)
  ) STRICT;
  CREATE INDEX channel_reactions_waiting ON channel_reactions (connection_id)
    WHERE done_at IS NULL;
  """,
    # A group chat of a workspace on its own Hermes root is a Hermes hosted room
    # (ADR 0020): which room it is now, how far AGOS has read its log, the room's
    # events AGOS took (each once, across restarts), and member approvals.
    """
  CREATE TABLE group_rooms (
    chat_id        INTEGER PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
    workspace_id   TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    room_id        TEXT NOT NULL,
    generation     INTEGER NOT NULL DEFAULT 1,
    roster         TEXT NOT NULL,
    cursor         INTEGER NOT NULL DEFAULT 0,
    state          TEXT NOT NULL DEFAULT 'wanted' CHECK (state IN ('wanted','ready','failed')),
    error          TEXT,
    discussion     TEXT,
    last_member    TEXT,
    continuations  INTEGER NOT NULL DEFAULT 0,
    recap          TEXT,
    updated_at     TEXT NOT NULL,
    UNIQUE (workspace_id, room_id)
  ) STRICT;
  CREATE TABLE room_events (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    room_id      TEXT NOT NULL,
    event_id     TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    message_id   INTEGER,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, room_id, event_id)
  ) STRICT;
  CREATE TABLE room_approvals (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id         TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chat_id              INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    room_id              TEXT NOT NULL,
    member_id            TEXT NOT NULL,
    task_id              TEXT NOT NULL,
    execution_generation INTEGER NOT NULL,
    request_id           TEXT NOT NULL,
    command              TEXT NOT NULL DEFAULT '',
    description          TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    answered_at          TEXT,
    choice               TEXT CHECK (choice IN ('once','deny')),
    UNIQUE (workspace_id, room_id, request_id)
  ) STRICT;
  CREATE INDEX room_approvals_open ON room_approvals (chat_id) WHERE answered_at IS NULL;
  """,
    # What a workspace has on lives in its Hermes config now (actions/hermes_config.py):
    # the owner's notes on a skill, tool, plugin or MCP server of a workspace (shown in
    # AGOS only) get their own table; the rest of those rows moves into each root at
    # the workspace's next apply, then the rows go.
    """
  CREATE TABLE connector_notes (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    notes        TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, item_id)
  ) STRICT;
  INSERT INTO connector_notes (workspace_id, item_id, notes, updated_at)
    SELECT c.workspace_id, c.item_id, c.local, c.updated_at
      FROM workspace_connectors c JOIN library_items l ON l.id = c.item_id
     WHERE l.kind != 'agent' AND c.local != '';
  """,
    # Leftovers nothing writes or reads any more: the proposals of older chats and
    # automation runs (agents put cards on Hermes's Kanban), AGOS's old run index
    # and webhook deliveries (Hermes's cron and webhook routes keep them), the
    # Telegram poller's seen list, the workspace identity column (SOUL.md is its
    # only home), unused group-room and channel columns.
    """
  DROP TABLE IF EXISTS chat_proposals;
  DROP TABLE IF EXISTS automation_proposals;
  DROP TABLE IF EXISTS automation_runs;
  DROP TABLE IF EXISTS automation_proposed;
  DROP TABLE IF EXISTS automation_events;
  DROP TABLE IF EXISTS channel_seen;
  ALTER TABLE workspaces DROP COLUMN identity;
  ALTER TABLE group_rooms DROP COLUMN continuations;
  ALTER TABLE group_rooms DROP COLUMN recap;
  ALTER TABLE channel_connections DROP COLUMN relay;
  ALTER TABLE channel_connections DROP COLUMN cursor;
  """,
    # A chat or DM is its Hermes conversation (db/hermes_chats.py): its words, titles,
    # model and steps are read from Hermes. AGOS's rows of those chats are marked
    # `legacy`: they are moved into Hermes once (actions/chat_store.py) and go, except
    # AGOS's own notices. A file of his message is kept by the queue item it went to
    # Hermes as (`inbox_id`) or by its Hermes message (`hermes_uid`), in its chat. An
    # edit of an older message is kept by the id the web shows (`hermes` = 1).
    """
  -- agos: foreign-keys-off
  CREATE TABLE message_attachments_new (
    id          INTEGER PRIMARY KEY,
    message_id  INTEGER REFERENCES "message_rows"(id) ON DELETE CASCADE,
    chat_id     INTEGER REFERENCES chats(id) ON DELETE CASCADE,
    inbox_id    INTEGER,
    hermes_uid  TEXT,
    kind        TEXT NOT NULL CHECK (kind IN ('image','audio','file')),
    name        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    path        TEXT NOT NULL,
    duration    REAL,
    transcript  TEXT
  ) STRICT;
  INSERT INTO message_attachments_new
      (id, message_id, chat_id, kind, name, mime, size, path, duration, transcript)
    SELECT a.id, a.message_id, m.chat_id, a.kind, a.name, a.mime, a.size, a.path, a.duration,
           a.transcript
      FROM message_attachments a LEFT JOIN message_rows m ON m.id = a.message_id;
  DROP TABLE message_attachments;
  ALTER TABLE message_attachments_new RENAME TO message_attachments;
  CREATE INDEX message_attachments_by_message ON message_attachments (message_id, id);
  CREATE INDEX message_attachments_by_chat ON message_attachments (chat_id, inbox_id);
  ALTER TABLE message_rows ADD COLUMN legacy INTEGER NOT NULL DEFAULT 0;
  UPDATE message_rows SET legacy = 1
   WHERE chat_id IN (SELECT id FROM chats WHERE kind != 'group');
  ALTER TABLE chat_edits ADD COLUMN hermes INTEGER NOT NULL DEFAULT 0;
  DROP VIEW messages;
  CREATE VIEW messages AS
    SELECT m.id, m.chat_id, m.author,
           agos_text5(m.body, m.hermes_profile, m.hermes_session, m.hermes_uid,
                      c.workspace_id) AS body,
           m.created_at, m.speaker, m.kind, m.reply_to, m.reply_excerpt, m.edited_at,
           m.hermes_profile, m.hermes_session, m.hermes_uid, m.legacy
      FROM message_rows m LEFT JOIN chats c ON c.id = m.chat_id;
  INSERT OR IGNORE INTO app_settings (key, value, updated_at)
    VALUES ('channels.hermes_replies_since',
            '"' || strftime('%Y-%m-%dT%H:%M:%fZ', 'now') || '"',
            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
  """,
    # Access, Autonomy and who may write to the bot are Hermes's own now: the
    # workspace's switch is its profiles' approvals.mode, a chat's is Hermes's
    # per-conversation /yolo, the Autonomy rules are the agos-guard plugin's file,
    # and the bot's people are Hermes's allowlist and DM pairing. The old AGOS
    # copies wait in hermes_moves until the core has written each into Hermes
    # (actions/hermes_moves.py, at start), then their columns and table go.
    """
  CREATE TABLE hermes_moves (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL
                 CHECK (kind IN ('access','chat_access','autonomy','telegram_allowed')),
    ref          TEXT NOT NULL DEFAULT '',
    value        TEXT NOT NULL,
    PRIMARY KEY (workspace_id, kind, ref)
  ) STRICT;
  INSERT INTO hermes_moves (workspace_id, kind, ref, value)
    SELECT id, 'access', '', chat_access FROM workspaces;
  INSERT INTO hermes_moves (workspace_id, kind, ref, value)
    SELECT workspace_id, 'chat_access', CAST(id AS TEXT), 'full' FROM chats
     WHERE access = 'full' AND deleted_at IS NULL AND kind != 'group';
  INSERT INTO hermes_moves (workspace_id, kind, ref, value)
    SELECT workspace_id, 'autonomy', agent || ' ' || action, choice FROM autonomy_rules;
  INSERT INTO hermes_moves (workspace_id, kind, ref, value)
    SELECT workspace_id, 'telegram_allowed', CAST(id AS TEXT), allowed
      FROM channel_connections
     WHERE workspace_id IS NOT NULL AND kind = 'telegram' AND allowed != '[]';
  ALTER TABLE workspaces DROP COLUMN chat_access;
  ALTER TABLE chats DROP COLUMN access;
  DROP TABLE autonomy_rules;
  ALTER TABLE channel_connections DROP COLUMN allowed;
  ALTER TABLE channel_connections DROP COLUMN claim_code;
  ALTER TABLE channel_connections DROP COLUMN claim_expires;
  """,
    # Dead leftovers go. Columns nothing writes or reads any more (a turn's old
    # queue/note/handoffs, the old "notified" flags, a Co-Founder action's run, a
    # connector's last 4). Transitional copies whose moves into Hermes are done on
    # the live install (all empty): hermes_moves (Access, Autonomy, the bot's people
    # are Hermes's), owner_rules (Hermes's USER.md), workspace_apps (Hermes's
    # mcp_servers) and the automations' hook_* columns (Hermes's webhook routes).
    # The live install had no row left in any of them (checked 2026-10-16).
    """
  DROP INDEX IF EXISTS manager_actions_by_run;
  DROP INDEX IF EXISTS automations_by_hook;
  ALTER TABLE chat_turns DROP COLUMN note;
  ALTER TABLE chat_turns DROP COLUMN queue;
  ALTER TABLE chat_turns DROP COLUMN handoffs;
  ALTER TABLE capability_requests DROP COLUMN notified;
  ALTER TABLE manager_actions DROP COLUMN notified;
  ALTER TABLE manager_actions DROP COLUMN run_id;
  ALTER TABLE workspace_connectors DROP COLUMN secret_last4;
  ALTER TABLE automations DROP COLUMN hook_token;
  ALTER TABLE automations DROP COLUMN hook_secret;
  ALTER TABLE automations DROP COLUMN hook_filter;
  DROP TABLE hermes_moves;
  DROP TABLE owner_rules;
  DROP TABLE workspace_apps;
  """,
    # A bot's lamp is Hermes's own state of it, read live from its gateway's
    # gateway_state.json (actions/hermes_channel.py `channel_state`): AGOS's cached
    # copy goes. The bot's @name stays (Hermes keeps it only in its running adapter).
    """
  ALTER TABLE channel_connections DROP COLUMN status;
  ALTER TABLE channel_connections DROP COLUMN status_reason;
  ALTER TABLE channel_connections DROP COLUMN last_ok_at;
  """,
    # A Hermes chat's tokens, model and how its turns ended are Hermes's own
    # (messages.token_count, session_model_usage, its sessions, agent.log "Turn
    # ended"; db/hermes_turns.py): AGOS's copies on its turn records go. `model`
    # stays only for answers from before steps were Hermes's (nothing writes it).
    """
  ALTER TABLE chat_turns DROP COLUMN usage;
  ALTER TABLE chat_turns DROP COLUMN provider;
  """,
    # Dead columns and the last copies from before Hermes held each thing go
    # (step 17). Dead: automations.job_digest (the Hermes job prompt is the one copy),
    # chat_turns.model (a turn's model is Hermes's), group_rooms.last_member and
    # activity.task_id (nothing writes them). Transitional, their moves done and
    # gone (db/leftovers.py checks first and keeps anything left in a file):
    # workspace_connectors and a workspace's MCP definitions (the root's Hermes
    # config), the agent rows' text (member profiles), the bot token copies
    # (channel_connections.secret; secret_last4 too: the token's end is read from the
    # workspace's .env), old message copies and their Hermes links (Hermes's
    # sessions), chats.title_told.* and owner.timezone (Hermes has them). Copies of
    # Hermes's own state go too: a skill's summary (its SKILL.md description), the
    # webhook port (WEBHOOK_PORT in the workspace's .env), the keys' last 4 in
    # provider_keys and tools.services (read from Hermes's .env).
    """
  -- agos: leftovers
  ALTER TABLE automations DROP COLUMN job_digest;
  ALTER TABLE chat_turns DROP COLUMN model;
  ALTER TABLE group_rooms DROP COLUMN last_member;
  ALTER TABLE activity DROP COLUMN task_id;
  DROP TABLE workspace_connectors;
  UPDATE library_items SET definition = '{}'
   WHERE kind = 'mcp' AND workspace_id IS NOT NULL AND definition NOT IN ('{}', '');
  UPDATE library_items SET title = '', summary = '', definition = '{}', source = 'hermes'
   WHERE kind = 'agent' AND (title != '' OR definition NOT IN ('{}', ''));
  ALTER TABLE channel_connections DROP COLUMN secret;
  ALTER TABLE channel_connections DROP COLUMN secret_last4;
  DELETE FROM message_rows WHERE legacy = 1;
  DROP VIEW messages;
  DROP INDEX IF EXISTS message_rows_unlinked;
  ALTER TABLE message_rows DROP COLUMN hermes_profile;
  ALTER TABLE message_rows DROP COLUMN hermes_session;
  ALTER TABLE message_rows DROP COLUMN hermes_uid;
  ALTER TABLE message_rows DROP COLUMN legacy;
  CREATE VIEW messages AS
    SELECT id, chat_id, author, body, created_at, speaker, kind, reply_to, reply_excerpt,
           edited_at
      FROM message_rows;
  DELETE FROM app_settings WHERE key LIKE 'chats.title_told.%' OR key = 'owner.timezone';
  UPDATE library_items SET summary = '' WHERE kind = 'skill';
  DELETE FROM app_settings WHERE key LIKE 'hooks.port.%' OR key = 'legacy.task_sessions_upto';
  UPDATE app_settings SET value = (
      SELECT json_group_object(p.key, json_object(
               'tested', coalesce(json_extract(p.value, '$.tested'), '')))
        FROM json_each(app_settings.value) p)
   WHERE key = 'provider_keys' AND json_valid(value) AND json_type(value) = 'object';
  UPDATE app_settings SET value = (
      SELECT json_group_object(t.key, json_object(
               'provider', json_extract(t.value, '$.provider'),
               'keys', CASE json_type(t.value, '$.keys')
                         WHEN 'object' THEN (SELECT json_group_array(k.key)
                                               FROM json_each(t.value, '$.keys') k)
                         WHEN 'array' THEN json_extract(t.value, '$.keys')
                         ELSE json_array() END))
        FROM json_each(app_settings.value) t)
   WHERE key = 'tools.services' AND json_valid(value) AND json_type(value) = 'object';
  """,
    # Library rows keep no copy of what Hermes holds: a tool (a Hermes toolset) keeps
    # only its id (its label and words are Hermes's catalog, engine/hermes_tools);
    # a skill keeps no title equal to its SKILL.md name (a display name the owner
    # gave it stays: Hermes has no field for one).
    """
  UPDATE library_items SET title = '', summary = '', definition = '{}' WHERE kind = 'tool';
  UPDATE library_items SET title = '' WHERE kind = 'skill' AND title = name;
  """,
    # Hermes's "/" menu is read from Hermes's own registry each time
    # (engine command_menu): AGOS's copy, pushed by the plugin, goes.
    """
  DELETE FROM app_settings WHERE key LIKE 'hermes.commands.%';
  """,
    # Step 23: the workspace's old Telegram group (workspaces.telegram_group/topic,
    # no reader left; the web showed it as "Saved from before") joins the places a
    # chat can be linked to (actions/hermes_channel GROUPS_KEY, what Hermes's channel
    # directory lacks), then the columns go.
    """
  -- agos: old workspace Telegram group into the places
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'telegram.groups.' || id, '{}', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM workspaces WHERE telegram_group GLOB '-[0-9]*'
    ON CONFLICT (key) DO NOTHING;
  UPDATE app_settings SET value = (
      SELECT json_set(app_settings.value, '$."' || w.telegram_group || '"',
               json_object('name', '', 'topics',
                 CASE WHEN coalesce(w.telegram_topic, '') GLOB '[0-9]*'
                       AND w.telegram_topic NOT IN ('0', '1')
                      THEN json_object('0', '', w.telegram_topic, '')
                      ELSE json_object('0', '') END))
        FROM workspaces w WHERE app_settings.key = 'telegram.groups.' || w.id)
   WHERE json_valid(value) AND json_type(value) = 'object'
     AND EXISTS (SELECT 1 FROM workspaces w
                  WHERE app_settings.key = 'telegram.groups.' || w.id
                    AND w.telegram_group GLOB '-[0-9]*'
                    AND json_type(app_settings.value, '$."' || w.telegram_group || '"') IS NULL);
  ALTER TABLE workspaces DROP COLUMN telegram_group;
  ALTER TABLE workspaces DROP COLUMN telegram_topic;
  """,
    # Step 23: a chat's model is Hermes's own /model for its conversation (model,
    # provider); AGOS keeps only the reasoning effort Hermes forgets on a restart
    # (actions/hermes_channel.py EFFORT_KEY). His picks in chats.model wait in
    # app_settings until the core start tells Hermes (hermes_channel.move_old_models).
    """
  -- agos: chats.model into Hermes
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'chats.model.move.' || id, model, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM chats WHERE model IS NOT NULL AND json_valid(model) AND deleted_at IS NULL
    ON CONFLICT (key) DO NOTHING;
  ALTER TABLE chats DROP COLUMN model;
  """,
    # Step 23: an automation's on/off is its Hermes cron job's `enabled` alone; AGOS's
    # column holds it only while Hermes refused it (sync_error). Where Hermes has the
    # job, the copy goes (back to 0, the column is NOT NULL).
    """
  -- agos: automations.enabled only while Hermes refused it
  UPDATE automations SET enabled = 0
   WHERE hermes_job_id IS NOT NULL AND sync_error IS NULL;
  """,
    # Step 26: Hermes's toolset catalog is read from Hermes (engine/hermes_tools,
    # in memory only); AGOS's saved copy goes.
    """
  DELETE FROM app_settings WHERE key = 'hermes.tools_catalog';
  """,
    # Step 26: the added folders are Hermes's terminal.docker_volumes alone. Rows a
    # workspace's sync hasn't moved yet wait in app_settings (folders.move.<ws>,
    # read by db/workspaces.legacy_folders until the next sync puts them into
    # Hermes, then deleted); the old table goes. An old backup restores through
    # this same step.
    """
  -- agos: old added folders wait for their Hermes, then the table goes
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'folders.move.' || workspace_id,
           json_group_array(json_object('name', name, 'host_path', host_path, 'access', access)),
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM (SELECT * FROM workspace_folders ORDER BY workspace_id, name)
     GROUP BY workspace_id
    ON CONFLICT (key) DO NOTHING;
  DROP TABLE workspace_folders;
  """,
    # Step 26: a finished answer's thoughts, notes and helpers are read from Hermes's
    # session (db/hermes_chats.py steps_between: the content of its tool-calling rows,
    # its delegate_task calls and results; Hermes always had them, they were what it
    # relayed live). AGOS's record keeps only the approvals (actions/turn_steps.kept).
    """
  -- agos: chat_turns.activity keeps only the approvals
  UPDATE chat_turns SET activity = json_object('kept', json((
      SELECT json_group_array(json(k.value)) FROM json_each(chat_turns.activity, '$.kept') k
       WHERE json_extract(k.value, '$.kind') = 'approval')))
   WHERE json_valid(activity) AND json_type(activity, '$.kept') = 'array'
     AND EXISTS (SELECT 1 FROM json_each(chat_turns.activity, '$.kept') k
                  WHERE coalesce(json_extract(k.value, '$.kind'), '') != 'approval');
  """,
    # Step 26: a room member's waiting approval is Hermes's own (its room service's
    # pending set, HostedRoomService.status()["pending_actions"]); the plugin reports
    # it with every room-next and AGOS holds only what it was told, in memory
    # (actions/rooms.py). Hermes's set is in memory too: one Hermes still waits on is
    # told again, one it dropped can't be answered any more. The copy goes.
    """
  -- agos: room_approvals are Hermes's
  DROP TABLE IF EXISTS room_approvals;
  """,
    # Step 26: a room's members are Hermes's (its hosted-room row, made by create_room;
    # the plugin reports them with every room-next). AGOS's master stays the group's
    # members (chats.members), compared with Hermes's room to know when to make it
    # again. A room Hermes hasn't made yet has its members in its room-sync job.
    """
  -- agos: group_rooms.roster is Hermes's
  ALTER TABLE group_rooms DROP COLUMN roster;
  """,
    # Step 27: the Daily digest's clock is a Hermes no-agent cron job in each root
    # (actions/digest.py); AGOS's "sent today" mark is gone.
    """
  -- agos: the digest's clock is Hermes's cron
  DELETE FROM app_settings WHERE key LIKE 'digest.sent.%';
  """,
    # Step 27: a voice note's words in a Hermes chat are Hermes's (the message Hermes
    # keeps: its own transcript, or AGOS's "[Voice note, transcribed] …" it was handed,
    # read by db/hermes_chats.py owner_words). AGOS writes them only for a room line,
    # its own line (db/chats.py set_transcript); any copy on a Hermes chat's file goes.
    """
  -- agos: a Hermes chat's voice words are Hermes's
  UPDATE message_attachments SET transcript = NULL
   WHERE message_id IS NULL AND transcript IS NOT NULL;
  """,
    # Step 27: a workspace's one-line description is its Co-Founder's Hermes description
    # (the root profile's profile.yaml `description`, hermes_cli/profiles.py
    # write_profile_meta / `hermes profile describe`). Old rows wait under
    # workspace.description.move.<ws> until the workspace's next sync puts them into
    # Hermes (actions/engine.py move_description, which then deletes them).
    """
  -- agos: a workspace's description is its Manager's Hermes description
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'workspace.description.move.' || id, json_quote(description),
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM workspaces WHERE trim(description) != ''
    ON CONFLICT (key) DO NOTHING;
  ALTER TABLE workspaces DROP COLUMN description;
  """,
    # Step 27: how a provider key did is Hermes's: its credential pool's last_status
    # (agent/credential_pool.py PooledCredential, read by engine/key_status.py). AGOS's
    # record of when it last tested one goes.
    """
  DELETE FROM app_settings WHERE key = 'provider_keys';
  """,
    # Step 27: a bot's on/off is Hermes's own platforms.telegram.enabled (an explicit
    # false wins over the token in .env, gateway/config_env.py _enable_from_env); the
    # token stays in .env either way. A bot AGOS had turned off waits under
    # telegram.off.move.<ws> until hermes_channel.move_old_switches puts the off into
    # Hermes (then deleted); the column goes.
    """
  -- agos: a bot's on/off is Hermes's platforms.telegram.enabled
  INSERT INTO app_settings (key, value, updated_at)
    SELECT DISTINCT 'telegram.off.move.' || workspace_id, 'true',
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM channel_connections
     WHERE enabled = 0 AND workspace_id IS NOT NULL AND kind = 'telegram'
    ON CONFLICT (key) DO NOTHING;
  ALTER TABLE channel_connections DROP COLUMN enabled;
  """,
    # Step 28 (117): a card's chat is with the member Hermes has on the card now
    # (its Kanban task's assignee): a reassigned card gets a chat with its new member
    # (the old conversation stays in the old member's profile, where Hermes keeps it).
    """
  DROP INDEX IF EXISTS chats_kanban_card;
  CREATE UNIQUE INDEX chats_kanban_card ON chats (workspace_id, kanban_card, COALESCE(agent, ''))
    WHERE kanban_card IS NOT NULL AND deleted_at IS NULL;
  """,
    # Step 28 (118): a workspace's name is its Co-Founder's Hermes display name (the root
    # profile's profile.yaml display_name, hermes_cli/profiles.py write_profile_meta).
    # Every name waits under workspace.name.move.<ws> until actions/engine.py
    # move_name puts it into Hermes (at start and at every sync), then it's deleted.
    """
  -- agos: a workspace's name is its Manager's Hermes display name
  INSERT INTO app_settings (key, value, updated_at)
    SELECT 'workspace.name.move.' || id, json_quote(name),
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
      FROM workspaces WHERE true
    ON CONFLICT (key) DO NOTHING;
  ALTER TABLE workspaces DROP COLUMN name;
  """,
    # Step 29 (119): a Telegram place's name is read from Hermes's channel directory
    # (actions/hermes_channel.py place_names); the label AGOS kept was a snapshot of
    # the chat's title, stale after a rename. Nothing to move.
    """
  -- agos: a linked place's name is Hermes's (channel_directory.json)
  ALTER TABLE chat_addresses DROP COLUMN label;
  """,
    # Step 29 (120): a deleted team login's chats keep who had them beside the title
    # (chats.former_member), no longer as a "[name] " prefix written into chats.title
    # (a chat's title is its Hermes session's). Old markers move there once.
    """
  -- agos: who had a chat, after that team login was deleted
  ALTER TABLE chats ADD COLUMN former_member TEXT NOT NULL DEFAULT '';
  UPDATE chats
     SET former_member = substr(title, 2, instr(title, '] ') - 2),
         title = substr(title, instr(title, '] ') + 2)
   WHERE member_id IS NULL AND kind = 'chat' AND title GLOB '[[]?*] *';
  """,
    # Step 30 (121): a Co-Founder pool action's sealed API key is kept only while AGOS
    # still needs it (actions/cofounder_actions.py _drop_sealed); once the action is
    # done, declined or undone, Hermes's managed .env holds the key (or it was never
    # added). Old copies are cleared once.
    """
  -- agos: no sealed key copy on settled Manager actions
  UPDATE manager_actions SET payload = json_remove(payload, '$.key_sealed')
   WHERE status IN ('done', 'rejected', 'undone') AND json_valid(payload)
     AND json_extract(payload, '$.key_sealed') IS NOT NULL;
  UPDATE manager_actions SET result = json_remove(result, '$.sealed')
   WHERE status = 'undone' AND json_valid(result)
     AND json_extract(result, '$.sealed') IS NOT NULL;
  """,
    # Step 32 (122): the last old copies of Hermes data (db/old_copies.py moves the
    # files and writes the rows into the backups folder first): chat answers' whole
    # tool steps in a plain chat or DM (Hermes's sessions hold them; their approvals
    # stay), app_settings keys no code reads, and the on/off of a webhook-only
    # automation (its Hermes route's).
    """
  -- agos: old copies (step 32)
  DELETE FROM app_settings
   WHERE key IN ('chats.words_in_hermes', 'telegram.menus', 'tools.default_on')
      OR key GLOB 'kanban.seen.*' OR key GLOB 'kanban.asked.*';
  UPDATE chat_turns
     SET activity = json_object('kept', (
           SELECT json_group_array(json(j.value))
             FROM json_each(json_extract(chat_turns.activity, '$.own')) j
            WHERE json_extract(j.value, '$.kind') = 'approval'))
   WHERE id IN (SELECT t.id FROM chat_turns t JOIN chats c ON c.id = t.chat_id
                 WHERE c.kind IN ('chat', 'dm') AND json_valid(t.activity)
                   AND json_type(t.activity, '$.own') IS NOT NULL);
  UPDATE automations SET enabled = 0
   WHERE hermes_job_id IS NULL AND schedule = '' AND COALESCE(sync_error, '') = ''
     AND enabled = 1;
  """,
    # Installed app (123): the browsers (his phone) that asked for AGOS's own
    # notifications (actions/web_push.py). One row per browser subscription.
    """
  -- agos: web push subscriptions
  CREATE TABLE push_subscriptions (
    id         INTEGER PRIMARY KEY,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    label      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    seen_at    TEXT NOT NULL
  ) STRICT;
  """,
    # Skills belong to ONE workspace too (like agents and MCP servers): a row with
    # its workspace; its folder is that workspace's own (<root>/skills/agos-library).
    # The old shared rows are moved by actions/skills_move.py at start.
    """
  -- agos: foreign-keys-off
  CREATE TABLE library_items_v4 (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('skill','agent','mcp','plugin','tool')),
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    definition   TEXT NOT NULL DEFAULT '{}',
    source       TEXT NOT NULL DEFAULT 'created',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    CHECK (kind IN ('agent','mcp','skill') OR workspace_id IS NULL)
  ) STRICT;
  INSERT INTO library_items_v4
    (id, kind, name, title, summary, definition, source, created_at, updated_at, workspace_id)
  SELECT id, kind, name, title, summary, definition, source, created_at, updated_at,
         workspace_id
  FROM library_items;
  DROP TABLE library_items;
  ALTER TABLE library_items_v4 RENAME TO library_items;
  CREATE UNIQUE INDEX library_items_unique ON library_items (kind, name, COALESCE(workspace_id, ''));
  CREATE INDEX library_items_by_workspace ON library_items (workspace_id);
  """,
    # Step 43 (125): proposals on top of the card asks. An agent proposes (a hire,
    # a change to its own instructions, a plan) as a Hermes Kanban card it blocks
    # for the owner; AGOS keeps one row per proposal round with its kind and
    # payload (the card body holds the same, Hermes-side), the owner's decision
    # (approve / revise / reject) and what Undo needs (actions/proposals.py).
    """
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
                                   'approved','revised','rejected','undone')),
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    kind         TEXT NOT NULL DEFAULT 'ask'
                 CHECK (kind IN ('ask','hire','instructions','plan')),
    payload      TEXT NOT NULL DEFAULT '',
    round        INTEGER NOT NULL DEFAULT 1,
    note         TEXT,
    result       TEXT
  ) STRICT;
  INSERT INTO kanban_asks_new (id, workspace_id, card, member, action, label, detail, status,
      created_at, decided_at)
    SELECT id, workspace_id, card, member, action, label, detail, status, created_at,
      decided_at FROM kanban_asks;
  DROP TABLE kanban_asks;
  ALTER TABLE kanban_asks_new RENAME TO kanban_asks;
  CREATE UNIQUE INDEX kanban_asks_once ON kanban_asks (workspace_id, card, action)
    WHERE status = 'waiting';
  CREATE INDEX kanban_asks_by_ws ON kanban_asks (workspace_id, status);
  """,
    # Step 44 (126): the workspace's root bot is the Co-Founder (it was called the
    # Manager): its table, its settings key, its DM's title and the Office look's
    # key take the new name; the old cards' snapshot file (step 32) is renamed by
    # actions/cofounder_move.py at start, so the rows that point at it follow here.
    """
  -- agos: the Manager is the Co-Founder (step 44)
  -- agos: rename-table manager_actions cofounder_actions
  DROP INDEX IF EXISTS manager_actions_by_turn;
  CREATE INDEX IF NOT EXISTS cofounder_actions_by_turn ON cofounder_actions (turn_id);
  UPDATE chats SET title = 'Co-Founder' WHERE kind = 'dm' AND agent IS NULL AND title = 'Manager';
  UPDATE app_settings SET key = 'cofounder.actions' WHERE key = 'manager.actions'
    AND NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'cofounder.actions');
  DELETE FROM app_settings WHERE key = 'manager.actions';
  UPDATE app_settings
    SET value = json_set(json_remove(value, '$.manager'), '$.cofounder',
                         json(json_extract(value, '$.manager')))
    WHERE key LIKE 'office.%' AND json_valid(value) AND json_type(value, '$.manager') = 'object'
      AND json_type(value, '$.cofounder') IS NULL;
  UPDATE app_settings SET value = json_remove(value, '$.manager')
    WHERE key LIKE 'office.%' AND json_valid(value) AND json_type(value, '$.manager') IS NOT NULL;
  UPDATE cofounder_actions
    SET result = replace(result, 'manager-actions-before-step32.json',
                                 'cofounder-actions-before-step32.json')
    WHERE result LIKE '%manager-actions-before-step32.json%';
  """,
    # Step 45 (127): typed questions to the owner ride on the asks (kind 'question',
    # status 'answered'; the card body holds the agos-question block, Hermes-side);
    # the Inbox keeps only what the owner marked read or dismissed (every item is
    # derived from Hermes's board and AGOS's asks); a subtree hold (Pause / Cancel
    # of a card and its descendants) records exactly which Hermes cards it moved,
    # so Resume releases those and nothing else (actions/holds.py). Replayable:
    # the asks rebuild copies every column, the new tables are IF NOT EXISTS.
    """
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
                 CHECK (kind IN ('ask','hire','instructions','plan','question')),
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
  CREATE UNIQUE INDEX kanban_asks_once ON kanban_asks (workspace_id, card, action)
    WHERE status = 'waiting';
  CREATE INDEX kanban_asks_by_ws ON kanban_asks (workspace_id, status);
  CREATE TABLE IF NOT EXISTS inbox_marks (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    key          TEXT NOT NULL,
    mark         TEXT NOT NULL CHECK (mark IN ('read','dismissed')),
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, key, mark)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS kanban_holds (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    root_card    TEXT NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('pause','cancel')),
    held         TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    released_at  TEXT
  ) STRICT;
  CREATE INDEX IF NOT EXISTS kanban_holds_by_root ON kanban_holds (workspace_id, root_card);
  """,
    # Step 46 (128): Skill Studio test runs. The run itself is a Hermes Kanban card
    # (its body carries the rendered test and an `agos-skill-test` block); AGOS keeps
    # what Hermes has no record for: a skill's saved test inputs (with an expected
    # output each), its run template and grading checklist, and each run's link to
    # its card with the output taken from the card and the grader's verdict
    # (actions/skill_tests.py). Idempotent on replay (IF NOT EXISTS).
    """
  CREATE TABLE IF NOT EXISTS skill_test_inputs (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    text         TEXT NOT NULL,
    expected     TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS skill_test_inputs_by_item ON skill_test_inputs (item_id);
  CREATE TABLE IF NOT EXISTS skill_test_settings (
    item_id      INTEGER PRIMARY KEY REFERENCES library_items(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    template     TEXT NOT NULL DEFAULT '',
    checklist    TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
  ) STRICT;
  CREATE TABLE IF NOT EXISTS skill_test_runs (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    input_id     INTEGER REFERENCES skill_test_inputs(id) ON DELETE SET NULL,
    input_name   TEXT NOT NULL,
    input_text   TEXT NOT NULL,
    expected     TEXT NOT NULL DEFAULT '',
    checklist    TEXT NOT NULL DEFAULT '',
    version      INTEGER NOT NULL,
    member       TEXT NOT NULL DEFAULT '',
    card         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','blocked','done','lost')),
    output       TEXT NOT NULL DEFAULT '',
    grade        TEXT CHECK (grade IN ('pass','fail','error')),
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    finished_at  TEXT,
    graded_at    TEXT
  ) STRICT;
  CREATE INDEX IF NOT EXISTS skill_test_runs_by_item ON skill_test_runs (item_id, id);
  """,
    # Step 48 (129): routines. An automation's typed variables (interpolated as
    # {name} into its cards and prompt), its concurrency policy (what a trigger does
    # while the last run's cards are still open) and its ticket on-ramp mapping
    # (Linear / Jira / Asana / GitHub issues → one card per issue) are AGOS's plan,
    # which Hermes's job and route don't hold. Each save appends a snapshot row
    # (automation_revisions): Hermes's cron keeps the job, not its history. A task
    # watchdog (kanban_watchdogs) keeps the last stop fingerprint of a card's
    # subtree, so its Hermes cron job wakes the agent once per stop. Idempotent on
    # replay (ensure-column, IF NOT EXISTS).
    """
  -- agos: ensure-column automations.variables TEXT
  -- agos: ensure-column automations.policy TEXT
  -- agos: ensure-column automations.ticket TEXT
  CREATE TABLE IF NOT EXISTS automation_revisions (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    n             INTEGER NOT NULL,
    snapshot      TEXT NOT NULL,
    who           TEXT NOT NULL DEFAULT 'owner',
    summary       TEXT NOT NULL DEFAULT '',
    restored_from INTEGER,
    created_at    TEXT NOT NULL,
    UNIQUE (automation_id, n)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS kanban_watchdogs (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    root_card     TEXT NOT NULL,
    hermes_job_id TEXT,
    fingerprint   TEXT NOT NULL DEFAULT '',
    acts          INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    observed_at   TEXT,
    acted_at      TEXT,
    escalated_at  TEXT,
    UNIQUE (workspace_id, root_card)
  ) STRICT;
  """,
    # Step 49 (130): a card's documents live as files in the workspace folder (every
    # revision a file too: actions/card_docs.py); AGOS keeps only what Hermes has no
    # record for: the owner's passage comments anchored in a document (and where
    # each one is after every revision), his review of an artifact (a Hermes card
    # attachment or a card document), and his 👍/👎 on a reply or a document
    # revision (said into Hermes's learning conversation; the row shows the count).
    # Idempotent on replay (IF NOT EXISTS).
    """
  CREATE TABLE IF NOT EXISTS card_doc_annotations (
    id                INTEGER PRIMARY KEY,
    workspace_id      TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    card              TEXT NOT NULL,
    key               TEXT NOT NULL,
    revision          INTEGER NOT NULL,
    quote             TEXT NOT NULL,
    prefix            TEXT NOT NULL DEFAULT '',
    suffix            TEXT NOT NULL DEFAULT '',
    pos_start         INTEGER NOT NULL,
    pos_end           INTEGER NOT NULL,
    body              TEXT NOT NULL,
    author            TEXT NOT NULL DEFAULT 'Owner',
    anchor            TEXT NOT NULL DEFAULT 'active'
                      CHECK (anchor IN ('active','stale','orphaned')),
    anchored_revision INTEGER NOT NULL,
    resolved_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS card_doc_annotations_by_doc
    ON card_doc_annotations (workspace_id, card, key);
  CREATE TABLE IF NOT EXISTS artifact_reviews (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    artifact     TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('approved','needs_work')),
    note         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, artifact)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS feedback_votes (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('reply','revision')),
    ref          TEXT NOT NULL,
    vote         INTEGER NOT NULL CHECK (vote IN (-1, 1)),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, kind, ref)
  ) STRICT;
  """,
    # Step 51 (131): goals and the org chart. The workspace goal (title, why, success
    # measure) and its sub-goals (owner, status, parent) are AGOS's plan: Hermes's
    # projects (hermes_cli/projects_db.py) are per-profile folders with no status,
    # owner, parent or measure, and its goals (hermes_cli/goals.py) are one session's
    # Ralph loop. A card's link to a sub-goal is its Hermes body ("## Goal" line),
    # never a row. A proposal may now be a goal change (kanban_asks kind 'goal',
    # rebuilt the way 127 did). AGOS's own Inbox notes (a lead removed, its reports
    # moved to the Co-Founder) are one row each. Replayable: the rebuild starts from
    # a fresh kanban_asks_new, the rest is IF NOT EXISTS.
    """
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
                 CHECK (kind IN ('ask','hire','instructions','plan','question','goal')),
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
  CREATE TABLE IF NOT EXISTS goals (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_id    INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    measure      TEXT NOT NULL DEFAULT '',
    owner        TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','dropped')),
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS goals_one_workspace_goal ON goals (workspace_id)
    WHERE parent_id IS NULL;
  CREATE INDEX IF NOT EXISTS goals_by_workspace ON goals (workspace_id, parent_id);
  CREATE TABLE IF NOT EXISTS inbox_notes (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
  ) STRICT;
  """,
    # Step 53 (133; step 52's review flow takes 132): the Vision page. The goals table
    # becomes the workspace's plan in three levels: the Vision (the row with no
    # parent: the owner's sentence, its why and a strategy), its goals (owner, due
    # date) and each goal's projects (dated start / end, or recurring with a rhythm).
    # A goal's key results are numbers (start, current, target, unit, due date): a
    # row each in key_results, so a proposed update names one. Hermes has none of
    # it (its projects are per-profile folders, its cards have no target).
    # Existing rows: the workspace goal becomes the Vision (its why stays), its
    # sub-goals become goals and theirs projects (a deeper one hangs under its goal);
    # a non-empty success measure becomes the one key result (words only, no target
    # yet) of a new goal "Success measure", since a Vision has no measure. Replayable:
    # ensure-column, IF NOT EXISTS, and every UPDATE / INSERT only touches rows not
    # mapped yet (level NULL, a measure not moved yet).
    """
  -- agos: ensure-column goals.level TEXT
  -- agos: ensure-column goals.strategy TEXT
  -- agos: ensure-column goals.due_on TEXT
  -- agos: ensure-column goals.project_kind TEXT
  -- agos: ensure-column goals.starts_on TEXT
  -- agos: ensure-column goals.ends_on TEXT
  -- agos: ensure-column goals.rhythm TEXT
  CREATE TABLE IF NOT EXISTS key_results (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    goal_id      INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    start_value  REAL NOT NULL DEFAULT 0,
    current      REAL NOT NULL DEFAULT 0,
    target       REAL,
    unit         TEXT NOT NULL DEFAULT '',
    due_on       TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS key_results_by_goal ON key_results (workspace_id, goal_id);
  UPDATE goals SET level = 'vision' WHERE level IS NULL AND parent_id IS NULL;
  UPDATE goals SET level = 'goal' WHERE level IS NULL
    AND parent_id IN (SELECT id FROM goals WHERE level = 'vision');
  UPDATE goals SET level = 'project' WHERE level IS NULL;
  WITH RECURSIVE up(id, anc) AS (
    SELECT id, parent_id FROM goals WHERE level = 'project'
    UNION
    SELECT up.id, g.parent_id FROM up JOIN goals g ON g.id = up.anc WHERE g.level = 'project'
  )
  UPDATE goals SET parent_id = (
      SELECT up.anc FROM up JOIN goals a ON a.id = up.anc
      WHERE up.id = goals.id AND a.level = 'goal' LIMIT 1)
    WHERE level = 'project' AND parent_id IN (SELECT id FROM goals WHERE level = 'project');
  INSERT INTO goals (workspace_id, parent_id, level, title, why, owner, status, position,
                     created_at, updated_at)
    SELECT v.workspace_id, v.id, 'goal', 'Success measure', '', '', 'active', -1,
           v.updated_at, v.updated_at
    FROM goals v WHERE v.level = 'vision' AND trim(v.measure) != '';
  INSERT INTO key_results (workspace_id, goal_id, title, created_at, updated_at)
    SELECT g.workspace_id, g.id, substr(trim(v.measure), 1, 300), v.updated_at, v.updated_at
    FROM goals g JOIN goals v ON v.id = g.parent_id
    WHERE v.level = 'vision' AND trim(v.measure) != '' AND g.level = 'goal'
      AND g.position = -1 AND g.title = 'Success measure'
      AND NOT EXISTS (SELECT 1 FROM key_results k WHERE k.goal_id = g.id);
  UPDATE goals SET measure = '' WHERE level = 'vision' AND measure != '';
  """,
    # Step 55 (134; step 56 takes 135): status cards. A status card's definition is
    # AGOS's (Hermes has no notion of a scoped summary): its title, its scope (the
    # workspace, a goal, a project, a member or a few words) and its update policy
    # (daily, weekly, on demand), and when the owner last asked for a refresh. Its
    # time is its Hermes cron job's schedule, its change detection Hermes's monitor
    # state, its summary and revisions files in the workspace folder (status/<id>/).
    """
  CREATE TABLE IF NOT EXISTS status_cards (
    id               INTEGER PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title            TEXT NOT NULL,
    scope            TEXT NOT NULL CHECK (scope IN ('workspace', 'goal', 'project', 'member', 'query')),
    scope_ref        TEXT NOT NULL DEFAULT '',
    policy           TEXT NOT NULL DEFAULT 'daily' CHECK (policy IN ('daily', 'weekly', 'manual')),
    refresh_asked_at TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS status_cards_by_workspace ON status_cards (workspace_id, id);
  """,
    # Step 56 (135; step 55 takes 134): templates. A team member's revisions (one
    # snapshot per change of its title, description, role text, the owner's notes,
    # model, skills, reads, lead, on/off, heartbeat; who made it and why; Restore is a
    # new revision): Hermes keeps no history of a SOUL.md or profile.yaml. And which
    # ready-made team (a catalog bundle) a workspace installed, with the bundle's
    # hash and what each of its items became, so the Team page can show what drifted
    # from it. Replayable: IF NOT EXISTS only.
    """
  CREATE TABLE IF NOT EXISTS agent_revisions (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    n             INTEGER NOT NULL,
    snapshot      TEXT NOT NULL,
    who           TEXT NOT NULL DEFAULT 'owner',
    why           TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    restored_from INTEGER,
    created_at    TEXT NOT NULL,
    UNIQUE (workspace_id, name, n)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS template_installs (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    slug          TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL,
    items         TEXT NOT NULL DEFAULT '{}',
    installed_at  TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS template_installs_by_workspace
    ON template_installs (workspace_id, slug);
  """,
    # Step 58 (136; step 59 takes 137): threads. A workspace's labels (a name, a
    # colour, the folder that groups them): Hermes's board has no labels. Which
    # cards carry a label is a block in each card's Hermes body (engine/threads.py),
    # never a row here. Replayable: IF NOT EXISTS only.
    """
  CREATE TABLE IF NOT EXISTS labels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    color         TEXT NOT NULL DEFAULT 'gray',
    folder        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    UNIQUE (workspace_id, name)
  ) STRICT;
  CREATE INDEX IF NOT EXISTS labels_by_workspace ON labels (workspace_id, folder, name);
  """,
    # Step 59 (137; step 58 takes 136): polish. Pipeline rules (when a card moves to a
    # status, a review stage approves or a plan is accepted, in a project or with a
    # #label: make a follow-up card, comment, assign, run an automation or tell the
    # owner) and the last move each rule kind acted on per card, so a Kanban hook Hermes
    # fires twice acts once; and the dev servers / previews a card's worker started
    # through Hermes's background processes (its port and pid: Hermes's processes.json
    # is rewritten by whichever process of the profile writes last, and has no port or
    # card). Replayable: IF NOT EXISTS only.
    """
  CREATE TABLE IF NOT EXISTS pipeline_rules (
    id             INTEGER PRIMARY KEY,
    workspace_id   TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name           TEXT NOT NULL DEFAULT '',
    trigger        TEXT NOT NULL CHECK (trigger IN ('status', 'review_approved', 'plan_accepted')),
    status         TEXT NOT NULL DEFAULT '',
    goal_id        INTEGER,
    label          TEXT NOT NULL DEFAULT '',
    action         TEXT NOT NULL
                   CHECK (action IN ('follow_up', 'comment', 'assign', 'run_automation', 'notify')),
    member         TEXT NOT NULL DEFAULT '',
    automation_id  INTEGER,
    text           TEXT NOT NULL DEFAULT '',
    enabled        INTEGER NOT NULL DEFAULT 1,
    last_fired_at  TEXT,
    last_outcome   TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS pipeline_rules_by_workspace ON pipeline_rules (workspace_id, id);
  CREATE TABLE IF NOT EXISTS pipeline_seen (
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    card          TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('status', 'review', 'plan')),
    mark          TEXT NOT NULL,
    seen_at       TEXT NOT NULL,
    PRIMARY KEY (workspace_id, card, kind)
  ) STRICT;
  CREATE TABLE IF NOT EXISTS card_services (
    id            INTEGER PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    card          TEXT NOT NULL,
    profile       TEXT NOT NULL,
    process_id    TEXT NOT NULL DEFAULT '',
    pid           INTEGER,
    pid_scope     TEXT NOT NULL DEFAULT 'host' CHECK (pid_scope IN ('host', 'sandbox')),
    started_mark  INTEGER,
    command       TEXT NOT NULL,
    port          INTEGER NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL,
    stopped_at    TEXT
  ) STRICT;
  CREATE INDEX IF NOT EXISTS card_services_by_card ON card_services (workspace_id, card, id);
  """,
    # Project pause (137): a goal or project may be "paused" (on hold, comes back;
    # "dropped" ends it). SQLite can't change a CHECK in place: the goals table is
    # rebuilt with every column, foreign keys off (key_results and the parent links
    # keep pointing at the same ids). Replayable: the rebuild starts from a fresh
    # goals_new and copies whatever the table holds.
    """
  -- agos: foreign-keys-off
  CREATE TABLE goals_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_id    INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    measure      TEXT NOT NULL DEFAULT '',
    owner        TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','paused','done','dropped')),
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    level        TEXT,
    strategy     TEXT,
    due_on       TEXT,
    project_kind TEXT,
    starts_on    TEXT,
    ends_on      TEXT,
    rhythm       TEXT
  ) STRICT;
  INSERT INTO goals_new (id, workspace_id, parent_id, title, why, measure, owner, status,
      position, created_at, updated_at, level, strategy, due_on, project_kind, starts_on,
      ends_on, rhythm)
    SELECT id, workspace_id, parent_id, title, why, measure, owner, status, position,
      created_at, updated_at, level, strategy, due_on, project_kind, starts_on, ends_on,
      rhythm FROM goals;
  DROP TABLE goals;
  ALTER TABLE goals_new RENAME TO goals;
  CREATE UNIQUE INDEX IF NOT EXISTS goals_one_workspace_goal ON goals (workspace_id)
    WHERE parent_id IS NULL;
  CREATE INDEX IF NOT EXISTS goals_by_workspace ON goals (workspace_id, parent_id);
  """,
    # Step 62 (138; step 63 takes 139): the hire kit's Readiness. The member's kit is
    # its Hermes profile's fact (profile.yaml ui_meta.agos.kit) and each item's state
    # is derived from real checks; AGOS keeps only the owner's own choices (Start
    # anyway, Not needed with his reason, Skip test) and each onboarding test's
    # grade (one row per test card). Replayable (IF NOT EXISTS).
    """
  CREATE TABLE IF NOT EXISTS member_readiness (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    member       TEXT NOT NULL,
    item         TEXT NOT NULL,
    choice       TEXT NOT NULL
                 CHECK (choice IN ('start_anyway','not_needed','skip_test','passed','failed')),
    reason       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, member, item)
  ) STRICT;
  """,
    # Step 63 (139; step 62 takes 138): skills that grow. An agent's request for a hub
    # skill it lacks (agos_skill_request: the source, why, its tests, what Hermes's scan
    # said, where it stands) and a skill's candidate version from the week's evidence
    # (its text under test until it passes the skill's Skill Studio tests and becomes a
    # version through Hermes's skill_manage, or is discarded). Hermes holds neither: its
    # skill_manage writes are live and its held writes have no test gate. A test run's
    # 0-1 score from the grader; a proposal may now be a skill (kanban_asks kind
    # 'skill', rebuilt the way 131 did). Replayable: the rebuild starts from a fresh
    # kanban_asks_new, the rest is IF NOT EXISTS / ensure-column.
    """
  -- agos: foreign-keys-off
  -- agos: ensure-column skill_test_runs.score REAL
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
                 CHECK (kind IN ('ask','hire','instructions','plan','question','goal','skill')),
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
  CREATE TABLE IF NOT EXISTS skill_requests (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    member       TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    tests        TEXT NOT NULL DEFAULT '[]',
    criteria     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'installing'
                 CHECK (status IN ('installing','testing','approval','landed','refused',
                                   'failed','rejected')),
    item_id      INTEGER REFERENCES library_items(id) ON DELETE SET NULL,
    verdict      TEXT NOT NULL DEFAULT '',
    scan         TEXT NOT NULL DEFAULT '',
    scripts      INTEGER NOT NULL DEFAULT 0,
    forced       INTEGER NOT NULL DEFAULT 0,
    runs         TEXT NOT NULL DEFAULT '[]',
    ask_id       INTEGER,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
  ) STRICT;
  CREATE INDEX IF NOT EXISTS skill_requests_by_ws ON skill_requests (workspace_id, created_at);
  CREATE TABLE IF NOT EXISTS skill_candidates (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES library_items(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    batch        TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    text         TEXT NOT NULL,
    why          TEXT NOT NULL DEFAULT '',
    evidence     TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'testing'
                 CHECK (status IN ('testing','promoted','discarded')),
    runs         TEXT NOT NULL DEFAULT '[]',
    score        REAL,
    base_score   REAL,
    version      INTEGER,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    decided_at   TEXT
  ) STRICT;
  CREATE INDEX IF NOT EXISTS skill_candidates_by_ws ON skill_candidates (workspace_id, status);
  """,
    # Card chats that kept a member's old profile name ('agos-<ws>--a-<name>') as
    # their member: the member's own name (actions/kanban_board.py _legacy_member).
    # Replayable: a fixed row no longer matches.
    """
  UPDATE chats SET agent = substr(agent, instr(agent, '--a-') + 4)
   WHERE agent LIKE '%--a-%';
  """,
    # Migration 141: AGOS is single-user with no login (db/logins_gone.py). The
    # owner's name is kept as the plain owner.name setting first; members' chats go
    # to the trash; the password, sessions, failed sign-ins and the human members
    # (and the workspaces they saw) go. `chats` is rebuilt without its two member
    # columns. Replayable: ensure-column brings the columns back for the rebuild.
    """
  -- agos: foreign-keys-off
  -- agos: logins-gone
  -- agos: ensure-column chats.member_id INTEGER
  -- agos: ensure-column chats.former_member TEXT
  UPDATE chats SET deleted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
   WHERE deleted_at IS NULL AND (member_id IS NOT NULL OR COALESCE(former_member, '') != '');
  DROP TABLE IF EXISTS sessions;
  DROP TABLE IF EXISTS login_failures;
  DROP TABLE IF EXISTS member_workspaces;
  DROP TABLE IF EXISTS members;
  DROP TABLE IF EXISTS owner;
  CREATE TABLE chats_new (
    id           INTEGER PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    channel      TEXT NOT NULL CHECK (channel IN ('web','telegram')),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    hermes_key   TEXT,
    deleted_at   TEXT,
    agent        TEXT,
    kind         TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat','dm','group')),
    members      TEXT NOT NULL DEFAULT '[]',
    kanban_card  TEXT
  ) STRICT;
  INSERT INTO chats_new (id, workspace_id, title, channel, created_at, updated_at,
      hermes_key, deleted_at, agent, kind, members, kanban_card)
    SELECT id, workspace_id, title, channel, created_at, updated_at,
      hermes_key, deleted_at, agent, kind, members, kanban_card FROM chats;
  DROP TABLE chats;
  ALTER TABLE chats_new RENAME TO chats;
  CREATE UNIQUE INDEX IF NOT EXISTS chats_by_hermes_key ON chats (hermes_key);
  CREATE UNIQUE INDEX IF NOT EXISTS chats_one_dm ON chats (workspace_id, COALESCE(agent, ''))
    WHERE kind = 'dm';
  CREATE UNIQUE INDEX IF NOT EXISTS chats_kanban_card
    ON chats (workspace_id, kanban_card, COALESCE(agent, ''))
    WHERE kanban_card IS NOT NULL AND deleted_at IS NULL;
  """,
    # Migration 142: catch-up of a run missed while the server was off
    # (actions/catch_up.py). The owner's choice per automation (NULL = run it once,
    # 'skip'), and what AGOS saw of each Hermes job: since when it is off / back on,
    # and the missed occurrence it already caught up or skipped (never twice).
    """
  -- agos: ensure-column automations.catch_up TEXT
  CREATE TABLE IF NOT EXISTS cron_catch_up (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    job_id       TEXT NOT NULL,
    off_since    TEXT,
    on_since     TEXT,
    missed_at    TEXT,
    asked_at     TEXT,
    state        TEXT CHECK (state IN ('waiting','asked','skipped')),
    PRIMARY KEY (workspace_id, job_id)
  ) STRICT;
  """,
    # Migration 143: folders, the owner's own grouping of a workspace's automations,
    # skills and projects (actions/folders.py). AGOS-only: nothing in Hermes moves.
    # One folder per item; an item deleted elsewhere leaves its folder by the cascade.
    """
  CREATE TABLE IF NOT EXISTS folders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('automation','skill','project')),
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL
  ) STRICT;
  CREATE UNIQUE INDEX IF NOT EXISTS folders_by_name
    ON folders (workspace_id, kind, name COLLATE NOCASE);
  CREATE TABLE IF NOT EXISTS folder_items (
    folder_id     INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    automation_id INTEGER UNIQUE REFERENCES automations(id) ON DELETE CASCADE,
    skill_id      INTEGER UNIQUE REFERENCES library_items(id) ON DELETE CASCADE,
    project_id    INTEGER UNIQUE REFERENCES goals(id) ON DELETE CASCADE,
    CHECK ((automation_id IS NOT NULL) + (skill_id IS NOT NULL) + (project_id IS NOT NULL) = 1)
  ) STRICT;
  CREATE INDEX IF NOT EXISTS folder_items_by_folder ON folder_items (folder_id);
  """,
    KANBAN_ASKS_KIT,  # 144: a kit for a member on the team (db/schema_kanban_kit.py)
    ERROR_ISSUES,  # 145: Settings → Errors (db/schema_errors.py)
    SERVICE_LAYER,  # 146: operation runs, sagas, outbox (db/schema_service_layer.py)
    RELIABILITY,  # 147: job queue, SLO samples (db/schema_reliability.py)
)
