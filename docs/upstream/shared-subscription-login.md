# Proposal for Hermes: one subscription login shared by several Hermes homes

Status: draft, not yet sent to NousResearch/hermes-agent (AGOS maintainers to approve).

## Problem

A machine can run several independent Hermes homes (separate `HERMES_HOME` roots,
not profiles of one root): for example one per team or workspace, each with its
own config, memory, skills, sessions, Kanban and gateway, closed off from the
others. API keys work in every home, but a subscription login (Claude Pro/Max,
ChatGPT/Codex, xAI) does not:

- `hermes auth add <provider>` saves the login in that home's `auth.json`.
- The refresh token is single-use and rotates, so copying `auth.json` to another
  home breaks both homes on the first refresh (Hermes's docs warn about this).
- Profiles of one root can share it (the root fallback and write-through in
  `agent/credential_pool.py`), but separate roots cannot.
- Today the only workarounds are signing in once per home, or writing the
  tokens into Claude Code's `~/.claude/.credentials.json` for every home to
  borrow (`auth.adopt_external_logins`). The second one means a program outside
  Hermes moves tokens around.

Nous already solves this inside Hermes: `HERMES_SHARED_AUTH_DIR` (default
`<root>/shared/`) holds `nous_auth.json`, written on login and on every refresh,
read by every home that points at it.

## Proposal

Do the same for every single-use-refresh OAuth provider (`anthropic`,
`openai-codex`, `xai-oauth`, …):

1. A shared credential store directory, set with `HERMES_SHARED_AUTH_DIR` or
   `auth.shared_store: <path>` in `config.yaml`.
2. `hermes auth add <provider> --shared` (or a config switch) saves the new pool
   entry in the shared store instead of the home's `auth.json`.
3. Every home that points at the store reads those entries as borrowed rows,
   like the profile root fallback does, and refreshes them under the store's
   cross-process lock, writing the rotated pair back to the store (the existing
   `_update_root_pool_rows` write-through logic, keyed on the store path).
4. `hermes auth list` marks shared entries; `hermes auth remove` on one removes it
   from the store for everyone.
5. Homes without the setting behave exactly as today.

## Why it belongs in Hermes

- Hermes already owns the hard parts: the pool, the single-use refresh rules,
  the cross-process locks, the fork healing (#100339, #103694).
- It removes the need for any tool on top of Hermes to read or write tokens.
- It makes "several closed Hermes homes, one account" a supported setup instead
  of N logins or a borrowed external file.

## What we can offer

A PR with the store, the `--shared` flag, tests modelled on the Nous shared
store tests, and a docs section in `credential-pools.md`.
