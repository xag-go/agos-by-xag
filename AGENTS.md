# AGENTS.md: rules for every coding agent working on AGOS

Claude Code loads this file through `CLAUDE.md`. Codex, Gemini CLI, Hermes Agent and other agents read it
directly. It is short on purpose: the details live in the linked docs, and the docs stay the source of truth.

## Read first

1. [ARCHITECTURE.md](ARCHITECTURE.md). Section 10 is the target design (the service layer).
2. [docs/hermes-ownership.md](docs/hermes-ownership.md). Hermes Agent is the engine of everything. AGOS
   stores only what Hermes has no place for, registered in `db/ownership/` with a reason.
3. [docs/guides/how-to-add-a-feature.md](docs/guides/how-to-add-a-feature.md), step by step.
4. [CONTRIBUTING.md](CONTRIBUTING.md) (setup, branches, Definition of Done) and
   [docs/guides/testing.md](docs/guides/testing.md) (what runs where).

## Rules

- AGOS has no user accounts: no login, logout, password, account, invite or human member in code, UI or
  docs. Sign-in to outside apps (connectors, model providers, Tailscale) is fine. Safety comes from
  listening on 127.0.0.1 plus Tailscale-only access.
- Nothing personal in the repository: no names, domains, IPs, host names, server paths, keys or tokens in
  code, tests, docs or screenshots. Owner-specific settings are config with neutral defaults.
- A fresh install starts empty (no workspace, no keys). Existing installs keep their stored values.
- Tests never call a paid model or a real outside service: use the fake model (`fake_llm.py`) and the fake
  bot API (`fake_bot_api.py`).
- Test first. A bug fix starts with a test that fails on the bug.
- Ratchets only shrink ([docs/CI.md](docs/CI.md)). Never raise a baseline, add an ignore, skip a test or
  weaken CI to get green.
- Migrations only move forward. Append a new one, never edit a shipped one (`test_migrations_frozen.py`).
- After an API change, re-export `openapi.json` and run `pnpm --filter @agos/web gen:api`.
- Every change updates CHANGELOG.md (Unreleased), and the user guide and ARCHITECTURE.md where needed.
- The Co-Founder can do what the owner can (`test_cofounder_parity.py`), with Undo or Approve.

## Checks, in order

1. **Every change.** Run these before you push. The full list of CI gates and their local commands is in
   [docs/CI.md](docs/CI.md):
   ```bash
   pnpm check                        # format + lint + typecheck + tests
   pnpm --filter @agos/web build     # production web build (catches what tsc misses)
   python3 scripts/check-docs.py     # docs links and referenced paths
   cd services/core && uv run pytest -m "not hermes" -n auto --dist loadfile   # what CI runs
   ```
2. **Real Hermes (when you touched engine code).** `uv run pytest -m hermes -p no:xdist` (serial). Files
   that need Hermes are listed in `tests/conftest.py` (`HERMES_FILES`).
3. **Before a ship: the full chain.** Run it as one script, in this order, never two lanes at once (they
   run out of memory): pnpm checks, then the web production build, then the whole core suite with Hermes
   (in pieces of about 12 files, each piece wrapped in a timeout), then the end-to-end run
   (`tests/e2e/rooms_e2e.py all`, then `down`). Run the chain as a systemd user unit, not as a child of the
   agent. It ends with one exact green line that the ship step looks for. Rerun failed tests alone at the
   end: fail alone = a real failure, pass alone = order or memory problem, look before shipping.
4. **Install test (VM), before releases and installer changes.** `deploy/test-install-vm.sh all`
   ([docs/guides/testing.md](docs/guides/testing.md#6-the-install-test-vm)). Keep the VM disk
   (`AGOS_VM_KEEP_DISK=1`). Never edit the script while it runs.
5. **Slow checks** (nightly): agent evals, migration rehearsal on every old version, speed and RAM budgets
   ([docs/CI.md](docs/CI.md#nightly-self-hosted-runner)).
6. **Release.** [docs/releases.md](docs/releases.md). Run gitleaks and the export check (secrets and personal
   words) from [docs/guides/testing.md](docs/guides/testing.md#7-before-a-release).

A skipped check is "not proven", never a pass. Report the exact commands you ran and their output.

## Shipping and maintainer steps

Shipping to a live server, the public/private repository split and the ship scripts are maintainer
steps. They live outside this repository, in the maintainer's private notes, because they name machines
and paths. Read them there before any ship, and never copy them into this repository. Never ship, push to
the public repository or tag a release without the maintainer's explicit word.
