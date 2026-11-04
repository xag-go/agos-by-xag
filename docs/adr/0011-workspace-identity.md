# ADR 0011 — Workspace identity: SOUL.md written by AGOS, memory owned by Hermes

- Status: accepted
- Date: 2026-09-25
- Builds on: ADR 0004 (memory and skills), ADR 0010 (Hermes engine)

## Context

A fresh Hermes profile starts with Hermes's generic `SOUL.md` ("You are Hermes Agent…")
and empty memory. The workspace's agent therefore didn't know which workspace it serves
or how AGOS's board works. The owner also asked that deleting a chat never removes what
the project learned.

## Decision

- **SOUL.md** (identity, slot #1 of the system prompt) is written **only by agos-core**
  into `profiles/agos-<id>/SOUL.md`, atomically, mode 0600, starting with an AGOS marker.
  Content = identity + AGOS's fixed working rules:
  - identity = the owner's text (Workspace settings → Identity & memory), or by default
    the workspace's name and description;
  - rules (read-only for the owner): one workspace only, `/workspace` and `/shared`,
    six board columns, work only from Start, plan first, Clarify when unsure, self-review
    with proof, propose never self-assign, no changing its own access, apply only per
    autonomy.
- SOUL.md is (re)written on create (after the first sync), rename, description change,
  identity edit, and for **every workspace at core startup** (migration of existing
  profiles, and repair if someone edited the file). Invisible and control characters are
  stripped; the identity is limited to 4,000 characters; the rules always come after it,
  so owner text can't replace them.
- **Memory** stays Hermes's own: `memories/MEMORY.md` (2,200 chars) and `USER.md`
  (1,375 chars) per profile, entries joined by `\n§\n`. Nothing is shared between
  workspaces. The owner can read, add, edit and remove entries. AGOS writes with the same
  `.lock` file Hermes's memory tool uses and enforces Hermes's limits. `§` is refused
  inside an entry.
- Everything applies from the **next session or run** (Hermes freezes SOUL and memory per
  session, which keeps the prompt cache).
- **What the agents are told lives in SOUL.md, not in each turn** (2026-10): the rules
  also cover tasks on the board, coming back later (the agent's own cronjob tool) and
  scheduled automations; each team member's SOUL.md has its role and the same rules; the
  Co-Founder's SOUL.md ends with its view of the workspace (apps and tools on / off, how to
  change automations, skills, agents and docs, the team and each member's Hermes),
  rewritten by AGOS whenever it changes (`context_file_max_chars` keeps it whole). A
  chat's name is Hermes's own conversation topic (the agos platform's `chat_topic`). A
  Session given to an agent is that member's own Hermes conversation. AGOS adds to a turn
  only what Hermes can't know: in a guest's chat who they are (once per session), and in
  the Co-Founder's conversations its view again only when it changed after the
  conversation started. Other conversations are recalled with Hermes's own
  session_search, never copied in.
- **Deleting a chat only hides it** (`chats.deleted_at`). Messages, attachments, the
  Hermes session and memory stay. No purge button yet (see PROGRESS decisions).

## Verified

- Unit: `tests/test_identity.py` (SOUL on create/rename/identity edit, rules can't be
  displaced, startup migration, 0600, memory per workspace, Hermes format, limits).
- Live (`AGOS_LIVE_IDENTITY=1 pytest tests/test_identity_live.py`, real Hermes + Docker,
  two throwaway workspaces): A answered "zz-live-…-alpha — sells argan oil to hotels in
  Agadir. Code word: ZEBRA-…"; B answered "…-beta — tracks bakery invoices. Code word:
  NONE." Zero leftover profiles or containers.
