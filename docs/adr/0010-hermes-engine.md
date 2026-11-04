# ADR 0010 — Hermes Agent is the engine; AGOS is the product on top

- Status: accepted (step 1 study; step 2 built — see below)
- Date: 2026-09-25
- Pinned for this study: Hermes Agent v0.21.4 (git `28aceb34`), Docker 29.8.0, macOS arm64
- Supersedes: the engine parts of ADRs 0002 (agent loop), 0003 (tools), 0004 (memory/skills),
  0005 (sessions), 0006 (scheduling), and the cli-runner design in ARCHITECTURE §12
  "Provider logins". The product parts of those ADRs (board rules, Start gate, autonomy,
  folders, vault, access) stay.

## Decision

**The owner sees only AGOS's web app, with its current design.** Every screen, the
Majorelle design, the board, departments and connectors stay as specified. Underneath,
AGOS stops building its own agent engine and drives **Hermes Agent** over its HTTP API.

- One AGOS workspace = one **Hermes profile** `agos-<workspace-id>` (own `config.yaml`,
  memory, sessions, skills, cron, `.env`).
- Every tool of that profile runs in a **Docker sandbox** that has only the workspace's
  folders mounted. The container is the boundary, not the prompt.
- AGOS (agos-core) owns the product state and is the **only writer** of each profile's
  config. The agent never edits it.

## Verified in step 1 (live spike, two throwaway profiles, real model runs)

| #   | Claim                                                              | How it was checked                                                                | Result                                                                                                                                                       |
| --- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Each profile's API is separate and keyed                           | Two profiles, own `API_SERVER_KEY`; no key → 401; A's key on B → 401              | ✅                                                                                                                                                           |
| 2   | The sandbox sees only its folders                                  | `docker inspect` of the containers Hermes created + `docker exec`                 | ✅ A: `/workspace` (ws-a) + `/shared/docs` (ro). B: `/workspace` (ws-b) only. No `/Users`, no other workspace, no host path                                  |
| 3   | Added folders are read-only when asked                             | `touch /shared/docs/x` inside A's sandbox                                         | ✅ `Read-only file system`                                                                                                                                   |
| 4   | No secret in the sandbox                                           | `env` inside both sandboxes                                                       | ✅ only `GPG_KEY` (the base image's public Python release-signing key — not a secret; we will build our own image anyway)                                    |
| 5   | A real run through the API uses the sandbox                        | `POST /v1/runs` on A: "list the project folder and /shared/docs"                  | ✅ answered from `/workspace/a.txt` and `/shared/docs/doc.txt`; `usage` (incl. cache read/write) and `runtime` (provider/model) returned                     |
| 6   | The owner's subscription works in every profile without copying it | New profiles have no `auth.json`; runs completed on `anthropic / claude-opus-5-5` | ✅ Hermes borrows the root grant and refreshes it in one place (it deliberately strips cloned single-use OAuth grants so two owners never revoke each other) |
| 7   | **Removing a folder takes effect immediately**                     | Removed `/shared/docs` from A's config, ran again                                 | ❌ **not by itself** — see below                                                                                                                             |

### Finding 7: folder removal needs AGOS to act

Hermes reads `terminal.docker_volumes` when it creates the sandbox and keeps it. After a
config change:

- the running sandbox kept the old mount;
- even after `docker rm` of the sandbox, the running gateway recreated it with the **old**
  mounts (config held in memory);
- only **stop run(s) → reload the profile's Hermes → remove the sandbox** produced a
  sandbox without the folder (verified: `/shared/docs: No such file or directory`).

So "removal is immediate" (brief §4) is implemented by **agos-core**, not assumed from
Hermes: on every folder change agos-core (1) asks running tasks to stop or finish (owner's
choice, as specified), (2) writes the new config, (3) reloads that workspace's Hermes,
(4) removes the sandbox, (5) verifies with `docker inspect` that the mount list equals the
granted list, and records it. Step 2 decides whether "reload" is a per-workspace process
restart or a narrower Hermes mechanism; a Hermes plugin or upstream fix is preferred if the
restart is too coarse.

## Ownership table

| AGOS concept                                                  | Owned by                                    | On Hermes                                                                                                                                       |
| ------------------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Workspace (id, name, description, departments, archive/trash) | agos-core                                   | one profile `agos-<id>`                                                                                                                         |
| Folders + grants (rw/ro), audit                               | agos-core                                   | `terminal.docker_volumes` written by agos-core; sandbox recreated on change                                                                     |
| Chat (General + one per department + extra)                   | Hermes                                      | session (`/api/sessions`, `/chat/stream`, fork, model lock); agos-core stores chat ↔ session id + department                                    |
| Board task / sub-task, Start gate, autonomy, evidence         | agos-core                                   | Start → `POST /v1/runs` (idempotency key = task step); events via SSE; stop/steer/approval endpoints                                            |
| Plan (#steps)                                                 | agos-core view                              | from the run's `todo` tool events                                                                                                               |
| Clarify                                                       | agos-core                                   | **gap** — no clarify event in the API; handled by an AGOS tool (plugin) that ends the run with a question → task moves to Clarify               |
| Automations                                                   | Hermes                                      | cron via `/api/jobs`; `.md` file mirrored in the workspace                                                                                      |
| Skills / agents / MCP / plugins                               | Global logic in AGOS; enabled per workspace | written into the profile (skills dir, `mcp_servers`, `plugins.enabled`) by agos-core only                                                       |
| Memory                                                        | Hermes                                      | profile `MEMORY.md` / `USER.md`, shown and edited in AGOS                                                                                       |
| Models, logins, effort                                        | Hermes                                      | root credentials shared by every profile; per-run model/effort via the API; `/api/model/options` for the live list                              |
| Channels (Telegram, Buzz, Slack…)                             | to decide in step 6                         | Hermes gateway (multiplex, per-profile credentials) **or** AGOS router → `/api/sessions/{id}/chat`. Both exist; decided when channels are built |
| Usage                                                         | Hermes                                      | per-run `usage` + `runtime`, per-session token counts; aggregated by agos-core                                                                  |
| Vault, access, backup                                         | agos-core                                   | backup also includes every `profiles/agos-*` home                                                                                               |

## Differences from the brief (owner approved the approach on 2026-09-25)

1. **No separate "brain" container per workspace.** Hermes runs as one host service
   (one process per workspace or one multiplexed process — decided in step 2 with
   resource numbers). The **hands** (sandbox) stay one container per workspace with only
   its folders and no secrets. Reason: Hermes already isolates profiles (config, keys,
   memory, sessions) and handles subscription refresh in one place; a brain container per
   workspace would re-create the refresh problem it solves.
2. **Subscriptions** are the owner's existing Hermes logins, not `claude setup-token`
   per container. Billing honesty stays: every run records provider + model + usage.
3. **No filtering Docker proxy in step 2.** Hermes creates the sandboxes itself (labels
   `hermes-agent=1`, `hermes-profile=<name>`); agos-core verifies every sandbox's mounts
   against the grants. A filtering proxy can be added later if Hermes moves into a
   container.

## Hardening applied per profile (step 2)

`terminal.backend: docker` always · `terminal.docker_mount_cwd_to_workspace: false` ·
explicit `docker_volumes` only · own image (no public image with extra env) ·
API server bound to 127.0.0.1 with a per-workspace key · Hermes dashboard/desktop not used
by AGOS · agent-created cron and self-enabled tools disabled · no public skill hub.

## Step 2 — built (2026-09-25)

`services/core/src/agos_core/engine/` + `actions/engine.py`. Enabled with
`AGOS_ENGINE=hermes`; without it the app runs on its own data as before.

- **Create workspace** → Hermes profile `agos-<id>` (`--no-skills`), its own API port and
  key on 127.0.0.1 (`.env`, 0600), and a locked-down terminal config (`rules.profile_config`):
  docker backend, no cwd auto-mount, no env forwarding, no credential files, explicit
  volumes only, toolsets that read host files or self-schedule disabled (browser, vision,
  video, computer_use, cronjob). A leftover profile with the same name is never reused.
- **Add / change / remove folder** → config rewritten, the profile's Hermes stopped if
  running, its sandboxes removed, Hermes started again, live sandboxes checked against the
  grants (`check_sandbox_mounts`). This is the answer to finding 7.
- **Fail closed** → if any of that fails (Docker down, Hermes error, mount mismatch), the
  workspace's Hermes is stopped and its sandboxes removed; the owner sees "the agent is
  stopped" and an activity entry. An old grant never outlives the owner's decision.
- **Refused before saving**: the disk root, the host home and anything containing a secret
  folder (`.ssh`, `.docker`, `.gnupg`, `.aws`, `.kube`, `.config/gh`, the Docker socket),
  Hermes's home, AGOS's data (incl. another workspace), symlinks resolving there, and paths
  with `:`/`,` (Docker volume syntax).
- **Archive / trash** → Hermes stopped, sandboxes removed. **Purge** → the profile is
  deleted (memory, sessions, keys). **Restore** → re-synced.
- Hermes keeps profiles under `<HOME>/.hermes/profiles` whatever `HERMES_HOME` says, so AGOS
  only configures the home it runs as (`AGOS_HERMES_USER_HOME`, default `$HOME`).

Tests: `test_engine_rules.py` (rules, 14 cases), `test_engine_sync.py` (actions with a fake
runner, incl. fail-closed, 6), and `test_engine_live.py` — real Hermes + Docker through
AGOS's own API (`AGOS_TEST_HERMES=1`): A can't see B's files (`find /` from A's sandbox),
added folder read-only by default (write → `Read-only file system`), removal effective on
the very next command, no socket / host home / `/Users` in the sandbox, no key or token in
its env, per-workspace API keys (wrong key → 401), private folders refused, nothing left
behind after the run. All passed on 2026-09-25.

## Open items (next steps)

- AGOS's own sandbox image (Node, Python/uv, git, gh, ffmpeg…), non-root; today the Hermes
  default image is used.
- One process per workspace (built) vs multiplexed gateway: measure RAM with 5 / 20
  workspaces; idle workspaces stopped automatically.
- Runs from the board (step 3): Start → `POST /v1/runs`, events, stop, approvals; Clarify
  tool (plugin) and plan mapping from `todo` events.
- Connectors / MCP enabled per workspace, written into the profile by agos-core only.

## Step 3: the board drives Hermes runs

- Only a card in **Start** becomes a run (`POST /v1/runs`, one Hermes session per
  task: `agos-task-<id>`). The card moves to Progress; To do never runs.
- The agent's `todo_list` is the card's **plan** (live); every `terminal` call is
  **evidence** (command, exit code, output). No evidence → the card is blocked,
  never sent to Review or Complete.
- The agent ends with an `agos-report` block. `clarify` → Clarify column + the
  question in the task chat; the answer is sent when the owner moves it to Start.
  `blocked` or a failed run → blocked in Progress, with the reason.
- Autonomy decides Review vs Complete (`engine/work.py: outcome`); a different
  model serving the run is always written on the card.
- **Stop** (new owner action on Progress) and **Cancel** stop the Hermes run;
  Request changes goes back through Start.
- Tested live: run → Review with evidence; Stop mid-run (file never written);
  Clarify → answer → Start → Review.

## Models and usage come from Hermes

- `GET /models/catalog` and `/models/providers` read Hermes's own inventory
  (`hermes_cli.inventory`, run with Hermes's interpreter) and `hermes auth list`
  (labels and kinds only, never secrets); cached 5 minutes. Only logged-in
  providers are offered in the pickers; a saved choice Hermes no longer lists is
  kept and marked "not listed now", never switched silently.
- If Hermes can't answer, pages still open: pickers keep saved choices and
  Settings → Models says Hermes isn't answering.
- Usage on the dashboard is summed from the runs Hermes reported (tokens, runs;
  subscriptions shown as "included", API cost left empty rather than guessed).
- Tested live: GPT-5.5 via the ChatGPT subscription → Review with evidence; an
  unknown model → Blocked with the provider's error; the core restarting
  mid-run → the run finishes and the card reaches Review.

## Chats are Hermes runs in the chat's own session

- Each workspace chat has its own Hermes session (`agos-chat-<id>`); every answer is a run on the workspace's API server, with the chat's model and effort (effort levels come from Hermes per model; `none` turns reasoning off).
- The core follows the run's events and keeps a live view (text, tools, thinking, approvals); the web long-polls `/chats/{id}/live`, so answers stream in and survive a page reload.
- Messages sent while the agent works go straight to Hermes (its busy_input_mode: steer; messages one after another are one turn by its text batching); AGOS keeps no queue (ADR 0020). Stop cancels the run; a failed or stopped answer can be retried.
- Approvals from Hermes surface in the chat with only "Allow once" or "Deny" — a chat can never widen what the agent may do.
- The agent may propose board tasks; they are added to To do only when the owner clicks, and never start by themselves.
- After a core restart, unfinished turns are resumed (a run still alive is followed again; otherwise the waiting messages are answered).

## Chat access, attachments and voice notes

- **Answers only.** The chat shows the owner's messages and the agent's replies. Tool
  calls and reasoning stay in Hermes; while the agent works the chat shows one status
  line ("Thinking…", "Working in the workspace…").
- **Access per chat, default per workspace.** "Ask me first" shows an Allow once / Deny
  card for every command Hermes flags. "Full access" makes AGOS answer `once` for the
  owner, never `always`, so nothing is stored as permanently allowed. Only the owner's
  click in the web app changes it. A chat message cannot, and the value is outside the
  agent's reach. Either way the command still runs only in the workspace sandbox, and
  Hermes's hardline blocks still apply.
- **`approvals.mode: manual`** is set on every workspace profile. Hermes's default
  `smart` mode lets an auxiliary model approve commands by itself; with host folders
  mounted, every flagged command must reach the owner (or the owner's standing
  Full access choice).
- **Attachments** (screenshots pasted or dropped, files, voice notes) are written under
  `/workspace/.agos/uploads/chat-<id>/` so the agent can open them. Images also go to
  the model as `input_image` parts. Voice notes are transcribed by Hermes's own
  `transcribe_audio` (the local provider by default) before the run. Limits: 8 files,
  20 MB each, 30 MB per message; types are checked and names cleaned. Deleting the chat
  removes its files.
- **Each chat has a random Hermes key.** SQLite reuses the id of a deleted chat, so the
  Hermes session and run idempotency keys come from `chats.hermes_key` and never from
  the id.

## Deleting a chat keeps what the project learned (owner decision)

The owner asked that deleting a chat never removes the project's knowledge. Deleting a
chat now only hides it (`chats.deleted_at`). Its messages, attachments in the workspace,
the Hermes session and the workspace's memory and SOUL all stay. Hidden chats are left
out of the list, search and attachment reads. New chats never reuse a hidden chat's id
or Hermes key.

## Automations run by the workspace's Hermes cron (step 5)

- Each automation is a job in its workspace's own Hermes cron store
  (`profiles/agos-<id>/cron/jobs.json`), named `agos-automation-<id>`. AGOS is its only
  writer. The agent's `cronjob` toolset stays disabled, so agent-made jobs can't exist.
- AGOS talks to cron through Hermes's own `cron.jobs` API, run in the Hermes venv with
  `HERMES_HOME=<profile home>`. That code takes the same cross-process lock as the
  scheduler. `/api/jobs` was not used because it can't pin a model or reasoning effort.
  Each job pins the automation's `model`, `provider` and `reasoning_effort`, and
  delivers `local`.
- Hermes does the scheduling: no double runs (execution ledger), catch-up after
  downtime, account-limit hold. Its scheduler ticks inside the profile's gateway, so AGOS
  keeps that gateway running while an automation is on.
- Results: every 20 s AGOS reads Hermes's finished executions and output files and records
  each run once (`automation_runs`): result, report, error, proposed To do cards
  (`agos-tasks` block). Failures go to the activity feed. Proposals become To do cards
  only on the owner's click. Automations never start or move tasks.
- A job that can't be written (engine not set up, Docker down) shows its reason on the
  automation ("Not scheduled: …"). Nothing fails silently. Archive/trash pauses the
  jobs; restore re-syncs them. Delete removes the job.

## Connectors: global library, per-workspace switches (step 5)

- The library (Settings → Skills / Agents / MCP / Tools / Plugins) holds definitions
  only. Each workspace turns items on in Workspace settings → Connectors (all off by
  default), with its own allowed tools, notes and credential. agos-core writes the
  result into that profile only:
  - skills → (now) one shared folder in `skills.external_dirs`, off = `skills.disabled` (ADR 0020 update);
  - MCP → `mcp_servers.<name>` with `tools.include` = allowed tools. The credential is
    encrypted in AGOS's DB and written only to that profile's `.env` as `AGOS_MCP_<NAME>`,
    referenced as `${AGOS_MCP_<NAME>}`. It is never sent back to the browser (••••last4);
  - plugins → `plugins.enabled`;
  - tools → removed from `agent.disabled_toolsets` only for the safe optional
    toolsets (code_execution, delegation, image_gen, tts). browser, vision, video,
    computer_use, cronjob, connections, homeassistant, spotify and kanban stay locked,
    with the reason shown;
  - agents → role text AGOS adds to a run (next step wires the task/chat picker).
- **Only remote (HTTP) MCP servers for now.** A stdio MCP server would run on the host,
  outside the sandbox, so it's refused until step 6b gives it a container. URLs to
  localhost, `.local`, private, link-local and CGNAT (100.64/10) ranges are refused;
  credentials in URLs are refused.
- "Test connection" connects with Hermes's MCP client from the Hermes venv (the
  workspace's credential goes in on stdin) and lists the tools, so the owner can pick
  allowed tools.

## Global library sources, agents in runs, limits (step 6a)

- **On this machine**: skills are read from `~/.hermes/skills` (definition folder copied
  into AGOS's library without anything that looks like a secret or a symlink). MCP comes
  from Hermes's approved catalog (`optional-mcps/*/manifest.yaml`): remote no-auth
  servers import in one click; OAuth servers are listed locked until AGOS has a
  per-workspace login flow. Plugins come from `hermes plugins list --json`.
- **From the web**: `hermes skills search --json` → `hermes skills inspect` (source,
  trust, SKILL.md preview) → the owner confirms → `hermes skills install --yes` into a
  **throwaway HERMES_HOME**. Hermes's security scan runs there and a blocked verdict
  stops it (AGOS never passes `--force`). The folder is then copied into AGOS's library.
  The owner's own Hermes is never changed.
- **Updates**: imported skills keep a content hash. "Update available" shows when the
  source changed; nothing changes until the owner clicks Update.
- **Agents**: created in Settings → Agents (role instructions, optional default model).
  A workspace turns them on in Connectors and can add its own instructions. A task
  (task modal) or a chat (header) can pick an agent that is on in its workspace. AGOS
  adds the role after its own run/chat instructions for that run only (cache-safe: the
  instructions are part of the run, not the profile). Picking an agent that isn't on is
  refused. Agents drafted from a chat as proposal cards are not built yet (see
  PROGRESS).
- **Account limits**: Hermes's `agent.account_usage.fetch_account_usage` gives real
  session and weekly use for Claude and OpenAI Codex subscriptions. Settings → Usage &
  limits shows them. The owner sets "warn at" and "pause at". While an account is at the
  pause level, everything new in every workspace waits — Hermes's own pause holds each
  root (ADR 0022), running work finishes. Warnings show on the
  Dashboard and Needs you.
- **Workspace limits enforced on runs**: monthly task-run limit (the card is Blocked
  with the reason), time limit per run, and the loop detector (the same tool call with
  the same result N times in a row). The run is stopped and the card is Blocked with the
  reason.
- **Notifications**: per event type instant / daily digest / silent, saved in AGOS
  (`app_settings`). Delivery to Telegram/Buzz comes with step 7.

## Sandbox network isolation (step 6b)

- Every workspace sandbox sits on its own **internal** Docker network
  (`agos-net-agos-<id>`, `docker network create --internal`). It has no route to the
  host, the LAN, Tailscale, cloud metadata or the internet.
- One shared **AGOS egress proxy** (`agos-egress`, stdlib Python, read-only rootfs, all
  capabilities dropped, no-new-privileges, 128 MB, no Docker socket) sits on the bridge
  and on every workspace network. It is the only way out: HTTP and HTTPS (CONNECT) to
  ports 80/443 only. Names that resolve to loopback, private, link-local, CGNAT
  (100.64/10 — Tailscale), multicast or reserved addresses, and Docker/host names
  (`host.docker.internal`, `*.local`, `*.internal`…), are refused with 403. The
  resolved public address is used for the connection, so DNS rebinding can't get
  through.
- AGOS writes `terminal.docker_extra_args = ["--network=agos-net-…"]` and proxy variables in
  `terminal.docker_env` for each profile (it is their only writer). Sync is fail-closed:
  if the network can't be created, the sandbox is removed and the agent stays stopped.
  At core startup every active workspace is re-synced, so older sandboxes move onto the
  isolated network. Purge removes the network.
- Verified live (`AGOS_LIVE_NETWORK=1 pytest tests/test_network_live.py`, the real
  sandbox created by Hermes's terminal tool): example.com 200; AGOS core and web through
  `host.docker.internal`, 172.17.0.1, 192.168.1.1, 100.100.100.100 and 169.254.169.254
  all 403; direct connection without the proxy: no DNS or route; raw TCP to the host:
  closed.

## Tools that stay locked (step 6b)

Superseded on 2026-10-02 by "Host tools moved into the workspace" below. Only
**cronjob** (and connections, homeassistant, spotify, kanban) stays locked.

- **cronjob** stays disabled. The agent can suggest an automation in words; the owner
  creates it (a structured "propose automation" card is listed in PROGRESS).
- Tool use is recorded per run and chat (task evidence, chat turn activity) and
  per-workspace changes go to the activity feed.

## Host tools moved into the workspace (2026-10-02)

Rule: a tool may act only inside its workspace's container, never on the machine.
Each one reuses what Hermes already has, instead of an AGOS copy.

- **vision / video**: optional (Capabilities → Tools). With the docker backend,
  Hermes's `tools/image_source.py` reads the file INSIDE the sandbox (host reads
  only for its own media caches; `.env`/`auth.json` refused). Live check: a
  `/workspace` picture is read in the container; a host `/tmp` file is not reachable.
- **browser / computer_use**: optional. Every workspace's sandbox runs
  `agos-sandbox:desktop` (`docker/sandbox/desktop.Dockerfile` = `agos-sandbox:1` +
  Hermes's Bot Desktop stack: Xvnc/Xfce, Playwright Chromium, agent-browser,
  cua-driver), like Hermes's own default sandbox image, with
  `bot_desktop.placement: terminal`, which REFUSES rather than fall back to the
  host. Turning either tool on is only Hermes's `agent.disabled_toolsets` (Step 14,
  ADR 0021: no image switch, no sandbox rebuild). Same agent user, mounts, internal network and egress
  proxy as the plain sandbox. The screen starts on first use and stops after 30
  idle minutes. Live check: the agent read a page; `172.17.0.1` was blocked;
  all Chromium processes were in the container cgroup, none on the host.
- **Screen tab** (`/w/<id>/screen`): the core grabs a JPEG of the workspace's X
  display inside its sandbox (`GET /workspaces/{id}/screen.jpg`); the web
  refreshes it ~1/s while visible. Watch only: no input path exists.
- **Local (command) MCP servers** (`engine/mcp_runner.py`): per workspace, a
  container `agos-mcp-<profile>-<name>` (sandbox image, internal network + proxy,
  only `/workspace` mounted, its key as an env var from a 0600 file) runs the
  command under `supergateway --stateful` (stdio → streamable HTTP); a relay
  publishes it on 127.0.0.1 only; the profile gets just that URL. The command is
  run once without input first so its packages download once. Off/park/purge
  remove the containers. Live check: the agent read `/workspace/zz-note.txt`
  through it; the server refused `/etc/hostname`; no host or direct internet.
- **Agents from chat**: the Co-Founder's `create_agent` / `update_agent` cards (with
  Undo, or Approve in "asks me first") already cover this (21 created, 44
  updated in real use), so no separate proposal card was built. Superseded
  (2026-11, hire kit required): a NEW agent is only ever a hire card in the
  owner's Inbox, in every autonomy mode, with its whole kit and model;
  `create_agent` makes none (it changes an existing agent, or becomes that same
  hire card), and `update_agent` never creates one.
- Linux note: the sandbox agent user takes the host user's uid/gid at build time
  (`scripts/build-sandbox.sh`); with a mismatch, bind mounts read as
  "Permission denied". Purge empties the profile's root-owned `sandboxes/`
  through a one-shot container (root, no network, only that folder mounted).
- New profiles get the workspace's model (`model.provider/default`); without it
  Hermes kept its template (OpenRouter) and a new workspace couldn't answer.

## Dashboard and Needs you (step 8)

- The Dashboard counters, activity, usage by provider and workspace share come from
  AGOS's own tables (runs and chat turns report Hermes's `usage`). Account-limit
  warnings are real (Hermes `fetch_account_usage`, owner's warn level). A channels
  summary shows lamps (connected / connecting / not connected).
- Needs you lists, across workspaces: Clarify questions, tasks waiting for approval,
  Blocked tasks (including limits), automation failures in the last 7 days, open
  proposals from automations and chats, and channel connections that are down. Each
  item links straight to the place to act (task, Runs dialog, chat, Settings →
  Channels).

## Hardening (step 10)

- **AGOS sandbox image** `agos-sandbox:1` (`docker/sandbox/Dockerfile`, `scripts/build-sandbox.sh`):
  Debian bookworm-slim, Node 22 (NodeSource, signed), Python 3.11 + pinned uv, git, gh
  (official signed repo), ffmpeg, ImageMagick, poppler, ripgrep, jq, sqlite, build tools.
  The default user is the unprivileged `agent` (uid 1000). Hermes still starts it with its
  hardened flags (caps dropped, no-new-privileges, pids limit) and the workspace's
  internal network. 1.71 GB, versus 2.2 GB for the old generic image. It is now the
  default (`AGOS_SANDBOX_IMAGE` overrides). Built and checked on arm64; amd64 through
  buildx (see PROGRESS).
- **Always on (2026-10-11, replaces the idle stop)**: each workspace's Co-Founder is its
  Hermes gateway and runs the way Hermes runs its own gateway service: always on, started
  again when it isn't running: Hermes's own service (`hermes -p <profile> gateway install`,
  systemd user unit with Restart=always, on at boot), started with `hermes gateway start`.
  AGOS only installs it once and hands over a gateway it had spawned. Its bot, scheduler,
  heartbeat and Kanban dispatcher live in it. (The old 20-minute idle stop fought the bot keeper and made Hermes send its
  "shutting down" notice every 20 minutes.) Team members still start when something is
  for them and stop once quiet.
- **RAM measured** (5 throwaway workspaces, this Mac): 5 gateways ≈ 306 MB total (41–110
  MB each), idle sandboxes ≈ 1 MB each, egress proxy 12 MB. Estimate for 20 active
  workspaces: ≈ 1.2 GB for gateways plus what the agents run. Idle workspaces cost
  nothing once stopped. A 16 GB server has ample room.
- **Hermes pinned**: tested version 0.21.4 (`HERMES_TESTED_VERSION`). Update procedure
  in `docs/HERMES-UPDATES.md` (backup → try a copy → AGOS unit + live tests → switch).
- **Bug found and fixed (live)**: stopping a workspace gateway could kill agos-core
  itself. Hermes's process registry had recorded the dev shell's background processes
  (agos-core among them) in the `agos-demo` profile's `processes.json`, and a gateway
  "recovered" and then terminated them when it stopped. Fixes: (1) every Hermes child
  runs in its own session with no `HERMES_*` markers from the parent environment; (2)
  before a gateway starts, AGOS removes records in the profile's `processes.json` that
  point at agos-core, its process group or its parents; (3) `scripts/dev-up.sh` runs the
  dev stack under launchd, outside any agent's process registry (the server install
  uses systemd services for the same reason). Verified: 3 archive/unarchive rounds with
  the gateway up; agos-core stayed up.
