# ADR 0023 — No keys outside Settings → Keys: masked messages, a Secrets check, key-free backups

Date: 2026-11-02 · Status: accepted (owner, after a key pasted in a chat on 2026-10-02
was found in clear in that workspace's Hermes sessions; "B" for backups)

## Problem

Keys belong only in Hermes's `.env` files, written by Settings → Keys. Three places
broke that:

1. **The owner's own messages.** Hermes masks what the model and the tools say
   (`security.redact_secrets`, on by default), never the user's own message. A key the owner
   pastes into a chat stays in clear in Hermes's session (`state.db`, `messages` and
   its full-text index).
2. **Nobody looks.** Keys already in chat history or in logs, and key files that
   others may read, are found only by a hand audit.
3. **Backups.** The nightly `.agosb` is encrypted, but it held every `.env`, AGOS's
   master key and the values it opens.

## Decision

1. **The owner's messages are masked with Hermes's own masking before anything keeps them.**
   One file, `hermes_plugin/agos_guard/keys.py`, runs only inside Hermes's runtime and
   calls `agent.redact.redact_sensitive_text(force=True)` (Hermes's default URL
   handling: a link the owner pastes for the agent keeps its query). No AGOS pattern list:
   a key is whatever Hermes's masking changes. One thing Hermes masks is put back: a
   phone number is not a key, and the owner gives the agents numbers on purpose.
   - **Web chat** (`actions/chat.py` send, room lines, edits): through
     `engine/owner_keys.py`, a helper process in Hermes's runtime (`keys.py serve`),
     before agos.db or Hermes's queue gets the text.
   - **Telegram** (the agos-guard plugin, inside the gateway):
     `bridge.pre_gateway_dispatch` answers Hermes's `{"action": "rewrite", "text": …}`,
     which replaces the message before Hermes keeps, dispatches or hands it to AGOS.
     Only the first rewrite/allow answer counts, so it is that hook's own answer.
   - When something was hidden, the agent gets a note after the owner's words: "[AGOS hid a
     key in this message. Keys go in Settings → Keys, never in chat.]" so it tells
     the owner (in their language). A Hermes `/command` is masked without the note: its
     arguments are Hermes's to parse.
   - Hermes's masking can't answer (no runtime): the message goes on **unchanged**
     and one warning is logged. The owner's message is never blocked or lost over the check;
     the Secrets check finds such a key later.
2. **A Secrets check the owner runs** (Settings → Health → "Check now"; no schedule,
   the owner's choice), `actions/secrets_check.py`, read-only:
   - keys in chat history: every message of every root's and member's `state.db`
     (read-only) that Hermes's masking would change (`keys.py scan`, one Hermes run
     per root, ~30 s for 40k messages);
   - keys in logs: each home's `logs/*.log`, file + count;
   - wrong permissions: secret files not 600, AGOS's system and backups folders and
     each Hermes root not 700.
     Only the key's kind (the head Hermes's mask keeps, or the name it was assigned
     to) and its last 4 characters are shown, never a value. The workspace Co-Founder
     runs the same check from a chat (`agos_action secrets_check`) for **its own
     workspace only**; the owner's page shows every workspace.
3. **A backup holds no key, encrypted or not** (owner: a restore needs the keys
   re-entered by hand). `engine/backup.py` takes out, wherever they are:
   - every `.env` (the shared home's, each root's and member's: API keys and the
     Telegram bot tokens), auth.json, `.credentials.json`, `*.token`, and in a Hermes
     home every credential store Hermes's own profile export never ships
     (`hermes_cli.profiles.profile_path_is_private`: vault, mcp-tokens, Google and
     Slack tokens, pairing, browser logins, …). Hermes's list is asked in its runtime;
     when Hermes can't answer, no backup is made rather than one that may hold a key;
   - AGOS's own sealed values in the agos.db copy (the backup password, Composio
     keys, MCP tokens, the web push key, a pending pool-key card's copy): a settings
     row holding one is left out, any other cell holding one is emptied;
   - then the master key (`system/master.key`) too: nothing is left for it to open.
     Keeping the master key without its values would be a key with nothing to do;
     keeping the values would be keys. The restored AGOS makes a new master key and
     simply has these unset: each page asks again (backup password, Composio key, a
     new MCP token, push re-subscribes). That is "re-enter the keys", nothing worse.
     `manifest.json` lists what went: the files' paths and the key **names** (e.g.
     `OPENROUTER_API_KEY (workspace marketing)`), never a value. The restore
     rehearsal says "Re-enter these keys in Settings → Keys: …" from it.

## What is not covered

- **History before this ship.** Messages Hermes kept before it are not rewritten;
  the Secrets check finds them, and purging them (after the owner replaced the key) stays a
  manual step. Older backups still hold their keys and still restore as they are.
- Keys the owner writes somewhere other than a chat (a file the owner uploads, a voice note) are
  not masked; the check finds them in history only if Hermes kept them as text.
- Masking is Hermes's: a key shape its masking doesn't know is neither masked nor
  found.

## Consequences

- One more small Hermes helper process per core (like `engine/hermes_redact.py`'s).
- A restore from a new backup means setting up keys and bot tokens again by hand.
- `agos update`'s rollback snapshots hold the Hermes roots' `.env` files (a rollback
  must put the keys back as they were). They live in AGOS's own data folder
  (`agos-data/system/update-snapshots/`, 0700) and never in the backup folder, and
  the backup leaves that folder out (`engine/backup.py` `SKIP_DIRS`), so the backup
  folder and every backup still hold no key.
- Hermes names AGOS now relies on are pinned in `engine/hermes_contract.py`
  (`redact_sensitive_text`, its mask shape, the `rewrite` action,
  `profile_path_is_private`).
