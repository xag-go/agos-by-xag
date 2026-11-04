# ADR 0020 — One Hermes root per workspace; group chats are Hermes rooms

Date: 2026-10-13 · Status: accepted (owner, 2026-10-13: each workspace its own Hermes
root, groups as Hermes rooms that the Co-Founder directs, one shared subscription
login and shared API keys)

## Problem

Every workspace was a profile of the one AGOS Hermes home (`~/.hermes/profiles/agos-<ws>`,
its members `agos-<ws>--a-<agent>`). One home held every workspace's Kanban dispatcher,
cron, plugins and secrets side by side, every gateway ran on a temporary Hermes shim
(`gateway.standalone: true`), and group chats were AGOS's own orchestration (the
Co-Founder's `agos_handoff` tool, AGOS choosing who speaks next) instead of Hermes's.

## Decision

1. **One root per workspace.** A workspace's Hermes is a Hermes home of its own,
   `<AGOS_HERMES_ROOTS>/agos-<ws>` (default `<AGOS_DATA_DIR>/hermes`, never under
   `~/.hermes`, which Hermes maps back to itself). Its **default profile is the
   Co-Founder**; each team member is a profile under it (`profiles/a-<agent>`). The
   root's one gateway serves the Co-Founder and every member (Hermes multiplexing; no
   standalone shim). AGOS keeps its own names everywhere (`agos-<ws>[--a-<agent>]`);
   `engine.profile_home` / `home_of` / `hermes_name` map them to the root. A root is
   AGOS's when it carries `.agos-root`. Every Hermes process AGOS starts gets
   `HERMES_RUNTIME_DIR` (the install's runtime): without it a home outside
   `~/.hermes` installs a runtime of its own and rewrites the shared launcher.
   Sandboxes are labelled with AGOS's name (`terminal.docker_shared_container_key`):
   every root's Co-Founder is "default". New workspaces get a root; existing ones move
   with `python -m agos_core.migrate_root <ws> --dry-run | --run | --check`.
2. **Group chats are Hermes hosted rooms, run exactly as Hermes runs them** (owner:
   "AGOS is only the web UI where I see and control; Hermes 100% engine"). The owner's
   message goes in as written: Hermes decides who answers (the members the owner
   @mentions, or everyone; each replies or passes; at most 3 rounds / 10 messages).
   The Co-Founder is one member of the room (@cofounder), not a director; AGOS writes no
   room rules and never adds a turn of its own (no continuation, no recap). AGOS
   only bridges it (`actions/rooms.py`, the agos-guard plugin's `rooms.py` inside the
   root's gateway): the room log becomes the chat's messages under each member's
   name, once; Telegram gets them like any reply; a member picked in Telegram's "/"
   menu is that member's @mention; Stop is Hermes's `stop_room`; a member's command
   approval is a card and a Telegram button answered with `approve_room_task`
   (once / deny). A membership change disbands the room and makes the next
   generation (a gateway room's roster is frozen); AGOS's history stays. A roster
   only names the root's own profiles, and Hermes refuses any other: the wall
   between workspaces.
3. **General Settings still apply to every workspace at once.** Nothing is inherited
   across roots any more, so AGOS writes them:
   - **API keys** (one shared set): saved once, written into every root and every
     member `.env`, and into each new or migrated one (`actions/general_sync.py`). A
     key a workspace set itself wins; AGOS only ever removes its own copies.
   - **Subscription logins (Claude, ChatGPT, …) are each root's own** (revised
     2026-10-18). Hermes keeps one OAuth login per home and never shares a
     single-use refresh token between homes (its docs: sign in in each home, or
     share one `HERMES_HOME`). So each workspace signs in in its own root with
     Hermes's `hermes auth add <provider>`; its members read the root's login
     through Hermes's profile fallback. General Settings → Models lists every
     workspace and walks through the ones not signed in yet. Once a root has its
     own login, Hermes stops borrowing Claude Code's file there
     (`auth.adopt_external_logins: false`). AGOS never reads, moves or writes a
     token. (Before: AGOS moved one login into `~/.claude/.credentials.json` for
     every root to borrow — AGOS doing Hermes's job; removed.) Copilot (a token,
     shared as a key) and Nous (Hermes's own shared store) stay one login.
     One login for every root from General Settings needs a Hermes feature
     (a shared login store like Nous's for Claude/Codex): proposed upstream.
   - Limits, rules, tool services and the rest were already written per profile
     through `profile_home`, which now follows each workspace's layout.

## Consequences

- Each root costs disk for Hermes's own dependency env (`installs/`, ~120 MB+, no
  override) and caches.
- One subscription login per workspace: a new workspace is connected once (Settings
  → Models, or its own settings) before it can use a subscription model.
- A room holds at most 6 members (the Co-Founder and five).
- Backups hold each root as Hermes's own backup (`hermes/roots/<name>.zip`).
- Supersedes the group-chat parts of ADR 0013/0014 (AGOS's handoff orchestration).

## Update (2026-10-15): roots are the only layout

Every live workspace is on its own root, so the pre-root code is gone:
`AGOS_HERMES_ROOTS=off` and `AGOS_HERMES_ROOTS_FOR_NEW` (off is now a config error),
the shared-home `agos-<ws>` profiles and their `hermes -p` calls, AGOS's own group
orchestration outside rooms (`agos_handoff`, choosing speakers, Co-Founder/member group
prompts) and the member wake/idle lifecycle (the root's one gateway serves members;
Hermes's dispatcher starts their cards). AGOS only checks that each root's gateway
runs (Hermes's systemd service, or the `spawn` supervisor in tests). A workspace
still in the shared home is never run from it nor given a fresh root over it: it is
moved with `migrate_root`, which drives the old profiles itself; `--rollback` is
gone (the backup keeps the old profiles). The shared home keeps only General
Settings' login and keys.

## Update: each workspace owns its skills (replaces the shared folder below)

- A skill belongs to ONE workspace, like its agents and MCP servers: its row in
  `library_items` has the workspace, and the same name in two workspaces is two
  separate skills. Its files live once, in the workspace's root:
  `<root>/skills/agos-library/<name>/` (the Co-Founder's local skill folder).
- The Co-Founder reads them as its own local skills; the owner's edits and the
  Co-Founder's `update_skill` / `create_skill` cards are Hermes's `skill_manage` there
  (one ledger, Undo = `rollback_entry`). Every member profile of the workspace has
  that folder in its `skills.external_dirs`, so it reads the Co-Founder's current text
  and cannot change it (the agos-guard refuses `skill_manage` on external skills).
  The Co-Founder never lists its own folder as external.
- Shared by every workspace: only AGOS's own skills (`agos-skills/`) and the Brain's
  (`brain/skills/`). Off in a workspace stays Hermes's `skills.disabled`.
- Added from inside the workspace (Workspace Settings → Capabilities): created,
  imported from this machine, installed from the web (`hermes skills install
--category agos-library` in the root: the root's hub lock keeps it; the hub's
  GitHub token stays in the library home and is given to that process only), or
  copied from another workspace (an independent copy). Deleting one is Hermes's
  `curator archive` (recoverable). No Sync / Use-library-version any more.
- The walled gateway reads the folder (it is inside its root); a skills dir of
  another root named in a config is never opened (engine/wall.py).
- One-time move at start (actions/skills_move.py): each old shared skill that is
  on in a workspace (or that the workspace had changed) becomes that workspace's
  own; an own version is kept and gets only the files the library copy had in
  addition (none of its files is overwritten or removed); the old folder is moved
  to `global/skills.retired-<UTC stamp>` (never deleted).

## Update: skills are Hermes's, one shared folder (superseded above)

- The library's skills (`<AGOS data>/global/skills/`) and the Brain's
  (`<AGOS data>/brain/skills/`) are stored once and are `skills.external_dirs` of
  every root and member profile. Both are in AGOS's data dir, which no sandbox grant
  can mount; Hermes mounts them read-only itself (accepted by the sandbox check).
- Off in a workspace = Hermes's `skills.disabled` of its profiles: every library
  skill not turned on there, plus Hermes's own entries (Brain "Not here", …). A new
  library skill is put in every workspace's `skills.disabled` before its folder
  appears.
- No per-profile copies. A workspace has a skill of its own only on purpose: the
  Co-Founder's `update_skill` makes its own version (a Hermes local skill of the same
  name in `skills/agos-library/`, which Hermes prefers); the owner syncs it to the
  library or drops it (Connectors). The agos-guard refuses `skill_manage` on a skill
  Hermes resolves to an external dir, so no workspace writes into the shared one.
- Cleanup of live profiles, at every apply (so at start via resync; safe to repeat):
  in `skills/agos-library/` only, a copy equal to the library's, unchanged since AGOS
  copied it, or of a skill gone from the library is removed; one the team changed
  stays as the workspace's own version. Other skill folders are never touched.
- `/workspace/playbooks/skills` is gone (agents read skills natively); AGOS removes
  only the files it wrote there, as it wrote them. `playbooks/agents` and
  `playbooks/automations` stay: a member's role is in its own profile's SOUL.md (out
  of the Co-Founder's sandbox) and Hermes's cron list shows only a 100-character prompt
  preview and no team steps.

## Smaller pieces handed to Hermes (Phase 7)

- Telegram QR bot setup: Hermes's own client (`hermes_cli/telegram_managed_bot.py`,
  run in Hermes's runtime); AGOS only holds the pairing and saves the bot.
- The owner's timezone: Hermes's own `timezone` key, written with `hermes config
set` into the shared home, every root and member (general_sync keeps new homes
  in step); AGOS reads it back and keeps no copy.
- Backups: Hermes's part is only `hermes backup` (shared home + each root). AGOS
  keeps the encryption, agos.db and workspace files, schedule and rehearsal, and
  strips auth.json from Hermes's zips (Hermes has no option for that).
- Google stays AGOS's (engine/google.py says why): `hermes mcp login` is MCP
  OAuth 2.1 against a server that advertises it (CIMD/DCR, per-root tokens), which
  workspace-mcp in single-user mode and Google's OAuth are not.

## Chats and turns are Hermes's sessions (Phase 2, chats)

- A message written in AGOS is handed at once to the chat's Hermes conversation
  (the agos platform in the root's gateway). Messages one after another are one
  turn by Hermes's own inbound text batching (`text_batch_delay_seconds`, at its
  2 s ceiling); a message while it works is Hermes's `busy_input_mode: steer`.
  AGOS has no gathering pause, no queue, and starts no answer after one ends.
- Each inbox item is confirmed to AGOS only after Hermes has it (the platform
  confirms a text batch when it went in); an unconfirmed one is handed again after
  a minute. A gateway that dies mid-answer is Hermes's own recovery (its active-turn
  marker → `resume_pending` → auto-resume); AGOS re-sends nothing.
- AGOS adds nothing to a turn: `pre_llm_call` returns no context, the Co-Founder's
  view is only in SOUL.md (Hermes keeps a conversation's system prompt for its
  prompt cache: a new conversation reads the current one). What only one
  conversation is told (who a member's chat is with, what the learning
  conversation is for) is Hermes's per-channel prompt (`MessageEvent.channel_prompt`);
  a Kanban card's chat names its card in the conversation's topic.
- Hermes's answer is never changed: `transform_llm_output` is gone, `post_llm_call`
  (fired before Hermes sends) only mirrors it into the AGOS chat.
- Still AGOS's, because Hermes has no such thing: an edit or delete of a message
  already answered is told with the owner's next message (Hermes's sessions have no
  message edit); the owner's decisions on cards are said in the learning
  conversation (Hermes's background review and curator learn only from
  conversations).
- A reply in AGOS is Hermes's own reply context (`reply_to_text`, the part the owner
  selected or the whole message; `reply_to_is_own_message` for the agent's): the owner's
  words go as written, Hermes adds its `[Replying to: …]`. The owner's files are the
  message's own media (Hermes reads them).

## Update: a workspace's capabilities and the owner's rules are Hermes's config

- What a workspace has on lives only in its root's Hermes config (the Co-Founder's,
  the root's default profile), read there and changed there with `hermes config
set` (`actions/hermes_config.py`):
  - MCP servers: `mcp_servers.<name>` with Hermes's own `enabled` switch and
    `tools.include` filter; the key in the root's `.env` (`AGOS_MCP_<NAME>`,
    referenced as `${…}`). An entry is an open mapping in Hermes
    (`_OPEN_DICT_TOP_LEVEL_KEYS`; the MCP client reads only its own keys), so AGOS
    keeps under `agos:` what Hermes has no key for: a local server's command (it
    runs in the workspace's own container, never on this machine) and the header a
    key is sent with. AGOS's row of a server is only its id, name and label; a
    server added with `hermes mcp add` gets one; one that would run a command on
    the host is left out at the next apply.
  - Apps: an app is ON while its `mcp_servers.app-<name>` entry is there (Hermes's
    `enabled: false` while its login is missing); Google's apps are one entry,
    `app-google`, whose `agos.apps` lists them; Nous apps are the `connections`
    toolset. The login bookkeeping and Composio stay AGOS's (no Hermes store).
  - Tools: the owner's switches are `platform_toolsets.*` (a tool the owner turned on
    stays listed even under the owner's Autonomy "Never"); `agent.disabled_toolsets` is
    what really runs (Hermes applies it last, `tools_config._get_platform_tools`).
    A toolset in neither list (new from Hermes) is on. A sandbox sync no longer
    resets `agent.disabled_toolsets` of an existing profile.
  - Library skills: off = the root's `skills.disabled`; plugins: `plugins.enabled`.
  - The owner's notes on an item (shown in AGOS only) are `connector_notes`.
- Members: Hermes profiles inherit no config from each other
  (`hermes_cli/profiles.py`), so each member gets the root's settings copied in.
  Who the member is lives in its own profile only (see "the team is its Hermes
  profiles" below).
- The owner's rules are entries of the shared Hermes home's `memories/USER.md`
  (the home General Settings writes), the one place AGOS reads and edits them; like
  General Settings' keys they are written into every root's and member's USER.md.
  A rule's id is its text's hash. Which workspace proposed one is kept beside it
  (`<AGOS data>/owner-rules.json`), never in what the agents read.
- Live data moves once (safe to repeat): at start the `owner_rules` rows go into
  the shared USER.md (in order, never twice), then the table is emptied; each
  workspace's `workspace_connectors` rows (non-agent), `workspace_apps` rows and MCP
  definitions with their sealed keys are written into its root (config + `.env`) at
  its next apply (every workspace at start, archived ones too), checked by reading
  the root back, then the rows go (an MCP row keeps its id with an empty
  definition). A workspace without a root keeps its rows, read as they are.
- Stays AGOS's: Composio keys and the local MCP containers. The tool services'
  record (`tools.services`) went in step 23: the service shown is the one each
  profile's Hermes uses, read with Hermes's own picker
  (`tools_config_providers._detect_active_provider_index` over `_visible_providers`,
  Nous rows through its account check), cached only while the home's
  config/.env/auth.json are unchanged; the old record was moved into the
  connectors home once and deleted.

## Update: the team is its Hermes profiles

- Who is on a workspace's team is the root's member profiles (`profiles/a-<name>`,
  Hermes's profile list; a tombstoned one is gone). A profile made with
  `hermes profile create a-<name>` in the root is a member too.
- Everything about a member is its own profile's Hermes data, read there each time
  and written there only (`actions/team.py`):
  - job title (the owner renames it): profile.yaml `display_name`, Hermes's
    presentation name (max 64 characters, `hermes profile show` prints it);
  - what it's for: profile.yaml `description` (`hermes profile describe --text`;
    the title when the owner wrote none), which Hermes's Kanban decomposer routes by;
  - role text and the owner's notes for it here: its SOUL.md, each between markers;
  - model: its config's `model.*` and `agent.reasoning_effort`;
  - skills: its config's `skills.auto_load`;
  - off the team: Hermes's `gateway.parked` marker (the root's gateway stops
    serving it within its 30-second rescan; its memory stays). Hermes's docs allow
    making the marker by hand (user-guide/multi-profile-gateways.md);
  - what Hermes has no key for: profile.yaml `ui_meta.agos` (the rule files it
    reads; whether its model is its own or follows the workspace's), the place an
    app keeps its facts about a profile (tui_gateway `profiles.configure`).
    Hermes has no CLI for `display_name` of a named profile nor for `ui_meta`, so AGOS
    writes profile.yaml the way Hermes's own `write_profile_meta` does (only its
    fields changed, every other key kept, atomic).
- AGOS keeps one bare `library_items` row per member (id and name: the web's links
  and the Connectors list use ids), made for a new profile and dropped with it.
  `agent_versions` (AGOS's history of an agent's texts) stays: Hermes keeps none.
- Live data: an agent row from before (title, summary, definition; on/off and the
  notes in `workspace_connectors`) moves into its profile by itself, at start and
  in the background loop (`team.move_rows`): the profile is made when missing
  (parked when the agent was off), written, read back, then the row keeps only its
  id and its `workspace_connectors` row goes. Safe to repeat; a workspace without
  its root waits.

### The fixed working rules stay in SOUL.md

AGOS's fixed rules (`engine/identity.RULES`) were to become one shared skill read
from `skills.external_dirs` and loaded with `skills.auto_load`. Hermes does not load
such a skill everywhere SOUL.md is loaded:

- `agent/system_prompt.py` `_auto_load_parts`: no `skills.auto_load` block when the
  agent skips context files;
- `cron/scheduler.py` (run_job): a cron run without a workdir has
  `skip_context_files=True` but `load_soul_identity=True` ("SOUL.md always").
  AGOS's automations and the agents' own follow-ups are cron jobs without a workdir,
  so they would lose the rules (among them the ones for scheduled runs and how to talk
  to the owner) while SOUL.md still reaches them. The rules stay in each SOUL.md.
