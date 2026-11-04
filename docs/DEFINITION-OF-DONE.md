# Definition of Done

A change is done when every line below holds, or the PR says in one sentence why a
line does not apply. The PR template repeats this list as checkboxes; CI enforces the
lines marked **(CI)**. The CI gate itself is described in [CI.md](CI.md).

## 1. It works, and a test proves it

- **Tests for the new behaviour.** Core: `services/core/tests/test_<area>.py`. Web:
  the node tests in `apps/web/scripts/*.test.mjs` for logic. **(CI)** runs them;
  at least 80% of the changed lines in `services/core/src` must run under the tests
  (diff coverage).
- **A fix starts with a failing test.** Write the test first, watch it fail on the old
  code (`git stash push -- services/core/src`, run it, `git stash pop`), then fix.
  Name the test in the PR. Of the fix commits in October 2026, one in five changed no
  test; that is the gap this line closes.
- **No test sleeps to wait.** Poll a condition with a timeout instead; patch the clock
  instead of reading the wall clock.

## 2. It works with the real Hermes

GitHub's runners have no Hermes Agent install, so CI runs only the tests that need
none (`pytest -m "not hermes"`). When the change touches the Hermes boundary
(`engine/hermes*.py`, `actions/hermes_*.py`, `api/hermes_bridge.py`,
`hermes_plugin/`, a Hermes config write, a migration Hermes reads):

- run the real-Hermes tests locally: `cd services/core && uv run pytest -m hermes -p no:xdist`
  (and the files of your area that skip themselves without Hermes);
- run the e2e rig when the gateway, the agos_guard plugin or a Hermes write changed:
  `uv run python tests/e2e/rooms_e2e.py all`;
- a new test file that needs a real Hermes goes into `HERMES_FILES` in
  `tests/conftest.py`, or skips itself when Hermes is missing. **(CI)** fails otherwise,
  because the file then runs on GitHub without Hermes.

The nightly self-hosted job runs all of this every night once its runner is registered.

## 3. It keeps the structure

- **No new layer break** (`api -> actions -> engine|hermes_gateway -> db|storage|security -> domain`,
  core never imports `hermes_plugin`). **(CI)** `lint-imports` and
  `scripts/layer_ratchet.py`.
- **No file over 800 lines**, and the files already over it do not grow. Split by
  moving code into a new module. **(CI)** `scripts/ci/file_size.py`.
- A baseline that shrank is updated in the same PR (the gate says which command).
- **Migrations are replay-safe**: `tests/test_old_copies.py` replays the last one;
  `tests/test_migrations_frozen.py` keeps shipped ones unchanged. **(CI)**
- **Co-Founder parity**: anything the owner can do in the web, the Co-Founder can do
  from a chat (owner rule 2026-10-28). A new web server action needs a Co-Founder
  action or tool, a read, or an owner-only reason in `engine/cofounder_parity/`.
  **(CI)** `tests/test_cofounder_parity.py`.

## 4. The contract and the build hold

- API changed: regenerate `services/core/openapi.json`
  (`uv run python scripts/export_openapi.py`) and `apps/web/src/data/core-api.d.ts`
  (`pnpm --filter @agos/web gen:api`). **(CI)** both drift checks.
- No route or field disappears or changes type under the web. An intended break is
  labelled `api-breaking` and changes the web in the same PR. **(CI)** oasdiff.
- `pnpm --filter @agos/web build` passes when the web changed. **(CI)** `next build`.

## 5. It is safe

- No keys, tokens or personal data in code, tests, logs or screenshots. **(CI)** gitleaks.
- No `shell=True`, no SQL built from strings, the web reaches the core only through
  `apps/web/src/server`. **(CI)** Semgrep (new findings only).
- New dependencies are pinned in the lockfiles and pass `pip-audit` / `pnpm audit`.
  **(CI)**

## 6. People can find it

- `CHANGELOG.md`: one line under `## [Unreleased]`, in plain words (what the user sees).
  **(CI)** for PRs that change `apps/*/src`, `packages/*/src` or `services/*/src`;
  label `skip-changelog` when no user sees a change (refactor, tests, CI).
- Docs updated when behaviour changed (README, `docs/`, `ARCHITECTURE.md`, an ADR in
  `docs/adr/` for a design decision).
- Checked by hand: what you clicked, with screenshots when it shows on screen.
