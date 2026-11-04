# ADR 0005 — Storage: one SQLite database, tasks and chats as the history

- Status: accepted (built in roadmap step 2)
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3`, `hermes_state*.py` (21 files), `tools/session_search_tool.py`, `agent/context_compressor.py`; Hermes Web UI `api/models.py`, `api/session_recovery.py` (read only)

## What problem does Hermes's design solve?

- **Many sessions from many surfaces** (CLI, TUI, desktop, web, a dozen chat
  apps, cron, subagents) written by several processes at once. Hence SQLite
  in WAL mode with turn leases, lock guards, read pools, repair and
  recovery tools, and a routing index for chat platforms.
- **Finding old context**: full-text search (FTS5, with CJK tokenizers) over
  all messages, exposed as a tool.
- **Long sessions** that overflow the context window: compression (prune old
  tool output, then a structured summary), plus undo/retry/branch.
- The Web UI keeps its **own** JSON session files and reconciles them with
  the agent's database — a source of many bugs in its changelog.

## Do we have that problem?

- **Many writers: no.** One gateway process runs agents; the web app writes
  owner actions. SQLite with WAL and a busy timeout covers this.
- **Search: yes**, later (step 8), per workspace.
- **Long context: yes** for chats; tasks are shorter because each step has
  its own plan.
- **Two sources of truth: no**, and we keep it that way.

## Simpler version for us (what step 2 builds)

- One file `system/agos.db`, opened with `node:sqlite` (built into Node, no
  native dependency), WAL, foreign keys on, `STRICT` tables, created `0600`.
- Migrations as ordered SQL strings; `PRAGMA user_version` tracks them; a
  database newer than the app refuses to open.
- Tables: `workspaces`, `workspace_folders`, `tasks` (sub-tasks one level
  deep, enforced by a trigger), `plan_steps`, `comments`, `suggestions`,
  `chats`, `messages` (a chat's or a task's, never both — a CHECK
  constraint), `automations`, `activity` (dashboard + audit trail).
- Every repository function takes the `workspaceId`, so a row can't be read
  or changed through another workspace by guessing an id.
- Files stay files: workspace folders, memory and skills are on disk;
  the database indexes and records.
- Deleting a workspace moves its folder to `.trash/` and marks its rows;
  both are purged together after 30 days.
- Step 7 adds `runs` and `run_events` (ADR 0002); step 8 adds FTS5 search
  and compression.

## Deliberately simpler than Hermes

| Hermes                                                                 | Us                                         | Why                             |
| ---------------------------------------------------------------------- | ------------------------------------------ | ------------------------------- |
| 21 state modules: leases, lock guards, read pools, repair, portability | One `@agos/db` package, plain repositories | One writer process, one machine |
| Web UI JSON sidecars reconciled with the agent DB                      | One database for UI and gateway            | Avoids their largest bug class  |
| Session ids routed per platform/chat/thread/user                       | Workspace → chat or task                   | Our structure is explicit       |
| CJK tokenizer built in C                                               | Default FTS5 tokenizer first               | Not needed yet                  |
