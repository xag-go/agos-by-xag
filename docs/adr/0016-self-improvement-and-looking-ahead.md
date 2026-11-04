# ADR 0016 — Self-improvement, looking ahead and Autonomy rules

Status: accepted (2026-10-02)

## Context

The owner asked that each workspace's agents learn from the owner by themselves,
work ahead of the owner (notice what the owner will need and propose it), and never act
beyond what the owner allows. Reference ideas: OpenAI "dots" (background read-only
research, learning from feedback, act / ask / never rules, approval cards),
built inside AGOS's own UI with Hermes as the engine.

## What Hermes already does (checked in the pinned source and on live profiles)

- After a turn, `agent/background_review.py` forks a reviewer that writes
  memory (`memories/MEMORY.md`, `USER.md`) and creates or patches skills.
  The curator (`agent/curator.py`) tidies skills; every skill change goes in
  `skills/.curator_ledger.jsonl` with before/after copies in
  `.curator_backups/blobs/`, and `hermes curator rollback <id>` undoes one.
- It is on in every `agos-<id>` profile today: one busy workspace had 151 skill
  changes in its ledger. Each profile only writes its own home, so learning is
  already per workspace.
- Plugins can veto or gate any tool call with the `pre_tool_call` hook
  (`block`, or `approve` = Hermes's own approval prompt).

## Decision

1. **Learning stays Hermes's own loop**, per workspace. AGOS does not copy it.
   _What I learned_ (workspace settings) lists every ledger change with the
   chat/task it came from and the text before/after, plus _Undo_ (Hermes
   rollback), the current memory and what the owner taught. Learning runs
   without asking (it is undoable). The Autonomy action _Learn_ covers the
   agent's own `memory`/`skill_manage` calls during a job (Never blocks them,
   Ask me waits for Approve); the background review is Hermes-internal and
   stays undoable through this page.
2. **Library skills no longer overwrite what a workspace learned.**
   `sync_skills` keeps the workspace's copy and replaces it only when the
   library skill itself changed (content hash in `.agos-sources.json`).
3. **Owner signals become lessons.** Approve, Request changes, Cancel on board
   cards, Reject and Undo on Co-Founder cards, and Dismiss on suggestions are
   stored in `feedback`. They are given with every run (`_with_agent`, newest
   first) so the next job uses them at once, and written once into the
   workspace's `MEMORY.md` (Hermes's locked writer) so they last.
4. **Autonomy rules (Do it / Ask me / Never)** per workspace, per agent (or
   everyone), for: files, commands, messages, changes in connected apps,
   deletes in connected apps, browser, desktop, images/audio, learning. Enforced
   in code by the `agos-guard` Hermes plugin AGOS installs in every profile
   (`plugins/agos-guard`, always in `plugins.enabled`) and feeds through
   `agos-guard.json` (0600, written only by AGOS). _Never_ blocks before the tool
   runs. _Ask me_ uses Hermes's approval with the mark `[AGOS rule: Ask me]`;
   Full access never answers those (`access.owner_rule`), so they wait for the
   owner's Approve in the app and on the owner's phone. Defaults: messages and app
   changes/deletes ask; the rest runs. The fixed rules of ADR 0010 (sandbox,
   no secrets, other workspaces off-limits, dangerous commands) are unchanged.
5. **Looking ahead (the watcher)**: off until the owner turns it on; default
   every 6 h, at most 5 suggestions. It is a Hermes run of the same workspace
   with session `agos-watch-*`; the guard lets that session use read tools only
   (anything that writes, sends, runs or clicks is blocked whatever the prompt
   says). It reads the board, chats, files, memory and connected apps, and ends
   with an `agos-suggestions` block. Each suggestion becomes a To do card (what,
   why now, evidence, plan, agent); nothing starts until the owner presses
   Start. Cards already on the board, already suggested or dismissed are never
   made again; a dismissal's reason is given to the next check and learned.
   Model: the workspace's default unless the owner sets one.

## Consequences

- One mechanism (the plugin) enforces both the owner's rules and the watcher's
  read-only mode, inside Hermes, not in a prompt.
- A cut watcher run is retried at the next tick; it never stops the schedule.
- Lessons are visible and editable (Identity & memory) and undoable (What I
  learned), so self-improvement never becomes a black box.
