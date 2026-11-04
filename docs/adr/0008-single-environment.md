# ADR 0008 — AGOS as the owner's single environment for building many projects

- Status: proposed
- Date: 2026-09-23
- Inputs: a read-only survey of one real owner's projects (no secrets opened);
  OpenClaw docs and incident reports; Hermes inventories (Appendix A).

## Context

The owner this was designed with doesn't write code: they describe the logic
and expect AI to build everything, edge cases included. Today that takes
several tools glued together (a typical setup, taken from the survey):

- **Claude Code in VS Code/terminal** with global settings (Opus, effort
  xhigh), plugins (Codex bridge with a "review gate", Gemini bridge,
  Playwright, Vercel, PR review) and global skills.
- **A home-made hub** (Python): discovers projects, one Telegram
  daemon for all of them with forum topics, role routing (Claude plans and
  reviews, Codex writes), reports, director notes, a doctor, Google
  Drive/Sheets access, macOS GUI control.
- **launchd** keeps services alive: the Telegram daemon, a pipeline every few
  minutes, a scheduler every hour, a small dashboard and a downloader on local
  ports; the Mac is woken on a schedule with `pmset`.
- **Projects** of two kinds:
  - _automation projects_ — Python pipelines with data in files, schedules,
    Telegram topics, external APIs, secrets in `.env` files; not always in git;
  - _code projects_ — Next.js apps with Postgres, Vercel deploys, an MCP
    endpoint, a strict PR flow and a `pnpm check` gate.
- **House rules** every project repeats, for example: replies in the owner's
  chat language (e.g. Darija in Latin letters), files in English, one script
  forbidden in replies; short command words for "do it" and "ask first";
  never claim a check that wasn't run; `AGENTS.md` is the single instruction
  file (`CLAUDE.md` just points to it).

**Goal.** An owner should be able to **build many new projects** from AGOS — apps,
automations, bots, pipelines — without wiring subscriptions into editors,
scripts and launchd each time. The survey of existing projects is **evidence
of how an owner works and what projects need**, not a migration plan:
the same needs (toolchains, schedules, services, Telegram topics, secrets,
Claude + Codex roles, strict checks, git/PR/deploy) must be available to every
new project from day one.

## What Hermes and OpenClaw do, and what they miss

| Need                           | Hermes                                     | OpenClaw                                                                                                                                      | Gap we close                                                                      |
| ------------------------------ | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Coding via Claude Code / Codex | drives Codex app-server; own coding tools  | `coding-agent` skill + ACP: Claude Code, Codex… in git worktrees, reports back to chat                                                        | Neither has a **code review surface** (diffs, previews, CI) — chat only           |
| Isolation                      | host by default, optional sandbox backends | Docker sandbox optional; `tools.elevated` escape hatch; one trust boundary per gateway                                                        | Containers always; per-workspace boundary; no escape hatch                        |
| Secrets                        | plain `.env`                               | `~/.openclaw` files; may leak into transcripts                                                                                                | Encrypted vault; never in the agent's container; exact-value redaction            |
| Long-running project services  | no                                         | no                                                                                                                                            | **Services**: the project's own daemons and jobs, supervised                      |
| Existing projects              | profiles                                   | agent workspaces                                                                                                                              | **Import in place**, keep the folder, add git                                     |
| Subscriptions                  | OAuth pools                                | OAuth + `claude -p`; hit by Anthropic's April 2026 change                                                                                     | Owner sees exactly how each provider bills third-party use                        |
| Security record                | heuristic guards                           | CVE-2026-25253 (gateway token leak → RCE), CVE-2026-32922 (device → admin), ~800 malicious hub skills, tens of thousands of exposed instances | Loopback + host check + owner auth, no public skill hub by default, audit command |

## Decision

### 1. Every project is a workspace — new, or an existing folder

- **New project** (the main path): created by AGOS with its folder, git,
  `AGENTS.md`, and a starter from a template the owner picks (Next.js app,
  Python automation, Telegram bot, data pipeline…), ready to run and check.
- **Existing folder** (optional): the workspace's own folder can also be a
  folder that already exists, used where it is, mounted at `/workspace`.
- On import AGOS detects: `AGENTS.md` (+ nested ones), skills folders
  (`plugins/Skills`, `.claude/skills`), agents (`plugins/agents`), stack
  (package.json / pyproject / requirements), dev and test commands, `.env`
  files, launchd jobs pointing at the folder, Telegram settings. It shows a
  plan; nothing is changed until the owner confirms.
- **Git always.** A project without git gets a local repository at import
  (with a sane `.gitignore` for secrets and logs). Every agent change becomes
  a commit on a task branch — so everything is reviewable and reversible.

### 2. Agents code through the official CLIs, as roles

- Per workspace, roles with a model each (defaults from the owner's current
  setup): **Planner/Reviewer** = Claude (Opus, effort xhigh),
  **Builder** = Codex, **Checker** (fact-check) = any model via OpenRouter.
  A task or sub-task can override any role (ADR 0002 board + §8 models).
- Coding runs use the official **Claude Code** and **Codex** CLIs from the
  `cli-runner` (the brain), with tools executed in the workspace container
  (the hands) — ADR 0003. Each task works in its own **git worktree and
  branch**; the base commit is recorded.
- **Plan → build → review loop** is built in: the planner writes the Plan,
  builder sub-tasks do the work, the reviewer checks against success criteria
  and the project's own gate (its `check` / self-test / doctor command).
  "Done" requires **evidence**: the command, its exit code and output are
  attached to the task. No evidence, no Review.

### 3. A code surface, so the owner reviews results, not code

In each workspace, a **Code** area (only when the folder is a repo):

- **Changes**: per task, the diff in plain language first ("what changed and
  why"), the full diff one click away; approve → merge, or request changes.
- **Preview**: the project's dev server started in the workspace container on
  an allocated port, opened through AGOS's authenticated proxy (no port
  collisions: both web apps want 3000 today).
- **Checks**: the project gate and CI status (GitHub via `gh`, token held by
  the gateway); **never push to `main`** — branch → PR → green CI → merge,
  exactly the flow the projects already enforce.
- **Files** (tree + editor, self-hosted CodeMirror), **Terminal** (owner only,
  inside the workspace container), **Deploy** (Vercel CLI with the gateway's
  token; production only after approval; preview deploys only where the
  project allows them).

### 4. Services: the project's own daemons and jobs

The owner's projects are not only code: they _run_ (pipelines, schedulers,
dashboards, bots). A workspace can declare **services**:

- _long-running_ (a dashboard, a daemon) — restarted on failure, health
  checked, port exposed only through the proxy;
- _scheduled_ (every 5 min, hourly, Monday 09:00) — no double runs, lock,
  catch-up after sleep, log rotation, heartbeat, alert on failure.

Services run in a **service container** separate from the agent's container,
from the **approved** commit (never from the agent's working branch).
They receive the workspace's **project secrets** (vault, encrypted); the
agent's container never does. The agent can start/stop/restart services and
read their logs and heartbeats; logs pass through exact-value secret
redaction. Changing a service's code goes through the task → review → merge
path. This replaces launchd-style supervision for the owner's projects.

### 5. Secrets: a vault per workspace

- Owner-imported from the project's `.env` at import (then the owner can
  delete the file), edited in Workspace settings → Secrets; values never shown
  again, never sent to the browser or to a model.
- Injected only into services and into the gateway's own credentialed calls
  (Telegram, Google, Vercel, GitHub, MCP). Test-only values can be marked
  "available to agent checks" explicitly, one by one.

### 6. House rules as settings, not prompts only

Per installation (overridable per workspace): chat language (e.g. Darija in
Latin letters), file language (e.g. English), **forbidden scripts** (e.g. a
script the owner doesn't want in replies) — enforced by an output check that
retries, like the filter in the surveyed setup; command words (e.g. one word for "do it",
another for "ask first") mapped to task autonomy.

### 7. The Mac itself: a small host helper, later

Some actions can't run in Docker on a Mac: waking the machine (`pmset`),
macOS GUI control, launchd migration. A tiny **host helper** (owner-installed,
allowlisted actions only, talks to the gateway over a local socket) covers
them. Until it exists, those stay manual.

### 8. Existing tools (optional)

Not a goal of the roadmap. If the owner ever wants to move an existing
project in, the same pieces apply: Telegram bots and topics →
connections and bindings (ADR 0007); launchd jobs → services; `config/.env` →
vault; `AGENTS.md`/skills/agents → workspace instructions and connectors;
director notes → memory; reports → automations. The old service is stopped
only after the new one has run successfully, with a rollback.

### 9. Subscriptions: use Claude Code the way owners already do

Official Anthropic docs (code.claude.com: authentication, headless, Agent SDK
quickstart), checked 2026-09-23:

- A third-party app must **not offer claude.ai login itself** (unless
  approved). The sanctioned ways are: the owner's own official login, a
  token the owner creates with **`claude setup-token`** (documented for
  scripts and automation, set as `CLAUDE_CODE_OAUTH_TOKEN`), or an API key.
- The owner typing `claude` in a terminal is normal Claude Code use, wherever
  that terminal is.
- Billing: reports disagree about whether subscription use through headless
  mode / the Agent SDK is metered separately (an April 2026 change, a May
  partial reversal, a June split reported as paused). **AGOS must not depend
  on one answer**: it records usage per provider and mode, shows how each is
  billed, and lets the owner switch a role to an API key at any time.

So AGOS offers three ways, all sanctioned:

1. **Owner terminal** (Code surface): a terminal where the owner runs
   `claude` or `codex` interactively in the project — exactly like VS Code's
   integrated terminal. Runs in a per-workspace session container that holds
   the owner's CLI login and only that workspace's folder.
2. **Owner's token for agents**: the owner runs `claude setup-token` (and the
   Codex equivalent) once, pastes the token into Settings → Models; it is
   encrypted, and only the `cli-runner` receives it (ADR 0003 brain/hands).
3. **API key**, per provider, as a fallback or for heavy automation.

## Consequences

- New roadmap steps: **New project + templates / existing folder** (16),
  **Code surface** (17), **Services** (18), **Host helper** (19, later, to be
  discussed). Build order changes so
  an owner can move off editor-plus-launchd setups as early as possible:
  3 → 4 → 6 → 7 → 16 → 18 → 9 → 17 → 8 → 10 → 11 → 12 → 13 → 14 → 19 → 15.
- Workspace containers need the projects' toolchains: Node 20–26 + pnpm,
  Python 3.11+ with uv, git, gh, ffmpeg, yt-dlp, Postgres client; a project
  can add its own (devcontainer.json is honoured when present).
- Hard-coded host paths in existing scripts must be made portable when a
  project is moved in; the import lists them.
