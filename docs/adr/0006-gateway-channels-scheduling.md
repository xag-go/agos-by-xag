# ADR 0006 — Gateway: one process, Telegram first, owner-only, durable delivery

- Status: superseded by [0010](0010-hermes-engine.md) — Hermes Agent provides this; kept for history
- Date: 2026-09-23
- Reference: Hermes Agent @ `28aceb3`, `gateway/AGENTS.md`, `gateway/run*.py`, `plugins/platforms/telegram/`, `gateway/pairing.py`, `gateway/delivery_ledger.py`, `cron/` (read only)

## What problem does Hermes's design solve?

- **Reaching the agent from 25+ chat platforms** with one normalised message
  event and adapters as plugins; streaming by editing one message; buttons
  for approvals and questions; voice in and out.
- **Strangers on public bots**: default deny, allowlists, DM pairing with
  hashed short-lived codes, lockouts, bot-loop guards, admin tiers.
- **Replies that must not be lost or doubled**: a delivery ledger with
  at-least-once semantics and labelled resends after a crash.
- **Scheduled work** that must fire once per slot, survive restarts, catch
  up after downtime, and pause while a quota window is closed.
- **Many profiles sharing one bot and one process** (multiplexing, profile
  routing, secret scopes) — a large part of its complexity.

## Do we have that problem?

- **Many platforms: not yet.** Telegram first; others later behind the same
  interface.
- **Strangers: barely.** One owner per installation. Still: the bot must
  ignore everyone else, and pairing the owner's account once is enough.
- **Lost or doubled replies: yes.** Telegram outages and restarts happen.
- **Scheduling: yes** (Setup → Automations).
- **Multiplexed profiles: no.** Workspaces are rows, not processes.

## Simpler version for us

- **One gateway process** with modules: `runner`, `scheduler`, `channels/`,
  `delivery`, `broker` (tools). It supervises workspace containers.
- **Channel interface**: `receive() → ChannelMessage`, `send`, `edit`,
  `buttons`, `typing`, capability flags. Telegram is the first adapter.
- **Owner-only**: the owner pairs their Telegram account once (a one-time
  code shown in Settings, hashed, 10-minute expiry). Every other sender is
  ignored silently; the owner sees a count in Settings.
- **Routing**: one Telegram group, one topic per workspace chat (set in
  workspace settings). A message in a topic belongs to that workspace only.
- **Streaming** by editing one message; approval and Clarify as buttons;
  reactions 👀 / 👍 / 👎 as status; progress messages silent, final ones
  notify.
- **Delivery ledger** in SQLite: pending → sending → delivered | failed,
  retries with backoff, a resend after a crash is labelled.
- **Scheduler**: `next_run_at` computed from the cron and advanced
  **before** a run starts (no double fire), a catch-up window of half the
  period, a skip when an account limit is reached (logged), one run at a
  time per automation. Automations are created by the owner only.
- **Commands** from one registry (help, Telegram menu, web autocomplete).

## Deliberately simpler than Hermes

| Hermes                                                     | Us                                           | Why                                     |
| ---------------------------------------------------------- | -------------------------------------------- | --------------------------------------- |
| 25+ adapters, relay, hosted multi-bot rooms, scale-to-zero | Telegram, then a few more                    | Build the interface right once          |
| Allowlists, pairing, admin tiers, guest mode               | Owner pairs once; everyone else ignored      | Single-owner product                    |
| Multiplexed profiles and secret scopes in one process      | Workspaces are data; isolation is containers | Removes their largest complexity source |
| Terminal tool on chat platforms by default                 | Tools only in workspace containers           | A chat message is never a shell         |
| `/update` self-updates a live install from chat            | Updates via new image version                | Reproducible, rollback by tag           |
