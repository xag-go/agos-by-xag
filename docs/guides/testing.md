# Testing

AGOS has four layers of tests. Run the fast ones on every change and the slow
ones before a release.

| Layer                 | What it covers                                                   | Needs                     | Time         |
| --------------------- | ---------------------------------------------------------------- | ------------------------- | ------------ |
| **Checks**            | format, lint, types, web unit tests, core tests without Hermes   | Node, pnpm, uv            | minutes      |
| **Core suite**        | every core test, many of them on a real Hermes                   | Hermes, Docker            | ~1 hour      |
| **End-to-end (e2e)**  | real Hermes gateways, a fake model and a fake Telegram, together | Hermes, Docker, ~4 GB RAM | ~1 hour      |
| **Install test (VM)** | the one-line install, update, rollback, uninstall in a fresh VM  | QEMU, `/dev/kvm`          | ~1–1.5 hours |

## 1. Checks (every change)

```bash
pnpm check        # format + lint + typecheck + tests, TypeScript and Python
pnpm build        # production build of the web
python3 scripts/check-docs.py     # docs links and referenced paths
```

The same, piece by piece:

```bash
pnpm format:check                          # prettier (also formats docs/*.md)
pnpm lint                                  # eslint + ruff
pnpm typecheck                             # tsc + mypy (strict)
pnpm test --filter='!@agos/service-core'   # web and package unit tests

cd services/core
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q tests/test_<area>.py      # the files your change touches
```

## 2. What CI runs

[.github/workflows/ci.yml](../../.github/workflows/ci.yml) runs on every pull
request and every push to `main`:

- **web**: prettier, then eslint, tsc and the web tests through Turborepo;
- **core**: ruff, ruff format, mypy, and pytest **without** a real Hermes or
  Docker, in parallel: `uv run pytest -m "not hermes" -n auto --dist loadfile`
  (the files that need a real Hermes are listed in `tests/conftest.py`
  `HERMES_FILES` and get the `hermes` marker; tests that need Hermes in other
  files skip themselves);
- **hygiene**: the layer and file-size ratchets, the CHANGELOG line and
  `scripts/check-docs.py`;
- **gitleaks**: no secret in the code or the history;
- **browser**: the web build clicked and screenshotted with Playwright
  ([resilience-tests.md](resilience-tests.md)).

A new test file that needs a real Hermes must skip itself when Hermes is
missing, or go in `HERMES_FILES`. Otherwise CI turns red. Every CI gate and how
to run it locally: [docs/CI.md](../CI.md).

## 3. The guard tests

Some tests check rules, not features. They fail with a message that says what
to do. The ones you will meet most:

| Test                                       | Fails when                                                                     |
| ------------------------------------------ | ------------------------------------------------------------------------------ |
| `test_contract.py`                         | `openapi.json` is stale (re-export it, then `pnpm --filter @agos/web gen:api`) |
| `test_migrations_frozen.py`                | a shipped migration changed                                                    |
| `test_old_copies.py`                       | the newest migration can't run twice                                           |
| `test_ownership.py`                        | a table, column or setting is missing from `db/ownership/`                     |
| `test_hermes_writes_guard.py`              | a module writes a Hermes file it isn't allowed to                              |
| `test_hermes_contract.py`                  | AGOS uses a Hermes internal that isn't in `CONTRACT`                           |
| `test_hermes_internals_kept.py`            | a new call into a Hermes bridge module has no recorded reason                  |
| `test_cofounder_parity.py`                 | a web server action has no Co-Founder mapping                                  |
| `test_event_loop_guard.py`                 | an `async` route blocks the event loop                                         |
| `test_version_file.py`                     | `VERSION`, the README badge and the CHANGELOG disagree                         |
| `apps/web/scripts/no-login.test.mjs`       | the web brings back a login                                                    |
| `apps/web/scripts/unused-exports.test.mjs` | the web exports a function nobody uses                                         |

## 4. The whole core suite (with Hermes)

```bash
cd services/core
uv run pytest -q
```

Many tests start a real Hermes Agent, and some a Docker sandbox. Install Hermes
at the pinned commit (`deploy/hermes.pin`) and Docker first. The live tests
(`tests/test_*_live.py`) run only when you ask for them:

```bash
AGOS_LIVE_IDENTITY=1 AGOS_LIVE_AUTOMATIONS=1 AGOS_LIVE_CONNECTORS=1 AGOS_LIVE_NETWORK=1 \
  uv run pytest -q tests/test_*_live.py
```

They make throwaway workspaces and remove them at the end.

## 5. End-to-end

`services/core/tests/e2e/rooms_e2e.py` starts real Hermes gateways in throwaway
roots, with a fake model (`fake_llm.py`) and a fake Telegram Bot API
(`fake_bot_api.py`), and drives AGOS through them: chats, rooms, approvals,
Telegram, restarts.

```bash
cd services/core
export AGOS_E2E=$(mktemp -d)                 # everything lives here
export AGOS_E2E_PORTS=18766,18991,18993      # core, fake model, fake Telegram
env -u PYTHONPATH .venv/bin/python tests/e2e/rooms_e2e.py all
env -u PYTHONPATH .venv/bin/python tests/e2e/rooms_e2e.py down
```

Steps: `up`, `setup`, `run`, `down`, or `all`. `AGOS_E2E_HERMES` and
`AGOS_E2E_RUNTIME` point it at another Hermes (used to test a Hermes upgrade,
see [hermes-upgrade.md](../hermes-upgrade.md)). It needs about 4 GB of free
memory: don't run two at once on a small machine.

Browser clicks and screenshots, the load test and the failure tests (gateway
killed mid-answer, model unreachable, core restarts, disk full, database busy):
[resilience-tests.md](resilience-tests.md).

## 6. The install test (VM)

`deploy/test-install-vm.sh all` (needs QEMU and `/dev/kvm`, no root) makes a
throwaway Ubuntu 24.04 VM, publishes the current commit as a git server, runs
the one-line `curl … | bash -s -- --yes` install with a fake provider key, and
checks:

- the services run and start at boot; the web answers 200; the core's `/health`;
- zero workspaces, voice notes off, no key in the install log;
- the sandbox image and Landlock;
- `agos status/stop/start/restart/backup/logs`;
- a second install with `--remote yes` (Tailscale and its operator);
- `agos update` with a good release, with a broken one (it must roll back), and
  through the core (the Settings button's path);
- `agos uninstall --keep-data`.

Not covered (it needs real machines): the macOS wrapper (Lima, Homebrew, port
forwarding, start at login), the Windows wrapper (WSL install and restart,
systemd in WSL, localhost forwarding, the logon task), Hermes's interactive
`hermes model` step, and the Tailscale sign-in.

The VM is kept between runs (its disk is `disk.qcow2` in `AGOS_VM_DIR`, default
`~/.cache/agos-test-vm`), so a new test reuses what the installer already
downloaded:

```bash
AGOS_VM_KEEP_DISK=1 deploy/test-install-vm.sh up      # boot the same VM (SSH on 127.0.0.1:2232)
ssh -i ~/.cache/agos-test-vm/key -p 2232 -N -L 3300:127.0.0.1:3000 tester@127.0.0.1
#   then open http://localhost:3300 (an SSH tunnel counts as this machine)
deploy/test-install-vm.sh ssh agos status             # any command inside the VM
deploy/test-install-vm.sh publish && deploy/test-install-vm.sh ssh agos update --yes   # this checkout's HEAD
AGOS_VM_KEEP_DISK=1 deploy/test-install-vm.sh install   # a fresh install after a purge
deploy/test-install-vm.sh down                        # clean shutdown; the disk stays
deploy/test-install-vm.sh delete                      # remove the VM's disk too
```

Set `AGOS_VM_DIR` the same way on every command when the VM lives elsewhere.
Never edit `deploy/test-install-vm.sh` while it runs: bash reads the file as it
goes.

## 7. Before a release

1. Start the VM install test first (it takes longest).
2. Meanwhile: the whole core suite, the e2e, `pnpm check`, `pnpm build`,
   gitleaks, and `scripts/publish-public.sh` into a temporary folder (it checks
   the export for secrets and personal words).
3. A real-Hermes test that times out while the VM runs is usually the machine
   being busy: rerun it alone before calling it a failure.
