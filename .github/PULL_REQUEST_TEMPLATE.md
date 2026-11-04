## What this changes

<!-- One or two sentences, in plain words. Link the issue or discussion if there is one. -->

## How I checked it

<!-- The commands you ran and what you looked at. -->

## Definition of Done

<!-- docs/DEFINITION-OF-DONE.md and CONTRIBUTING.md#definition-of-done explain each line. Tick it, or write why it does not apply. -->

- [ ] `pnpm check` passes (format, lint, typecheck, tests) and `pnpm --filter @agos/web build` when the web changed
- [ ] I tested the change by hand (screenshots below if it is visible on screen)
- [ ] Tests added or changed for the new behaviour; **a fix starts with a test that failed before the fix** (name it: `tests/...::test_...`)
- [ ] Real-Hermes files run locally when the Hermes boundary changed (`uv run pytest -m hermes -p no:xdist`); e2e (`tests/e2e/rooms_e2e.py all`) when the gateway, the agos_guard plugin or a Hermes write changed
- [ ] A new test file that needs a real Hermes is in `tests/conftest.py` `HERMES_FILES` (or skips itself without Hermes)
- [ ] Data lives in Hermes where Hermes has a place; anything new in AGOS is in `db/ownership/`
- [ ] Migrations are replay-safe (`tests/test_old_copies.py`, `tests/test_migrations_frozen.py`)
- [ ] API change: `openapi.json` and `core-api.d.ts` regenerated; a breaking change is intended and labelled `api-breaking`
- [ ] Co-Founder parity: a new owner action in the web has a Co-Founder action/tool or a listed owner-only reason (`cofounder_parity.DO` / `READS` / `OWNER_ONLY`, `tests/test_cofounder_parity.py`)
- [ ] No new layer break, no file over 800 lines (`services/core/scripts/layer_ratchet.py`, `scripts/ci/file_size.py`); a baseline that shrank is updated
- [ ] Docs updated if behaviour changed (README, user guide, docs/, ARCHITECTURE.md); `python3 scripts/check-docs.py` passes
- [ ] `CHANGELOG.md` has a line under `## [Unreleased]`, or the PR is labelled `skip-changelog`
- [ ] No keys, tokens or personal data in the code, tests or screenshots

## Screenshots

<!-- Optional. -->
