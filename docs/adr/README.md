# Architecture decision records

Short records of design decisions: the problem, what was decided, and why. The
main reference stays [ARCHITECTURE.md](../../ARCHITECTURE.md). An ADR explains
_why_ a part of it looks the way it does.

Hermes Agent (Nous Research, MIT) was first studied as a reference only. Since
[ADR 0010](0010-hermes-engine.md) it is the engine of everything: one Hermes
root and one Docker sandbox per workspace. ADRs 0002–0004 and 0006 describe the
engine AGOS would have built itself; they are kept for history. Older ADRs may
name files that no longer exist: each one says at the top what changed since.

## Index

| ADR                                                | Decision                                                                                                                                                                                                                                                                  | Status                                       |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| [0001](0001-language-split.md)                     | TypeScript core; Python only as isolated services                                                                                                                                                                                                                         | superseded by 0009                           |
| [0002](0002-agent-loop.md)                         | Agent loop: one run state machine, stable prompt, event log first                                                                                                                                                                                                         | superseded by 0010                           |
| [0003](0003-tools-and-isolation.md)                | Small tool set, run only in the workspace container; read vs act                                                                                                                                                                                                          | superseded by 0010                           |
| [0004](0004-memory-and-skills.md)                  | Memory as files per workspace; shared skills hold method, data stays local                                                                                                                                                                                                | superseded by 0010                           |
| [0005](0005-sessions-and-storage.md)               | One SQLite database for AGOS's own data                                                                                                                                                                                                                                   | accepted                                     |
| [0006](0006-gateway-channels-scheduling.md)        | One gateway process, Telegram first, owner-only, durable delivery                                                                                                                                                                                                         | superseded by 0010                           |
| [0007](0007-messaging-channels.md)                 | Messaging: conversations bound to one workspace, replies routed to tasks                                                                                                                                                                                                  | accepted, partly superseded by 0010 and 0020 |
| [0008](0008-single-environment.md)                 | AGOS as the single environment: import projects in place, coding roles, review surface, supervised services                                                                                                                                                               | proposed                                     |
| [0009](0009-python-core.md)                        | **Python is the core** (FastAPI: data, rules, control); Next.js is only the interface                                                                                                                                                                                     | accepted                                     |
| [0010](0010-hermes-engine.md)                      | **Hermes Agent is the engine**: AGOS drives it and keeps only the product and design                                                                                                                                                                                      | accepted                                     |
| [0011](0011-workspace-identity.md)                 | **Workspace identity**: SOUL.md written only by AGOS; memory stays Hermes's own; deleting a chat keeps knowledge                                                                                                                                                          | accepted                                     |
| [0012](0012-backup-and-server.md)                  | **Backup and restore**: one encrypted file, restore only into an empty folder, a restore test                                                                                                                                                                             | accepted                                     |
| [0013](0013-workers.md)                            | **Workers**: a team per workspace (Co-Founder and members), groups and DMs, @mention or Co-Founder handoff                                                                                                                                                                | accepted                                     |
| [0014](0014-team-plans.md)                         | **Team plans**: the Co-Founder proposes a chain of board steps, the owner approves once, the code runs it                                                                                                                                                                 | accepted                                     |
| [0015](0015-capabilities-and-connectors.md)        | **Capabilities and connectors**: skills, agents, MCP and tools in one place; apps connect once and turn on per workspace                                                                                                                                                  | accepted                                     |
| [0016](0016-self-improvement-and-looking-ahead.md) | **Self-improvement and Autonomy rules**: agents learn from feedback through Hermes; act / ask / never rules per agent                                                                                                                                                     | accepted (Looking ahead removed by 0019)     |
| [0017](0017-one-copy-of-the-team-texts.md)         | **One copy of the team's texts**: playbooks show what the team really uses; no second editable copy                                                                                                                                                                       | accepted, partly superseded by 0020          |
| [0018](0018-follow-ups-and-watches.md)             | **Follow-ups and watches**: agents come back by themselves and keep an eye on work until it is done                                                                                                                                                                       | accepted                                     |
| [0019](0019-goal-mode-in-chats.md)                 | **Goal mode in chats**: Hermes's goal judge checks real work in chats; Looking ahead removed                                                                                                                                                                              | accepted                                     |
| [0020](0020-one-hermes-root-per-workspace.md)      | **One Hermes root per workspace**: the Co-Founder is the root's default profile, members are profiles under it; groups are Hermes rooms                                                                                                                                   | accepted                                     |
| [0021](0021-screen-and-what-stays.md)              | **The screen is Hermes's; what stays AGOS's**: each piece AGOS keeps, with the Hermes evidence                                                                                                                                                                            | accepted                                     |
| [0022](0022-usage-pause-is-hermes-pause.md)        | **The usage pause is Hermes's own pause** (`hermes pause` / `resume` per root)                                                                                                                                                                                            | accepted                                     |
| [0023](0023-no-keys-outside-settings.md)           | **No keys outside Settings → Keys**: the owner's messages masked with Hermes's redactor, a manual Secrets check, backups with no keys                                                                                                                                     | accepted                                     |
| [0024](0024-hermes-gateway.md)                     | **The Hermes Gateway**: one boundary for every Hermes call (CLI, runtime runs, its DBs): typed errors, a per-root circuit breaker, retry for idempotent reads only; a ratchet keeps calls outside it shrinking                                                            | proposed                                     |
| [0025](0025-workspace-isolation.md)                | **Workspace isolation**: the wall's limits (/proc read-only, abstract sockets scoped; the Docker socket and `systemd-run --user` stay open until the broker), resource limits on every service and gateway, journal cap; step 4: one uid per workspace + a sandbox broker | accepted                                     |
| [0026](0026-job-queue-and-retention.md)            | **Job queue and retention**: AGOS's own background work as durable jobs (lease, backoff, dead letters in Settings → Errors), every send through the outbox, daily retention of machine records only, measured SLIs, expand/contract migrations                            | accepted                                     |
| [0028](0028-release-channels.md)                   | **Release channels**: SemVer tags from 0.x, stable / beta / main channels for the installer and `agos update` (forward only), releases signed keyless with Sigstore and checked before any of their code runs, SBOM + SLSA provenance                                     | accepted                                     |

## Writing a new ADR

1. Copy the shape of a recent one: title, `Date · Status`, Problem (or
   Context), Decision, Consequences.
2. Number it after the last one. Never renumber or delete an ADR.
3. When a decision is replaced, keep the old ADR and change its status to
   "superseded by NNNN", with a short note at the top.
4. Add it to the index above in the same change.

## Our design in one picture

```
Browser / phone ──► web (Next.js) ──► core (Python: data, rules, control; agos.db)
Telegram ─────────────┐                   │  hermes CLI · API · files (127.0.0.1)
                      ▼                   ▼
        Hermes root per workspace (ADR 0020): one gateway; its default
        profile = the Co-Founder, members = profiles under it, groups =
        Hermes rooms (memory, sessions, skills, cron, Kanban, Telegram)
                      │
                      ▼
        Docker sandbox per workspace: tools, only its folders,
        no secrets, public internet only via AGOS's egress proxy
```

The full picture, with C4 diagrams, is in
[ARCHITECTURE.md](../../ARCHITECTURE.md#2-system-context-c4-level-1).
