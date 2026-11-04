# Contributing to AGOS

Thank you for helping. This page explains how to set up AGOS for development,
how a change goes from a branch to `main`, and what "done" means.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ideas and questions

Use [GitHub Discussions](https://github.com/xag-go/agos-by-xag/discussions).
Say what you want to do and why. A short example helps more than a long spec.

## Bugs

Open an [issue](https://github.com/xag-go/agos-by-xag/issues/new/choose) with
the **Bug report** form. Include:

- the output of `agos version` and your system;
- the steps that show the problem;
- a screenshot when it is visible on screen;
- the last lines of the log (`agos logs core`), with keys, tokens and personal
  data removed;
- the error code if a message showed one ([docs/errors.md](docs/errors.md)), and
  the diagnostics (Settings → Errors → Copy diagnostics).

What happens next, and what the labels mean: [docs/triage.md](docs/triage.md).

Security problems are different: never open a public issue for them. See
[SECURITY.md](SECURITY.md).

## Development setup

The full walk-through is [docs/guides/getting-started.md](docs/guides/getting-started.md).
In short:

- Node.js 24 LTS and pnpm 10 (`corepack enable`);
- [uv](https://docs.astral.sh/uv/) for the Python core (Python 3.11 or newer;
  CI uses 3.14);
- optional, for real agents: Hermes Agent at the pinned commit
  (`deploy/hermes.pin`) and Docker, with `AGOS_ENGINE=hermes`. Without them,
  leave `AGOS_ENGINE` empty: the app runs on its own data only, which is
  enough for most web and core work.

```bash
pnpm install                       # TypeScript dependencies
(cd services/core && uv sync)      # Python dependencies

# terminal 1: the core on 127.0.0.1:8766
cd services/core
AGOS_DATA_DIR="$PWD/../../agos-data" AGOS_ENGINE= \
  uv run uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port 8766

# terminal 2: the web on http://127.0.0.1:3001
cd apps/web
AGOS_DATA_DIR="$PWD/../../agos-data" pnpm exec next dev -H 127.0.0.1 -p 3001
```

[.env.example](.env.example) lists every variable. On a Mac,
`scripts/dev-up.sh` starts both under launchd.

## Before you write code

1. Read [ARCHITECTURE.md](ARCHITECTURE.md). Section 10 is the target design
   (the service layer) every change moves toward.
2. Read [docs/hermes-ownership.md](docs/hermes-ownership.md). Hermes Agent is
   the engine of everything; AGOS stores only what Hermes has no place for.
3. Follow [docs/guides/how-to-add-a-feature.md](docs/guides/how-to-add-a-feature.md)
   step by step.
4. For a design change, write an ADR in [docs/adr](docs/adr/README.md) first.

## Branches and pull requests

1. Fork the repository (or, for maintainers, branch in it) from `main`.
   Name the branch after the change: `feat/<name>`, `fix/<name>`,
   `docs/<name>`, `refactor/<name>`.
2. Keep one change per pull request. Big changes go in a series of small pull
   requests, each with green tests.
3. Fill in the pull request template: what changes, how you checked it, and
   screenshots when it is visible.
4. CI must be green ([.github/workflows/ci.yml](.github/workflows/ci.yml)).
5. A maintainer reviews every pull request before it is merged. Expect
   questions about the rules in ARCHITECTURE.md and the decisions in
   [docs/adr](docs/adr/README.md).
6. After approval, a maintainer merges it into `main`.

By sending a pull request you agree that your contribution is licensed under
the [MIT license](LICENSE).

## Definition of Done

A change is done when:

- [ ] it does what its description says, checked by hand in the browser;
- [ ] data lives in Hermes where Hermes has a place for it; anything new in
      AGOS is registered in `db/ownership/` with a reason;
- [ ] the Co-Founder can do it too (or `cofounder_parity.OWNER_ONLY` says why not),
      with Undo or Approve;
- [ ] it adds no layer violation and no file over 800 lines (the ratchets,
      [docs/CI.md](docs/CI.md));
- [ ] it has tests; a bug fix has a test that failed before the fix;
- [ ] `pnpm check` passes, and the Hermes-dependent tests you touched pass
      locally;
- [ ] `openapi.json` and the web's generated types are up to date;
- [ ] CHANGELOG.md (Unreleased), the user guide and ARCHITECTURE.md are
      updated where needed, and `python3 scripts/check-docs.py` passes;
- [ ] no keys, tokens or personal data in code, tests, docs or screenshots.

The long version, with the why of each item, is in
[docs/DEFINITION-OF-DONE.md](docs/DEFINITION-OF-DONE.md) and
[docs/guides/how-to-add-a-feature.md](docs/guides/how-to-add-a-feature.md#8-definition-of-done).

## Tests

```bash
pnpm check                         # format + lint + typecheck + tests, TypeScript and Python
pnpm build                         # production build of the web
python3 scripts/check-docs.py      # docs: relative links and referenced paths
```

Many core tests start a real Hermes Agent (and some a Docker sandbox). CI runs
the part that needs neither, in parallel:
`uv run pytest -m "not hermes" -n auto --dist loadfile`. The files that need a
real Hermes are listed in `tests/conftest.py` (`HERMES_FILES`). What runs where,
the guard tests, the e2e and the install test in a VM:
[docs/guides/testing.md](docs/guides/testing.md). Every CI gate and how to run
it locally: [docs/CI.md](docs/CI.md).

## Commit style

- Write commit messages in English, in plain words.
- Use a short type prefix: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
  `chore:`, `ci:`. Add a scope when it helps: `fix(kanban): …`.
- The first line says what changes, in under 72 characters. The body (when
  needed) says why.
- One logical change per commit. Don't mix a refactor with a behaviour change.

## Style

- Code, comments, docs and commit messages in English, in plain words and
  short sentences.
- Python: ruff and mypy `--strict`. TypeScript: strict, eslint, prettier.
  Markdown is formatted by prettier too.
- Never commit keys, tokens, real personal data or a `.env` file. CI runs
  [gitleaks](https://github.com/gitleaks/gitleaks) on every push.

## Releases

Versions follow SemVer from 0.x; a release is a signed `vX.Y.Z` tag cut with
`scripts/release.py prepare X.Y.Z`, published by pushing the tag (the Release
workflow builds, signs and publishes it). The whole process, the channels
(stable, beta, main) and how installs check a release:
[docs/releases.md](docs/releases.md). The release number lives in [VERSION](VERSION);
`tests/test_version_file.py` checks it agrees with the README badge and
[CHANGELOG.md](CHANGELOG.md).
