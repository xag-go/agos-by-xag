# ADR 0015: Capabilities and Connectors (apps)

Status: accepted (2026-09-26)

## Context

The owner wants Settings organised the way ChatGPT does it:

- **Capabilities**: Skills, Agents, MCP, Tools. Each workspace turns them on or off.
- **Connectors**: apps that log in with the owner's account (Notion, Canva, Figma…). The owner connects each
  one once, then turns it on or off per workspace.
- **Plugins**: later. Hermes plugins run inside the Hermes host process with full rights, so
  they can't be isolated (ADR 0003).

Tools must be fully usable and must not affect the owner's computer.

## Decision

### Settings

- The global Settings nav shows a **Capabilities** group (Skills, Agents, MCP, Tools) and a
  **Connectors** page. The Plugins page is removed from the nav. The plugin rows in the
  library stay in the database, unused.
- In each workspace, settings → **Capabilities** (renamed from "Connectors";
  `/settings/connectors` redirects) is one page of ON/OFF switches: Skills, Agents, MCP, Tools
  and **Connectors (apps)**. Everything starts off.

### Where the apps come from

1. **Hermes's approved catalog** (`optional-mcps/`, 65 entries read with Hermes's own parser
   `hermes_cli.mcp_catalog.list_catalog`). These are vendor-hosted HTTP MCP servers with no
   middleman and no subscription.
   - 61 can be connected.
   - Locked, with the reason shown: Asana and Cloudflare (they need the owner's own
     developer app or key), and n8n and Unreal (local addresses).
2. **Nous hosted apps** (Gmail, Google Drive…): one row, "Nous apps". It is available only when
   Hermes's own gate `connectors_available()` says yes, which needs a Nous Portal login with
   Nous's `managed_tools` claim. Today the owner is logged in, but Nous hasn't opened apps
   for the account, so the row shows that reason. When it opens, the workspace switch removes
   `connections` from `agent.disabled_toolsets`.
   - AGOS never logs in to Nous itself: that would change the owner's root Hermes login.

### Login (connect once)

- "Connect" runs `engine/connect_helper.py` with the Python that runs Hermes and
  `HERMES_HOME = agos-data/system/connectors`. The helper refuses to run if that path is
  `~/.hermes` or inside it.
- Hermes's own dashboard OAuth bridge (`DashboardOAuthFlow`) handles discovery, client
  registration, PKCE, state checking, token exchange and refresh. AGOS only carries the two
  browser steps:
  - The helper prints the app's login URL; the web app opens it.
  - The app redirects to `/connectors/callback` on AGOS. The web app posts `state` + `code`
    to the core, which hands them to the helper. The state must match exactly and works
    only once.
- The return address must be `http(s)://<AGOS host>/connectors/callback`. Plain `http` is
  accepted only for localhost.
- A login that takes more than 15 minutes is dropped. Starting a new login for the same app
  replaces the old one.
- The tokens are Hermes's own files: `connectors/mcp-tokens/app-<name>.json`. They are never
  in AGOS's database, never in `~/.hermes`, and never in a sandbox.

### Use (ON/OFF per workspace)

- While an app is ON in a workspace, its profile gets:
  - `mcp_servers.app-<name>` = `{url, auth: oauth}` (plus the catalog's default tool
    excludes). The `app-` prefix means a library MCP server can never take its place.
  - `profiles/agos-<id>/mcp-tokens` as a link to the one token folder: one login and one
    refresh. Hermes's refresh lock is a file lock on the same file, so two workspaces
    never refresh at the same time.
- When no OAuth app is on, the link is removed. AGOS never replaces a real `mcp-tokens` folder
  that holds files; it refuses instead.
- An app that is OFF has no server entry, so that workspace's agent has no tool for it.
- The calls run in the Hermes gateway (host) as plain HTTPS to the vendor's official server.
  Nothing runs on the computer and no file of the owner's is read.
- **Disconnect** deletes the token files, turns the app off in every workspace, and rewrites
  their profiles.

## Consequences

- Tested: `tests/test_apps.py` (8 tests, with a fake login process):
  - connect once, on in workspace A only, link and server in A and not B
  - off removes both
  - disconnect removes the app everywhere
  - wrong state or a reused state is refused
  - failed login
  - refusals: locked app, non-local http return address, unknown app, Nous without login
  - no-login app, and the Nous `connections` toggle
  - the link refuses a real token folder
  - catalog locks
- Verified live:
  - Settings lists 66 rows.
  - Notion's Connect opened the real Notion login page, with Hermes's registration done in
    AGOS's folder. It was stopped there because it is the owner's account.
  - A fake callback was refused.
  - DeepWiki switched on in a throwaway workspace: `hermes -p agos-<id> mcp test app-deepwiki`
    connected and found 3 tools.
  - The throwaway workspace was purged through the app: no profile, container, network or
    rows left.
- Still to verify live: a full OAuth login needs the owner (their account). Nous apps need Nous to
  open connectors for the owner's account.
- A running gateway picks up the change after its next restart (same as other capabilities).

## Addendum: the Co-Founder asks from a chat

The owner can tell the Co-Founder (in the app or on Telegram) "connect Notion" or
"turn on the SEO skill". The Co-Founder never changes anything itself:

- Its instructions list what exists in this workspace (apps, skills, agents,
  MCP, tools) with ON/off, "not connected" and "locked".
- It ends its answer with one `agos-capabilities` block. AGOS stores only asks
  for known, unlocked things that would actually change, max 3 per answer,
  no duplicates of a pending ask. Nothing changes yet.
- The chat shows a card (Approve / No). A Telegram-linked chat gets the same
  card with buttons. A button only counts from a chat the card was sent to.
- Approve runs the owner's own Capabilities switch. An app that isn't
  connected opens its login first (only from the app on the computer; the
  phone button says so) and is turned on when the login returns.
- The Co-Founder is then told in the chat and carries on with the new tool.

Verified live: a real Co-Founder asked for DeepWiki, the owner approved in the
app, and the Co-Founder used `read_wiki_structure` in its next answer.
