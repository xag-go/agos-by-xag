# Getting started (developers)

This page takes you from a fresh clone to a running AGOS you can change. It
takes about 15 minutes.

## 1. What you need

| Tool                               | Why                                                         |
| ---------------------------------- | ----------------------------------------------------------- |
| Git                                | the code                                                    |
| Node.js 24 LTS and pnpm 10         | the web app and the monorepo checks (`corepack enable`)     |
| [uv](https://docs.astral.sh/uv/)   | the Python core (it installs Python 3.11+ for you)          |
| Hermes Agent and Docker (optional) | real agents. Without them the app runs on its own data only |

Most web and core work needs neither Hermes nor Docker. Leave `AGOS_ENGINE`
empty and the core runs without an engine: screens, data and rules all work,
agents don't answer.

## 2. Get the code and the dependencies

```bash
git clone https://github.com/xag-go/agos-by-xag.git
cd agos-by-xag
pnpm install                       # TypeScript dependencies
(cd services/core && uv sync)      # Python dependencies (.venv in services/core)
```

## 3. Run it

Use a data folder inside the repository (it is git-ignored) so you never touch
a real install. Start the core and the web in two terminals:

```bash
# Terminal 1: the Python core on 127.0.0.1:8766
cd services/core
AGOS_DATA_DIR="$PWD/../../agos-data" AGOS_ENGINE= \
  uv run uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port 8766

# Terminal 2: the web on http://127.0.0.1:3001
cd apps/web
AGOS_DATA_DIR="$PWD/../../agos-data" pnpm exec next dev -H 127.0.0.1 -p 3001
```

Open http://127.0.0.1:3001. A fresh data folder has no workspace: you see the
first-start screen.

On a Mac, `scripts/dev-up.sh` starts both under launchd (plus the webhook relay
on :8767). `scripts/dev-up.sh down` stops them.

### With real agents

Install Hermes Agent at the pinned commit (`deploy/hermes.pin`) and Docker, build
the sandbox image once (`scripts/build-sandbox.sh`), then start the core with
`AGOS_ENGINE=hermes`. Every variable is explained in [.env.example](../../.env.example).
Use a separate `AGOS_DATA_DIR` and `AGOS_PROFILE_PREFIX` so your test roots never
mix with a real install's.

## 4. Find your way around

| Path                                                    | What is there                                                |
| ------------------------------------------------------- | ------------------------------------------------------------ |
| `services/core/src/agos_core/api/`                      | FastAPI routers, one per screen                              |
| `services/core/src/agos_core/actions/`                  | the use-cases (moving to services, see the architecture §10) |
| `services/core/src/agos_core/engine/`                   | the Hermes driver, pure rules, the Hermes contract           |
| `services/core/src/agos_core/db/`                       | migrations, the ownership registry, repositories             |
| `services/core/src/agos_core/hermes_plugin/agos_guard/` | AGOS's plugin that runs inside Hermes                        |
| `services/core/tests/`                                  | the core's tests (pytest)                                    |
| `apps/web/src/features/`                                | one folder per screen: components and server actions         |
| `apps/web/src/data/`                                    | core API queries and the generated types                     |
| `deploy/`                                               | the installer, the `agos` command, the test VM               |
| `docs/`                                                 | these docs and the decision records                          |

Read next, in this order:

1. [ARCHITECTURE.md](../../ARCHITECTURE.md): how the pieces fit, and the target
   design every change moves toward.
2. [hermes-ownership.md](../hermes-ownership.md): what AGOS may store, and what
   belongs to Hermes.
3. [how-to-add-a-feature.md](how-to-add-a-feature.md): the step-by-step for a
   change.
4. [testing.md](testing.md): which tests to run, and when.

## 5. Before your first commit

```bash
pnpm check        # format, lint, typecheck and tests, TypeScript and Python
python3 scripts/check-docs.py     # when you touched docs
```

Then follow [CONTRIBUTING.md](../../CONTRIBUTING.md) for the branch and pull
request flow.

## Common problems

- **`openapi.json is out of date`**: you changed an API route. Run
  `cd services/core && uv run python scripts/export_openapi.py`, then
  `pnpm --filter @agos/web gen:api`.
- **The web can't reach the core**: the core is not running, or the web and
  the core use different `AGOS_DATA_DIR` values. The web reads the internal
  token from `<data>/system/internal.token`, which the core writes at start.
- **A core test needs Hermes**: many tests start a real Hermes. Without it they
  skip, or CI ignores them ([testing.md](testing.md)).
