# Upgrading Hermes Agent

AGOS runs on [Hermes Agent](https://github.com/NousResearch/hermes-agent) and is
tested with one exact Hermes commit:

- `deploy/hermes.pin`: the commit. The installer installs exactly this one.
- `HERMES_TESTED_VERSION` in `services/core/src/agos_core/config.py`: its version.

Hermes changes quickly, and AGOS uses some of its internals (the cron job store,
the sessions API, the approval hook, the terminal tool, the room service…). So
never run a plain `hermes update` on an AGOS machine. Use one of the two ways
below.

## The easy way: the Hermes update button

**Settings → General → Hermes update → Check Update → Do the update now.**

The button runs this page's order for you:

1. the contract check (section 0) on the target release, read-only;
2. backups of every Hermes root;
3. every workspace gateway stopped;
4. `hermes update` pinned to the checked release;
5. every Hermes home prepared (dependencies, the memory plugin);
6. the gateways started again.

If anything fails before a gateway ran the new code, the Hermes code is rolled
back by itself. The code is `engine/hermes_update.py` (the check) and
`actions/hermes_update.py` (the run).

The rest of this page is the manual procedure. It is also the reference for what
the button does.

## 0. First, always: does AGOS still fit the target Hermes?

Every Hermes internal AGOS uses is listed in
`services/core/src/agos_core/engine/hermes_contract.py` (`CONTRACT`; the entries
live by area in `engine/contract/uses_*.py`), with what of AGOS breaks without it. A release can change one of them without any AGOS test
noticing. So check the target first:

```bash
scripts/hermes-upgrade-check.sh <tag-or-sha>      # HERMES_FETCH=1 fetches first
```

The script checks the target out into a **temporary** git worktree of the
installed `~/.hermes/hermes-agent` (or `$HERMES_AGENT_SRC`, or a second argument),
runs the checker on it, prints the report and removes the worktree. The checker
reads the source with `ast`: nothing of Hermes is imported or run. The installed
Hermes is never switched. For a checkout you already have:
`cd services/core && .venv/bin/python -m agos_core.engine.hermes_contract /path/to/hermes-agent`.

- **exit 0**, `N entries: N ok, 0 broken`: go on with section 1.
- **exit 1**, `FAIL …` lines (each says what changed and which AGOS feature
  breaks): **stop**. Change AGOS for the new Hermes first (and its entry in
  `CONTRACT`), then run the check again. Never upgrade a running AGOS over a FAIL.
- **exit 2**: not a Hermes checkout, or no such tag or sha.

`tests/test_hermes_contract.py` runs the same check against the Hermes installed on
the test machine. It also fails when AGOS's code uses a Hermes name (an import, a
helper script's import, a `_private` attribute) that is not in `CONTRACT`.

If a break still reaches a running AGOS (an internal that only fails at run time),
AGOS fails closed and says so: an ERROR `Hermes contract broken: <name>` in the
workspace Log, and the same message in the Co-Founder's chat and on the owner's
phone, once per name per gateway start.

What to watch in a Hermes changelog: `cron/jobs.py`, the sessions and runs API,
`agent/account_usage.py`, `tools/approval.py`, `terminal.docker_*` config keys,
profile commands, the hosted room service, and the plugin hook list.

## 1. Test the target first (never on a machine people use)

Make a separate checkout of the release with its own environment. The installed
Hermes stays untouched.

```bash
git -C ~/.hermes/hermes-agent fetch origin --tags
git -C ~/.hermes/hermes-agent worktree add --detach ~/hermes-next <tag>
cp -a ~/.hermes/tools ~/hermes-next-tools                 # its own tool store
PY=$(ls -d ~/hermes-next-tools/python-3.*/bin/python3 | head -1)
cd ~/hermes-next
env -u PYTHONPATH HERMES_HOME=~/hermes-next-home HERMES_RUNTIME_DIR=~/hermes-next-tools \
  "$PY" -m pm.build_env --source . --out "$PWD/.venv-full" \
  --extra all --extra anthropic --extra stt-whisper --extra telegram
```

Then run AGOS's tests against it, with throwaway data:

```bash
cd services/core
export AGOS_HERMES_BIN=~/hermes-next/hermes AGOS_DATA_DIR=$(mktemp -d)
uv run pytest -q                                   # the core suite
AGOS_LIVE_IDENTITY=1 AGOS_LIVE_AUTOMATIONS=1 AGOS_LIVE_CONNECTORS=1 AGOS_LIVE_NETWORK=1 \
  uv run pytest -q tests/test_*_live.py            # live tests: need Docker and a provider
```

The end-to-end harness takes its Hermes from `AGOS_E2E_HERMES` and its runtime
from `AGOS_E2E_RUNTIME` (see [guides/testing.md](guides/testing.md)):

```bash
export AGOS_E2E=$(mktemp -d) AGOS_E2E_HERMES=<launcher for ~/hermes-next> \
  AGOS_E2E_RUNTIME=~/hermes-next-tools
env -u PYTHONPATH .venv/bin/python tests/e2e/rooms_e2e.py all
env -u PYTHONPATH .venv/bin/python tests/e2e/rooms_e2e.py down
```

Only go on when everything passes. If something fails, stay on the pinned
version and write down what broke. The live tests name the feature (identity,
automations, connectors, network).

## 2. Upgrade (as the AGOS user)

The installer runs AGOS as its own Linux user (`agos` by default; its home is
`$AGOS_HOME` below). Do every step as that user.

```bash
sudo -iu agos
export XDG_RUNTIME_DIR=/run/user/$(id -u)
H=~/.local/bin/hermes
ROOTS=~/agos-data/hermes            # AGOS_HERMES_ROOTS (default <AGOS_DATA_DIR>/hermes)
```

**a) Where you are, and backups.** Back up code and data: a newer Hermes may
migrate its stores.

```bash
$H --version
git -C ~/.hermes/hermes-agent rev-parse HEAD > ~/hermes-before.sha
agos backup                                    # AGOS's own backup (agos.db + every root)
mkdir -p ~/hermes-upgrade-backup
$H backup --output ~/hermes-upgrade-backup/shared.zip --keep 0
for r in "$ROOTS"/agos-*; do
  HERMES_HOME=$r HERMES_RUNTIME_DIR=~/.hermes/tools $H backup \
    --output ~/hermes-upgrade-backup/$(basename "$r").zip --keep 0
done
```

**b) Stop AGOS and every workspace gateway.** Nothing may run old code during the
swap.

```bash
sudo systemctl stop agos-web agos-hooks agos-core
systemctl --user list-units --type=service --all 'hermes-gateway*' --no-legend \
  | awk '{print $1}' > ~/hermes-units.txt
xargs -r systemctl --user stop < ~/hermes-units.txt
```

**c) Update to the tested release.**

```bash
$H update --plan --channel stable              # read-only: must name the release you tested
$H update --channel stable --yes --no-gateway-restart
# If the stable channel lands on another release, pin the tested one:
#   git -C ~/.hermes/hermes-agent checkout --detach <sha> && $H pm repair
$H --version
```

**d) Prepare every home now** (each root builds its dependency environment on
first launch, which takes minutes). Install the memory plugin where it is missing
and check the config.

```bash
for r in "$ROOTS"/agos-*; do HERMES_HOME=$r HERMES_RUNTIME_DIR=~/.hermes/tools $H --version >/dev/null; done
for h in "$ROOTS"/agos-* "$ROOTS"/agos-*/profiles/*; do
  HERMES_HOME=$h HERMES_RUNTIME_DIR=~/.hermes/tools \
    $H plugins install holographic --yes-deps --enable || echo "FAILED: $h"
done
for r in "$ROOTS"/agos-*; do HERMES_HOME=$r HERMES_RUNTIME_DIR=~/.hermes/tools $H config check; done
```

**e) Start AGOS, then the gateways.** AGOS does not restart a gateway someone
stopped.

```bash
sudo systemctl start agos-core agos-hooks agos-web
xargs -r -n1 systemctl --user start < ~/hermes-units.txt
sleep 60; xargs -r systemctl --user is-active < ~/hermes-units.txt
```

Check in AGOS: a chat answers (a DM and a group), the Telegram bot answers, an
approval shows in the chat, an automation runs. Then, in the repository, set
`deploy/hermes.pin` to the new full sha and `HERMES_TESTED_VERSION` to the new
version, and commit.

## 3. Rollback

`hermes update` may refuse to go back to an older release, and a code checkout
alone does not roll back the data. So roll back code and data together, from the
backups of step 2a:

```bash
sudo -iu agos; export XDG_RUNTIME_DIR=/run/user/$(id -u)
H=~/.local/bin/hermes; ROOTS=~/agos-data/hermes
sudo systemctl stop agos-web agos-hooks agos-core
xargs -r systemctl --user stop < ~/hermes-units.txt
git -C ~/.hermes/hermes-agent checkout --detach "$(cat ~/hermes-before.sha)"
$H pm repair                                    # that revision's dependencies and launchers
for r in "$ROOTS"/agos-*; do                    # keep the current state aside first
  mv "$r" "$r.after-upgrade"
  mkdir "$r" && HERMES_HOME=$r HERMES_RUNTIME_DIR=~/.hermes/tools \
    $H import --force ~/hermes-upgrade-backup/$(basename "$r").zip
done
$H import --force ~/hermes-upgrade-backup/shared.zip
sudo systemctl start agos-core agos-hooks agos-web
xargs -r -n1 systemctl --user start < ~/hermes-units.txt
```

If `hermes pm repair` cannot rebuild the old revision, reinstall it pinned with
Hermes's own installer (what `deploy/install-server.sh` does):

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/<sha>/scripts/install.sh \
  | bash -s -- --commit <sha> --non-interactive
```

Then restore the data as above. Messages and runs made between the upgrade and
the rollback stay in the `*.after-upgrade` folders.

A newer AGOS may need a newer Hermes (the contract check fails on the older one).
Then a Hermes rollback means an AGOS rollback too: see
[runbooks/update-failed.md](runbooks/update-failed.md).
