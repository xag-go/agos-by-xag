# ADR 0009 — Python is the core; Next.js is only the interface

- Status: accepted and done (owner's decision, 2026-09-23)
- Supersedes: ADR 0001 (TypeScript core, Python at the edges)

> **Since then:** `apps/gateway` and `services/documents` are gone (Hermes Agent
> is the engine, ADR 0010). The core and the web run as systemd services on
> 127.0.0.1 (core :8766, web :3000), not in Docker; only the workspace sandboxes
> are containers. AGOS has no login. The current picture is
> [ARCHITECTURE.md §3](../../ARCHITECTURE.md#3-containers-c4-level-2).

## Context

ADR 0001 kept the backend in TypeScript and used Python only for isolated
services. The owner's direction is the opposite, and it is theirs to set:
**Python is the foundation of AGOS; Next.js was chosen only for the
interface.** Their existing systems (a home-made hub, content and investment
pipelines) are Python, and so is most of the agent ecosystem they want to
use (Claude Agent SDK, OpenAI SDK, MCP SDK, Telegram, data and document
libraries).

Nothing in the design depends on TypeScript on the server: the security
model (containers, brain/hands, read vs act, vault), the board, the storage
and the channels are all language-neutral.

## Decision

```
Browser ──► web (Next.js)  ──HTTP, internal network──►  core (Python)
            screens only                                 everything else
            + access check                               ├─ API (FastAPI)
                                                         ├─ data (SQLite) + files
                                                         ├─ security (vault, sessions)
                                                         ├─ runner (agents), broker (tools)
                                                         ├─ scheduler, services
                                                         └─ channels (Telegram…)
                                  core ──► documents (Python, no internet)
                                  core ──► cli-runner / workspace containers
```

- **`services/core` (Python 3.12, FastAPI, Pydantic)** owns all data, rules
  and background work. It is the only process that opens the database and
  the workspace folders. It replaces `apps/gateway` and the TypeScript
  packages `db`, `workspace` and `security`.
- **`apps/web` (Next.js)** renders screens and calls the core API from the
  server side (server components and server actions). It keeps no data and no
  business rules. It still checks _who_ is asking (this machine, SSH tunnel,
  Tailscale) because it is the edge that sees the request,
  and forwards the verified request to the core with an internal token.
- **The contract is typed on both sides**: the core publishes its OpenAPI
  schema; TypeScript types for the web are generated from it (no hand-written
  duplicates). A contract test fails the build when they drift.
- **The core is never published**: it listens only on the internal Docker
  network. Only `web` has a port (127.0.0.1).
- **`services/documents`** stays a separate, internet-less container: it
  parses untrusted files, so it keeps its own boundary.
- **Same quality bar**: ruff, mypy `--strict`, pytest (including every
  security test that exists today, ported first), uv lockfile with
  `exclude-newer`, non-root read-only containers.

## Migration (keeps the app working at every step)

1. **Core skeleton** with the ported foundations and their tests: data
   layout and path safety, database schema + migrations + repositories
   (every function scoped by workspace id), secret
   helpers, access decision, cron validation, board rules.
2. **API** for everything the web does today; web switches from direct
   database calls to the API, screen by screen, with generated types.
3. **Background work** (trash purge, documents check) moves from
   `apps/gateway` to the core; `apps/gateway` and the TypeScript backend
   packages are deleted.
4. Docker: `web` + `core` + `documents`; same volume, same hardening.

The existing data folder and database file stay compatible: the core uses
the same schema and migrations, so nothing is lost.

**Done (2026-09-23):** steps 1–4 completed. `services/core` owns data and
rules (86 tests, mypy strict), the web calls it with generated types,
`apps/gateway` and the TypeScript packages `db`, `workspace`, `security` are
deleted, and Docker runs `web` + `core` + `documents`. Existing databases and
data volumes opened unchanged.

## Consequences

- One language for all logic, the one the owner knows and already uses.
- The web becomes thinner and easier to replace (desktop app, mobile).
- Cost: the TypeScript backend written in steps 2–4 is ported; its tests are
  ported with it, so behaviour is preserved and checked.
