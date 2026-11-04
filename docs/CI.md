# CI gate

Three workflows in `.github/workflows/`:

| Workflow             | When                              | Runs on                     |
| -------------------- | --------------------------------- | --------------------------- |
| `ci.yml`             | every PR, push to `main`          | GitHub (`ubuntu-24.04`)     |
| `security.yml`       | every PR, push to `main`, Mondays | GitHub (`ubuntu-24.04`)     |
| `nightly-hermes.yml` | nightly 02:23 UTC, by hand        | self-hosted runner `hermes` |

All jobs of a workflow run in parallel. Every action is pinned by commit SHA (the tag
is in the comment); Dependabot moves the pins. Every downloaded binary is checked
against its sha256.

## What each gate checks

| Job (workflow)                      | Fails when                                                                                                                                                                                                                                                                                                            |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web` (ci)                          | prettier, eslint, `tsc` or the web node tests fail; `core-api.d.ts` differs from what `gen:api` makes of the committed `openapi.json`; a web function is new over, or worse on, the complexity / length limits (`complexity.py --part web`); a web file has more jsx-a11y findings than its baseline (`a11y_lint.py`) |
| `web-build` (ci)                    | `next build` fails (it refuses server/client boundary and route-export mistakes that tsc and eslint pass)                                                                                                                                                                                                             |
| `web-budgets` (ci)                  | a page's first-load JavaScript (gzipped) is more than 20% over `scripts/ci/web-budget-baseline.json` (`scripts/ci/web_budgets.py`)                                                                                                                                                                                    |
| `core-static` (ci)                  | ruff, ruff format, mypy (strict) fail; `lint-imports` finds a broken contract; `.importlinter` is stale; `layer_ratchet.py` counts a new break; a core function is new over, or worse on, C901 / PLR0912 / PLR0915 / 80 lines (`complexity.py --part python`)                                                         |
| `core-tests` (ci)                   | a test fails or runs over 120 s (`pytest -m "not hermes" -n auto --dist loadfile`); on PRs, under 80% of the changed `src` lines are covered                                                                                                                                                                          |
| `contract` (ci)                     | `openapi.json` differs from the code; on PRs, oasdiff finds a breaking change against the base (unless labelled `api-breaking`)                                                                                                                                                                                       |
| `hygiene` (ci)                      | a file over 800 lines is new or grew; `scripts/check-docs.py` finds a broken doc link or path; a PR changes product code without a CHANGELOG `Unreleased` line (unless `skip-changelog`); shellcheck warns                                                                                                            |
| licences (ci: `web`, `core-static`) | a Node or Python dependency's licence is not one an MIT project can ship with (GPL/AGPL, SSPL/BUSL/FSL, unknown) and is not a reviewed exception in `scripts/ci/licenses-allowed.json` (`scripts/ci/licenses.py`)                                                                                                     |
| `workflows` (ci)                    | actionlint or zizmor (unpinned action, template injection, credentials left in the checkout, …) finds a problem                                                                                                                                                                                                       |
| `audit-python` (security)           | `pip-audit` finds a known vulnerability in any package of `uv.lock` (runtime and dev)                                                                                                                                                                                                                                 |
| `audit-node` (security)             | `pnpm audit --prod` finds a high or critical advisory                                                                                                                                                                                                                                                                 |
| `semgrep` (security)                | a NEW finding of `p/python`, `p/typescript`, `p/secrets` or `.semgrep/agos.yml` versus the base commit (Mondays: full report, never fails)                                                                                                                                                                            |
| `gitleaks` (security)               | a secret in the files or in the new commits (known test fakes: `.gitleaksignore`)                                                                                                                                                                                                                                     |

Labels the gate reads (create them once in the repository's Labels page):
`skip-changelog`, `api-breaking`, `coverage-exempt`, `dependencies`.

### The AGOS Semgrep rules (`.semgrep/agos.yml`)

- `agos-no-shell-true`: `subprocess.*(shell=True)`, `create_subprocess_shell`,
  `os.system`, `os.popen`.
- `agos-no-fstring-sql`: `execute*()` with an f-string, `%`, `.format()` or `+` in
  `services/core/src`. 68 findings exist today (constant table names); only new ones
  fail.
- `agos-web-core-only-through-server`: `AGOS_CORE_URL` / `AGOS_INTERNAL_TOKEN_FILE`
  read outside `apps/web/src/server`. 14 today (the streaming route handlers under
  `app/api/` and `app/preview/`); they should move behind a helper in `src/server`.

## Ratchets: today's debt may only shrink

| Gate                | Baseline file                                  | Today                                                                                                                            | After removing debt                                                     |
| ------------------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Layer rules         | `services/core/layer-baseline.json`            | layers 3, api-only-via-actions 23, core-not-plugin 0, plugin-standalone 0, domain-pure 0, shared-pure 0 (statements)             | `uv run python scripts/layer_ratchet.py --update`                       |
| import-linter       | `services/core/.importlinter` (ignore_imports) | 19 + 69 + 8 ignored module pairs                                                                                                 | `uv run python scripts/importlinter_ignores.py`                         |
| File size           | `scripts/ci/file-size-baseline.json`           | 13 files over 800 lines (all py)                                                                                                 | `python3 scripts/ci/file_size.py --update`                              |
| Function complexity | `scripts/ci/complexity-baseline.json`          | core: 120 functions (C901 > 10: 110, PLR0912 > 12: 46, PLR0915 > 50: 13, > 80 lines: 36); web: 243 (complexity > 10, > 80 lines) | `python3 scripts/ci/complexity.py --update` (records only improvements) |
| Semgrep             | the base commit (baseline mode)                | 6 pack findings, 68 + 14 AGOS-rule findings                                                                                      | nothing to update                                                       |
| Web bundle sizes    | `scripts/ci/web-budget-baseline.json`          | each page's first-load JS, gzipped (kB); more than 20% heavier fails                                                             | `python3 scripts/ci/web_budgets.py --update` (records only lighter)     |
| Core speed and RAM  | `services/core/tests/perf/baseline.json`       | core start, the main pages' reads (p50 ms), RSS after warm-up; nightly, more than 20% worse fails                                | `uv run python tests/perf/budgets.py --update` (records only better)    |

The function-complexity ratchet (`scripts/ci/complexity.py`) measures every function of
`services/core/src` with ruff (`C901` cyclomatic complexity over 10, `PLR0912` branches
over 12, `PLR0915` statements over 50) and its length (over 80 lines, `def` to its end),
and every function of `apps/web/src` with ESLint (`complexity` over 10,
`max-lines-per-function` over 80 without blank and comment lines;
`apps/web/eslint.complexity.mjs`, syntax only). A function is keyed by its file and
qualified name (`#2` for a second one of the same name, an unnamed web callback is
`(anonymous)`): a new function over a limit fails, a baselined one may not get worse, and
one that got simpler or went away must be recorded with `--update`, which refuses while
anything is new or worse.

Both layer tools count imports inside functions too (65% of the core's internal
imports are lazy). `lint-imports` follows indirect chains; `layer_ratchet.py` counts
every statement, so a second lazy import along an already-ignored pair still fails.
The gate also fails when debt went away and the baseline was not lowered, so a fixed
break can never come back unseen. `db/migrations.py` is append-only by design: it is
listed in the file-size baseline but may grow.

The contracts (`scripts/layer_ratchet.py`, mirrored into `.importlinter`):

- `layers`: `api -> actions -> engine | hermes_gateway -> db | storage | security -> domain`,
  never upward (`hermes_gateway`, ADR 0024, shares the engine's layer).
- `api-only-via-actions`: the api reaches engine/hermes_gateway/db/storage/security only through
  actions (`db.records` view models are allowed until they move to a schemas package).
- `core-not-plugin`: nothing in the core imports `hermes_plugin` (it runs inside Hermes).
- `plugin-standalone`: `hermes_plugin` imports no core package.
- `domain-pure`: `domain` imports nothing else from `agos_core`.

## Real-Hermes tests: the `hermes` marker

`tests/conftest.py` `HERMES_FILES` lists the test files that read the installed Hermes
Agent's own source or run the real `hermes` without skipping when it is missing; every
test in them gets the `hermes` marker. CI deselects them (`-m "not hermes"`, 138 tests
today); other Hermes tests skip themselves (122 skips in the CI set today, shown in the
job summary). `tests/test_ci_gates.py` fails when the list names a file that is gone.

```sh
cd services/core
uv run pytest -m "not hermes" -n auto --dist loadfile   # what CI runs (~2 min on 8 workers)
uv run pytest -m hermes -p no:xdist                     # the real-Hermes files, serial
uv run pytest -p no:xdist                               # everything, as the nightly job does
```

The real-Hermes tests must stay serial: they share `~/.hermes` (install locks) and fixed
roots such as `~/.cache/agos-wall-test`. `pytest-timeout` stops any test after 600 s
(`pyproject.toml`); CI passes `--timeout=120`.

## Run the gate locally

```sh
pnpm format:check && pnpm exec turbo run lint typecheck test --filter='!@agos/service-core'
pnpm --filter @agos/web build
cd services/core
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run lint-imports && uv run python scripts/layer_ratchet.py
uv run pytest -m "not hermes" -n auto --dist loadfile --cov=agos_core --cov-report=xml
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=80
cd ../.. && python3 scripts/ci/file_size.py && python3 scripts/ci/changelog_check.py origin/main
actionlint && uvx zizmor .github/workflows
```

`pre-commit install` (config: `.pre-commit-config.yaml`) runs ruff, prettier, gitleaks,
the file-size and layer ratchets on each commit.

## Nightly self-hosted runner

`nightly-hermes.yml` runs, on a self-hosted runner labelled `hermes` (stages chosen by
hand with Run workflow → `stage`):

1. the whole core suite against a real Hermes (serial);
2. the e2e rig (`tests/e2e/rooms_e2e.py all`, its own ports 28766/28991/28993);
3. the migrations on old databases (`scripts/migration_rehearsal.py`, below);
4. the agent evals (`tests/evals/run.py`, below);
5. the core's speed and RAM budgets (`tests/perf/budgets.py`, below).

Its reports (`nightly-*.json`) are kept 30 days as the `nightly-reports` artifact. It
is off until a runner is registered:

1. With the owner's OK, on the machine that has Hermes:
   `deploy/register-ci-runner.sh --dry-run` shows every step; then
   `deploy/register-ci-runner.sh --repo OWNER/NAME` (a registration token comes from
   your `gh` login, or `--token-file`; it never goes on a command line). It makes a
   dedicated low-privilege account (`agos-ci`: no sudo, its own 0700 home, so a job
   reads neither your keys nor the live AGOS), installs that account's own Hermes
   (pinned to `deploy/hermes.pin`) and uv, the runner (pinned version, sha256 checked,
   labels self-hosted / linux / hermes) and a systemd user service of that account:
   nice 19, idle IO, `MemoryHigh=7G` / `MemoryMax=9G`, OOM-killed first, so a squeeze
   never takes the live gateways. A clean-up hook runs before and after every job and
   when the service stops: it ends the rigs' processes and removes the rigs and the
   job's temp files, nothing else. A systemd user unit can't hide files from its own
   uid on this kernel (unprivileged user namespaces are refused, so `ProtectHome` /
   `InaccessiblePaths` are silently ignored): the separate account is the boundary.
2. One runner = one job at a time, which the real-Hermes tests need (the workflow's
   concurrency group says the same).
3. Set the repository variable `HERMES_RUNNER` to `on`
   (`gh variable set HERMES_RUNNER --body on`). Until then the job is skipped, never
   queued.
4. Start it once by hand (`gh workflow run nightly-hermes.yml -f stage=hermes-tests`).
5. `deploy/register-ci-runner.sh --remove` stops and unregisters it (the account stays;
   the script prints the `userdel`).

The workflow keeps pytest's temp dirs and the evals / budgets rigs under
`~/.hermes/cache/scratch/` (on disk and inside `~/.hermes`): outside it, each throwaway
Hermes home syncs its own Python environment for minutes. It never runs on
`pull_request`: a self-hosted runner must not run code from a fork
(`services/core/tests/test_ci_runner.py` checks that no other workflow reaches a
self-hosted runner).

### Agent evals

`services/core/tests/evals/run.py` brings up one throwaway workspace on real Hermes
(`tests/evals/one_workspace_rig.py`, built on the e2e rig) with a scripted model
(`tests/evals/eval_llm.py`: `tests/e2e/fake_llm.py` plus the eval turns, so the
results are deterministic), runs each scenario and scores it (each check one point):

| Scenario                       | Checks                                                                                                                                         |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| cofounder label from chat      | the Co-Founder's `agos_action` makes the label from his chat message, no question (a work action), its card is done, Undo takes it back        |
| cofounder skill from chat      | a power action in a turn that read nothing from outside is done at once                                                                        |
| card review flow               | a card with the owner as review stage: its worker hands it in, changes send it back, round 2, approve, done, the marker trail on Hermes's card |
| tainted turn asks before power | after a `curl` in the same turn the same power action waits on an Allow / Deny card that says why; nothing is made, before or after Deny       |

```sh
cd services/core
uv run python tests/evals/run.py                      # ~10 min (a new workspace's Hermes root)
uv run python tests/evals/run.py --keep               # leave the rig up, then:
uv run python tests/evals/run.py --reuse --only "card review flow"
```

It writes `evals-report.json` (the score per scenario and check: the trend) and, with
`--summary`, a Markdown table; it exits 1 under `--min-score` (default 1.0: the scripted
model leaves no room for luck) or over `--budget-tokens`. The scoring and the scripted
turns have their own fast tests (`tests/evals/test_evals_scoring.py`, in `core-tests`).

### Migrations on old databases

`services/core/scripts/migration_rehearsal.py` takes a copy of an `agos.db` (`--db`, or
the newest copy under `~/agos-roots-test`; never a live AGOS's data folder, which it
refuses), or else rebuilds old versions from git history (db/migrations.py as each
commit of the main line had it, given rows in every table), runs every migration
forward and checks: integrity_check, foreign_key_check, no table loses rows (unless a
migration deletes from it or a table it hangs on by name, or drops it), the same
shape as a fresh database, and that a restart or replaying the last migration
changes nothing.

```sh
cd services/core
uv run python scripts/migration_rehearsal.py --git all           # every old version (~40 s)
uv run python scripts/migration_rehearsal.py --db ~/restored/agos.db
uv run python scripts/migration_rehearsal.py --git all --side-branches   # also renumbered branch copies (a report)
```

`tests/test_migration_rehearsal.py` runs it on every 10th version in `core-tests`.

### Speed and RAM budgets

`scripts/ci/budget_ratchet.py` compares measured numbers with a baseline: more than
20% worse fails (unless the change is under the unit's noise floor: 10 ms, 0.25 s,
10 MB, 1 kB), a lost measurement fails, `--update` records better numbers only.

- `scripts/ci/web_budgets.py` (job `web-budgets`, every PR): each page's first-load
  JavaScript after `next build`, gzipped, from the build's client reference manifests.
- `services/core/tests/perf/budgets.py` (nightly): on a one-workspace rig with real
  Hermes, a board and a chat to read: the core's start (to its first answer, median of
  3), the reads behind the overview, board, chats, one chat, settings and Hermes
  settings and the workspace list (p50 of 15 warm calls), the core's RSS after them.
  Its baseline (`tests/perf/baseline.json`) was measured on the runner's machine: run
  it there, not on GitHub's runners.

## Dependency updates

`.github/dependabot.yml` opens grouped weekly PRs (Mondays) for `uv`
(`services/core`), npm (the pnpm workspace) and GitHub Actions, labelled
`dependencies` + `skip-changelog`. `services/core/pyproject.toml` pins
`[tool.uv] exclude-newer`: a Python update newer than that date fails `uv sync --frozen`
until the PR moves the date (and runs `uv lock`). npm updates wait 3 days
(`cooldown`), like `minimumReleaseAge` in `pnpm-workspace.yaml`.

## Branch protection

The gate only blocks a merge once branch protection makes it required. On the current
GitHub plan the protection API answers 403 for this private repository. The public
repository gets it for free: `scripts/public-repo-settings.sh --apply` requires every
job of `ci.yml` and `security.yml` on `main` there (docs/releases.md, "The public
repository's settings").
