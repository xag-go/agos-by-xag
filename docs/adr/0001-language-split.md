# ADR 0001 — TypeScript core, Python only as isolated services

- Status: superseded by ADR 0009 (Python core, owner's decision)
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3` (read only, no code copied)

## Context

Hermes is written almost entirely in Python: agent loop, tools, gateway,
messaging adapters, CLI and web UI backend. AGOS chose TypeScript and Next.js
because the team already works with them on the frontend. The question is
whether the backend should follow Hermes into Python.

## What problem does Python solve for Hermes?

1. **Libraries.** Many tools need libraries that are only good in Python:
   local speech-to-text (faster-whisper), document extraction (pdf, docx,
   xlsx, epub), data analysis, image/ML work, some messaging SDKs.
2. **One language for everything**, including research tooling
   (trajectories, batch runs, evals) aimed at model training.

## Do we have that problem?

- **Libraries: partly.** Documents, audio and data analysis matter for us
  (investor reports, store exports, voice notes on Telegram).
- **One language: yes, but we already have one** — TypeScript runs the UI,
  the server actions, and can run the gateway. Validation schemas (Zod) and
  types are shared between browser, server and gateway today.
- **Research tooling: no.** We are not training models.
- The things that make an agent system hard — the loop, the model APIs,
  MCP, containers, SQLite, Telegram — all have first-class TypeScript SDKs
  (official Anthropic and OpenAI SDKs, the Claude Agent SDK, the MCP SDK,
  `node:sqlite`, grammY/Telegram Bot API, Docker's HTTP API).

## Simpler version for us

Keep one core language and add Python **only at the edges**, as separate
services with a small HTTP contract (rules in ARCHITECTURE §13):

| Part                                                                    | Language                               | Why                                                          |
| ----------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------ |
| Web UI                                                                  | TypeScript / Next.js                   | Team knowledge                                               |
| Gateway: runner, scheduler, channels, tool broker                       | TypeScript                             | Shares types and validation with the UI; official SDKs exist |
| Tools that run in the workspace container (shell, files, patch, search) | TypeScript (small binary in the image) | Same code for cli and api modes                              |
| `services/documents` (pdf, docx, xlsx, pptx → text/tables)              | **Python**                             | Best libraries                                               |
| `services/speech` (local speech-to-text, text-to-speech)                | **Python**                             | faster-whisper, Piper                                        |
| `services/analysis` (pandas-style data work) when needed                | **Python**                             | Ecosystem                                                    |

The agent itself can still run Python _inside its workspace container_ for
the owner's tasks (e.g. a data script) — that is the task's code, not ours.

## Decision

**Update (step 3):** `services/documents` is built — the first Python service
(FastAPI, pypdf, python-docx, openpyxl, python-pptx), with a Zod-validated
client in the gateway and its ruff / mypy / pytest checks inside `pnpm check`.

TypeScript for the core. Python services are added when a feature needs
them, each one in its own container, never mixed into the core. Revisit if
more than half of new work ends up needing Python.

## What we deliberately keep simpler than Hermes

One language in the core instead of Python everywhere plus a TypeScript TUI,
Electron app and web UI talking to it over several protocols.
