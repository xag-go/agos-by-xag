# ADR 0007 — Messaging channels: one adapter interface, official APIs, conversations bound to workspaces

- Status: accepted (built in step 7 on the AGOS router + Hermes sessions)
- Date: 2026-09-23

> **Since then:** channels are Hermes's own platform adapters inside each
> workspace's gateway (ADR 0010, ADR 0020); AGOS adds its cards and menus through
> its plugin. The `packages/channels` interface and `services/speech` named below
> were not kept, and Buzz support was removed. Telegram is the channel AGOS ships.

- Reference: Hermes Agent @ `28aceb3` — `gateway/platforms/ADDING_A_PLATFORM.md`, `gateway/platforms/base.py`, `gateway/platforms/event.py`, `plugins/platforms/{telegram,slack,discord,whatsapp}/`, `gateway/platforms/whatsapp_cloud.py`, `gateway/delivery_ledger.py`, `gateway/stream_consumer*.py`, `website/docs/user-guide/messaging/` (read only, no code copied)

## What problem does Hermes's design solve?

Reaching the same agent from ~25 chat apps without 25 copies of the logic:

- **One inbound shape.** Every adapter turns its platform's update into a
  normalised `MessageEvent` (text / photo / voice / document / location /
  command, media saved to local files, reply-to, thread). The gateway only
  sees that.
- **One base adapter with capability flags.** Required: connect, disconnect,
  send, typing, image. Optional with graceful fallback: documents, voice,
  edit, buttons for approvals and questions, model picker, choice picker,
  native streaming. A platform without buttons gets numbered text choices.
- **Shared button ids** (`appr:<id>:<choice>`, `cl:<id>:<idx>`) so one
  resolver handles taps from any platform.
- **Per-platform realities**:
  - Telegram: long polling (no public URL), forum topics as separate
    sessions, inline keyboards, edit-in-place streaming, native drafts,
    voice bubbles, reactions as status, a command menu capped at ~60.
  - Slack: Socket Mode (no public URL), app manifest that registers every
    command, ephemeral replies, Block Kit buttons, assistant status line.
  - Discord: mention rules per channel, auto-threads per conversation,
    native slash commands, buttons, voice channels.
  - WhatsApp: two transports — an unofficial bridge (QR pairing, groups,
    ban risk) and the official Cloud API (public webhook, 24-hour reply
    window, no groups, rate limits) — sharing one behaviour layer.
- **Rendering**: markdown converted to each platform's dialect,
  fence-aware chunking to the length limit, tables turned into lists where
  unsupported, `<think>` blocks stripped.
- **Reliability**: reconnect with backoff and jitter, dedupe of repeated
  updates, self-message filtering, a delivery ledger (pending → delivered,
  labelled resend after a crash), a circuit breaker per adapter that alerts
  on another channel, a bot-loop guard.
- **Security**: default deny, allowlists, DM pairing codes, admin tiers,
  identifiers redacted in logs.
- **Extensibility**: adapters are plugins with a manifest; config bridges
  from YAML and environment variables; the setup wizard reads the manifest.

## Do we have that problem?

- **Several apps: yes, over time.** Telegram first, then Slack, Discord,
  WhatsApp and email are plausible for an owner.
- **One owner, not strangers.** Most of Hermes's allowlist / pairing / admin
  machinery exists for bots that anyone can message. We need: "only my
  accounts, everyone else ignored".
- **Our conversations belong to workspaces.** Hermes routes a conversation
  to a session (and a profile). We must route it to exactly **one workspace
  chat**, and never let one conversation reach two workspaces.
- **Tasks, not only chat.** Notifications, approvals and Clarify questions
  come from board tasks, and the owner's answer must land in that task.
- **Plugins from third parties: not now.**

## Our design

### One interface, in `packages/channels`

```ts
interface ChannelAdapter {
  kind: "telegram" | "slack" | "discord" | "whatsapp" | "email";
  capabilities: {
    edit: boolean;
    buttons: boolean;
    threads: boolean;
    reactions: boolean;
    files: boolean;
    voiceIn: boolean;
    voiceOut: boolean;
    typing: boolean;
    maxLength: number;
    markup:
      "telegram-html" | "slack-mrkdwn" | "discord-md" | "whatsapp" | "plain";
  };
  start(onMessage: (m: InboundMessage) => void): Promise<void>;
  stop(): Promise<void>;
  send(to: Address, message: OutboundMessage): Promise<SentRef>;
  edit?(ref: SentRef, message: OutboundMessage): Promise<void>;
  react?(ref: SentRef, status: "seen" | "done" | "failed"): Promise<void>;
  typing?(to: Address): Promise<void>;
}
```

- `InboundMessage`: channel, `Address` (chat + optional thread/topic),
  sender id, text, attachments (already saved, see below), reply-to ref,
  button tap `{ kind: "approval" | "choice", id, value }`.
- `OutboundMessage`: markdown text, optional buttons
  (`[{ label, action }]`), optional files, `silent` flag.
- Everything else (rendering, chunking, streaming, retries) lives **once**
  in the gateway, not in each adapter.

### Connections: many bots, many groups, many topics

Hermes runs one bot per platform (a token lock stops two processes from
sharing it). We go further:

- **Settings → Channels** holds any number of **connections**: several
  Telegram bots, several Slack workspaces, several Discord bots, several
  WhatsApp numbers. Each connection has its own encrypted token, its own
  status and its own circuit breaker; one failing bot never stops the
  others.
- A connection can serve **many groups and many topics**. A Telegram bot
  can sit in five groups, each with its own forum topics.
- **Any chat can have its own place, if the owner wants.** A workspace chat
  can use a dedicated bot, a dedicated group, or one topic in a shared
  group — and several of these at once (the same chat on Telegram and on
  Slack).
- **Creating a topic from AGOS.** When a chat is linked to a forum group, the
  gateway can create the topic itself (named after the chat) and bind it,
  so the owner doesn't set ids by hand.
- One gateway process runs all connections; adding or removing one needs no
  restart.

### Routing: bindings, not guesses

A table `channel_bindings (connection_id, address) → (workspace_id, chat_id)`,
where `address` = chat/group + optional topic or thread. Edited in the
chat's settings ("Where this chat lives") and listed in Workspace settings.
Rules:

1. A message from an address with no binding is **not** delivered to any
   workspace. In a direct chat the owner gets: "This conversation isn't
   linked to a workspace. Link it in AGOS." Nothing else is answered.
2. **One address ↔ one workspace chat**, always. A chat can have many
   addresses (several bots, groups, topics, platforms); an address never
   has two chats. Two topics of one group can belong to two different
   workspaces — each topic is its own address.
3. **Replies route to tasks.** Every outgoing notification is recorded in
   the delivery ledger with its task id. When the owner replies to that
   message (or taps its buttons), the answer goes to that task's Chat tab
   or decision — in the same workspace, checked again on the server.
4. Only the owner's paired accounts are listened to (paired once per
   platform, valid for every connection of that platform). Others are
   ignored silently; Settings shows a count.
5. Task notifications go to the workspace's **notification address** (one of
   its bindings, chosen in Workspace settings), or to Needs you only.

### Per platform

| Channel               | Transport                                 | Mapping                                                                                                     | Notes                                                                                  |
| --------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **Telegram** (step 9) | Bot API, long polling, one poller per bot | Any number of bots; each chat bound to a direct chat, a group, or a forum topic (created by AGOS if wanted) | Buttons, edit-in-place streaming, reactions, voice via `services/speech`               |
| **Slack** (later)     | Socket Mode (no public URL)               | One channel per workspace chat; a task's thread for its Chat                                                | Manifest generated from our command registry; Block Kit buttons                        |
| **Discord** (later)   | Gateway bot                               | One channel per workspace, threads per chat                                                                 | Mentions not needed in bound channels; buttons                                         |
| **WhatsApp** (later)  | **Official Cloud API only**               | One number; a conversation is bound to one workspace, `/workspace` switches the binding                     | Needs a public HTTPS endpoint (Tailscale Funnel or a tunnel); 24-hour window respected |
| **Email** (later)     | IMAP poll + SMTP                          | One address per workspace (plus-addressing)                                                                 | Mail bodies are untrusted content (read vs act)                                        |

### Shared behaviour in the gateway

- **Renderer**: our markdown → each `markup`, fence-aware chunking under
  `maxLength`, tables → lists where needed, never splitting inside code.
- **Streaming**: one message edited at most once per second (per platform
  limits); without `edit`, only the final answer is sent.
- **Buttons**: approvals and Clarify use one id format; taps are validated
  against the pending request (workspace, task, expiry) before acting.
- **Commands**: one registry → Telegram menu, Slack manifest, Discord slash
  commands, web autocomplete. Commands are owner decisions (start, approve,
  model), never shell access.
- **Files**: inbound files are saved by the gateway into the bound
  workspace's `files/inbox/` (size and type limits); they count as
  untrusted content. Outbound files must resolve inside that workspace's
  roots (`resolveSafePath`), so an agent can't send a file from elsewhere.
- **Reliability**: inbound dedupe stored in SQLite (survives restarts —
  Hermes keeps it in memory), delivery ledger, reconnect with backoff and
  jitter, circuit breaker per adapter with an alert in the web app and on
  another channel, bot-loop guard.
- **Secrets**: bot tokens encrypted, held by the gateway only.
- **Notifications**: progress silent, finals and "needs you" notify —
  following Settings → Notifications.

## Deliberately simpler than Hermes

| Hermes                                                                           | Us                                                                                | Why                                                  |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Adapters as plugins with YAML/env bridges and a setup wizard driven by manifests | Adapters as modules implementing one TypeScript interface; settings in the UI     | No third-party adapters yet; fewer moving parts      |
| ~25 platforms                                                                    | Telegram, then Slack / Discord / WhatsApp / email when needed                     | Each one done fully (buttons, files, voice)          |
| One bot per platform (token lock)                                                | **Many connections per platform**; each chat can have its own bot, group or topic | Where we go further than Hermes                      |
| Unofficial WhatsApp bridge (QR, groups) next to the Cloud API                    | Cloud API only                                                                    | Ban risk and terms of service                        |
| Allowlists, pairing codes for strangers, admin tiers, guest mode                 | Owner's accounts only; everyone else ignored                                      | Single-owner product                                 |
| Session key from platform/chat/thread/user, per-user sessions in groups          | Explicit binding: address → one workspace chat                                    | Workspace isolation must never depend on a heuristic |
| `MEDIA:/path` tags with allow-dirs and "trust recent files"                      | Files resolved through the run's roots                                            | Same boundary as every other file access             |
| In-memory update dedupe                                                          | Stored dedupe                                                                     | Survives restarts                                    |
| Terminal tool on chat platforms                                                  | No tools reachable from a channel except through the workspace's agent            | A chat message is never a shell                      |

## Update (2026-09-25): built on AGOS's own router, beside Hermes

- **One AGOS router** (`actions/channels.py`) for every connection, not Hermes's
  per-profile gateway adapters: a Telegram bot token can be polled by only one process,
  and there is one Hermes process per workspace. The router polls outbound only
  (Telegram `getUpdates` long polling; Buzz through the `buzz` CLI with the key in the
  child's environment), maps address → workspace chat, and posts the message exactly
  like one typed on the web. Web and Telegram/Buzz are one conversation.
- **Settings → Channels**: any number of Telegram bots (token tested with `getMe`,
  encrypted with AGOS's master key, shown as ••••last4) and Buzz connections (relay URL +
  nsec; the card explains when the `buzz` CLI is missing). Each connection has an
  allowed list (the owner's ids/usernames); everyone else is ignored.
- **Status lamp** on each connection card and on each chat's "Where": green after a good
  poll, red with the reason (token revoked 401, relay unreachable, no answer for 2
  minutes), pulsing while connecting, Retry. The page polls every 4 s, so no reload is
  needed.
- **"Where" per chat**: web only, or also a Telegram group/topic (AGOS can create the
  topic with `createForumTopic`) or a Buzz channel, or several. One address = exactly one
  workspace chat (unique index; a second chat or workspace gets 409). The old per-workspace
  Telegram group/topic fields are kept in the DB and shown read-only (nothing lost).
- **No lost or double messages**: `channel_seen` dedupes incoming updates. Every agent
  reply is queued once per address in `channel_outbox` (unique on message + address)
  and sent with retries. Linking a new address never re-sends old replies. A restart
  resumes from the saved cursor.
- **Board notifications** (Clarify, waiting for approval, Blocked incl. limits,
  Complete, automation failures) go to the chat address marked "board notifications",
  following Settings → Notifications (instant only; digest/silent are not sent).
  "Waiting for approval" has Approve / Request changes buttons (Telegram inline
  keyboard; Buzz gets text instructions). A reply to a Clarify notification lands in that
  task's chat. `/task <title>` creates a To do card; `/model` shows the chat's model.
  An archived workspace answers that it is archived.
- Tests: a fake Telegram Bot API (real HTTP server) covers connect, one conversation,
  restart (no re-send), strangers, duplicates, unlinked addresses, one address = one
  chat, token revoked → red → Retry → green, archived workspace, notification buttons,
  reply → task, `/task`. Buzz is covered at the driver level (validation, missing CLI).

## Update (2026-10): notifications and Telegram on Hermes

- **Kanban news are Hermes's own notifier.** AGOS no longer reads the board's events
  (kanban_news is gone, with its /kanban-event bridge call and its slow safety pass).
  When Hermes's dispatcher starts a card that no chat follows yet, the agos-guard
  plugin's `kanban_task_claimed` hook subscribes the Co-Founder's own Hermes conversation
  to it (`kanban_db_notify.add_notify_sub`, `notify+wake`, stamped with the gateway's
  profile), exactly as Hermes subscribes the chat a card was made in. AGOS only writes
  where that conversation is into the bridge file (`notify`: its Telegram chat when the
  Co-Founder's chat lives there, else its AGOS chat on the agos platform). Hermes sends the
  line and wakes the Co-Founder, whose SOUL.md says how to tell the owner (a question on a
  card is asked in the Co-Founder's own words; the owner's answer goes on the card with
  kanban_comment + kanban_unblock). Every workspace gets its Co-Founder chat when its
  profile is set up (also Hermes's home channel).
- A phone reply to a ❓ message is no longer caught by AGOS: it is a message to the
  Co-Founder, who puts it on the card. The per-turn "cards waiting" text is gone too.
- **`/task` is Hermes's skill command.** AGOS writes one shared skill folder
  (`<data>/agos-skills`, today only `task`) that every workspace root and member reads
  through `skills.external_dirs` (next to the AGOS Brain). `/task <what>` in AGOS or
  Telegram reaches the Co-Founder's Hermes as its skill command, which makes the card with
  its own kanban_create (Hermes then follows the card in that conversation). AGOS no
  longer catches `/task` or `/model` from the bot; only the one-time `/start <code>`
  link to the owner's account and AGOS's own buttons stay AGOS's.
- A turn Hermes starts on its own in an AGOS chat (a card's wake, a job's delivery)
  answers none of the owner's messages: one the owner sent just before is still handed over.
- **Kept in AGOS** (no Hermes equivalent): the outbox to Telegram for AGOS's own
  decisions with buttons (Allow once / Deny on a card's command, the token watch,
  Co-Founder actions, capability requests, automation proposals), the room → Telegram
  relay (Hermes rooms have no Telegram), the mirror of turns into AGOS chats, and the
  bot setup.

## Update (2026-10): Telegram's router, cards and allowlist are Hermes's

- **Who may talk to the bot is Hermes's own allowlist.** The agos-guard plugin asks the
  gateway (`_is_user_authorized_for_source`, the same check Hermes runs right after its
  `pre_gateway_dispatch` hook) and hands AGOS only what an allowed person says, marked
  `authorized`; a stranger is Hermes's to turn away (pairing or silence). Only the
  one-time `/start <code>` link reaches AGOS from someone not yet allowed. AGOS's own
  sender check, its duplicate check (`channel_seen`) and its router are gone. AGOS keeps
  writing the allowlist (`TELEGRAM_ALLOWED_USERS`) from the bot's setup.
- **An approval in an AGOS chat is Hermes's own Telegram card.** Hermes's approval hook
  asks AGOS where the chat lives on the phone (its own Telegram place, else the
  Co-Founder's); the agos platform's approval prompt then has the workspace's Telegram
  adapter send its own Allow / Deny card there for that AGOS conversation's session key
  (`send_exec_approval`), so Hermes's buttons resolve it (`resolve_gateway_approval`),
  check who pressed and close the card themselves. Answered in AGOS, the plugin edits
  that card. The adapter is shared by every profile the root's gateway serves.
- **AGOS's own button presses** pass Hermes's own button check
  (`_callback_authorized`) before they reach AGOS.
- **Gone (no AGOS card any more):** the Co-Founder's actions (✅ Done / Undo, Try again),
  capability requests, proposed tasks and automation proposals on the phone (the
  Co-Founder's Hermes conversation says what it did; Hermes's own approval card asks
  first), the "automation failed" notices (Hermes's cron `failure_deliver`), and the
  Telegram driver AGOS still carried (`engine/channels.py`).
- **The outbox that stays** is sent by the workspace's gateway with Hermes's own send
  (its Telegram formatting and splitting) for replies, and as one message with its
  buttons for AGOS's own cards: the replies of chats AGOS answers itself (a group's
  Hermes room, a member's topic: Hermes rooms have no Telegram), the owner's `/command` typed in
  AGOS shown in Telegram, the link's welcome line, and the cards about AGOS's own state
  (a Kanban card's Allow once / Deny, a card's token warning, a room member's command).
- **Needs you** reads what Hermes holds: approvals waiting in conversations (Hermes's
  approval hooks), cards its board holds blocked for the owner's OK or with a question, cards
  past their usual tokens (Hermes's count), automation runs and proposals (its cron and
  board).
