# ADR 0004 — Memory and skills: plain files per workspace, method shared, data local

- Status: superseded by [0010](0010-hermes-engine.md) — Hermes Agent provides this; kept for history
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3`, `tools/memory_tool.py`, `agent/memory_provider.py`, `tools/skills_tool.py`, `tools/skill_manager_tool.py`, `agent/curator.py`, `skills/AGENTS.md` (read only)

## What problem does Hermes's design solve?

- **An agent that learns across sessions.** Two small files (`MEMORY.md`
  for the agent's notes, `USER.md` for the user), with character budgets,
  loaded once per session so the prompt cache holds.
- **Reusable know-how** as skills: a folder with `SKILL.md` (frontmatter +
  instructions) and optional scripts; only an index sits in the prompt and
  the body is loaded on demand.
- **Self-improvement**: after a turn, a background review asks whether
  something should be remembered or turned into a skill; a curator archives
  stale agent-made skills; a hub installs community skills after a scan.
- **Pluggable memory providers** (8 external services) for users who want
  vector or graph memory.

## Do we have that problem?

- **Learning across sessions: yes**, per workspace (the store's tone, the
  investor's preferences) and a little globally (the owner's style).
- **Reusable know-how: yes**, and shared between workspaces — which creates
  a problem Hermes doesn't have: **data leaking between workspaces through
  a skill** (examples from `investor` ending up in `ecommerce`).
- **Self-improvement: yes, but the owner approves** anything that becomes
  shared.
- **External memory providers: no**, not now.

## Simpler version for us

- **Memory** = `workspaces/<id>/memory/MEMORY.md` + a global `OWNER.md`.
  Budgets in characters, frozen per run, written through a gateway tool
  (never by direct file write from the container), scanned for injected
  instructions, visible and editable in the UI.
- **Skills** = `global/skills/<name>/SKILL.md` (agentskills.io-compatible
  format) holding **method only**; examples and data in
  `workspaces/<id>/connectors/skills/<name>/`. Enabled per workspace in
  Setup → Connectors.
- **Agent-written skills** are proposals: a draft goes to the owner, is
  checked for workspace data (names, figures, specific terms), and only
  enters Global Settings when approved.
- **Background review** after a task completes (not after every chat
  message): "anything worth remembering?" → memory write or skill proposal.
- **Curator** later, as a monthly suggestion list rather than automatic
  archiving.

## Deliberately simpler than Hermes

| Hermes                                                        | Us                                    | Why                                                         |
| ------------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------- |
| Pluggable memory providers (honcho, mem0, …)                  | Markdown files only                   | Readable, backed up with the data volume, no extra services |
| Agent creates and edits skills directly, with an audit ledger | Agent proposes, owner approves        | Shared skills cross workspace boundaries                    |
| Skills hub with 4 sources and scanners                        | Local skills first, import by hand    | Supply-chain risk; add a hub later                          |
| Background review after every turn                            | After a task is completed             | Fewer tokens, better signal                                 |
| Profiles each with their own memory                           | Workspaces each with their own memory | Workspaces are our unit                                     |
