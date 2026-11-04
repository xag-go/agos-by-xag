# ADR 0003 — Tools: small built-in set, executed only in the workspace container

- Status: superseded by [0010](0010-hermes-engine.md) — Hermes Agent provides this; kept for history
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3`, `tools/registry.py`, `model_tools.py`, `tools/approval*.py`, `tools/environments/`, `SECURITY.md` (read only)

## What problem does Hermes's design solve?

- **Breadth.** A registry of 100+ tools (web, shell, files, browser, vision,
  voice, home automation, kanban, messaging, memory providers…), each with
  a `check_fn` so it only appears when configured, plus a "tool search"
  bridge so rarely used tools don't cost tokens on every call.
- **Safety without a boundary by default.** Tools run on the host unless the
  user picks a sandbox backend (Docker, SSH, Modal…). So Hermes adds layers
  inside the process: dangerous-command patterns, a guard LLM for "smart"
  approvals, write guards for sensitive paths, SSRF blocks, injection
  scanning, secret redaction. Its own `SECURITY.md` says these are
  heuristics, not a boundary.
- **Many execution backends** for users on laptops, servers and clouds.

## Do we have that problem?

- **Breadth: yes, over time**, but we start with the tools a real employee
  needs for our workspaces.
- **Safety without a boundary: no.** Our boundary exists from the start: every
  tool executes inside the workspace's container, which only has that
  workspace's folders and no secrets (ARCHITECTURE §12). Heuristics are
  still useful, but as a second layer.
- **Many backends: no.** One backend: Docker on the owner's machine.

## Simpler version for us

- **One tool broker in the gateway.** Tools are declared once (name, schema,
  handler, `read` or `act`) and served to both engines: as MCP to the
  official CLIs, as tool definitions in api mode.
- **Execution always in the workspace container** through a small runner
  binary in the image. Paths go through `resolveSafePath` with the run's
  roots (`@agos/workspace`), on top of the mounts.
- **Starting set**: `read`, `write`, `patch` (with diff), `search_files`,
  `shell` (with timeout and background jobs), `web_search`, `web_fetch`,
  `ask_owner` (moves the task to Clarify), `update_plan`, `comment`,
  `suggest_task`, `create_subtask`. Browser, vision, speech and documents
  come as the matching services land.
- **Read vs act.** A tool is tagged `read` or `act`. A run that has read
  untrusted content (web, email, uploaded files) cannot call `act` tools
  that reach outside the workspace (send, publish, pay). Those happen in a
  separate "apply" run, and ask the owner according to the task's autonomy.
- **Approvals** are tied to the task's autonomy setting, not to a global
  switch. There is no "yolo".
- **Tool search** is added when MCP connectors make the tool list large.

## Deliberately simpler than Hermes

| Hermes                                                | Us                                    | Why                                          |
| ----------------------------------------------------- | ------------------------------------- | -------------------------------------------- |
| 100+ tools from day one, toolset presets per platform | ~12 tools, grown with services        | Easier to secure and test                    |
| Local host by default, 8 sandbox backends             | Docker only, always                   | The container is our security boundary       |
| Guard LLM decides if a command is dangerous           | Container + read/act split + autonomy | An LLM guard can itself be prompt-injected   |
| `/yolo` turns approvals off                           | Autonomy per task                     | Keeps the owner in control per piece of work |
| Plugins run in-process with full privileges           | Plugins run in their own container    | Same boundary for everything                 |
