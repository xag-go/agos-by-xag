#!/usr/bin/env bash
# Registers the self-hosted GitHub Actions runner that .github/workflows/nightly-hermes.yml
# needs (real Hermes tests, the e2e rig, agent evals, speed budgets), on this machine.
#
# What it sets up (docs/CI.md, "Nightly self-hosted runner"):
#   - a dedicated low-privilege Linux account (default `server-ci`): no sudo group, its own
#     0700 home, so a job can read neither the owner's keys (~/.ssh, gh login, Hermes's
#     .env) nor the live AGOS (/home/agos). Never the account that runs the live AGOS.
#     (A systemd *user* unit cannot hide files from its own uid on this kernel: unprivileged
#     user namespaces are refused, so ProtectHome / InaccessiblePaths are silently ignored.
#     A separate uid is the boundary.)
#   - that account's own Hermes Agent, pinned to deploy/hermes.pin (Hermes's install.sh),
#     and uv;
#   - the runner (actions/runner, pinned version, sha256 checked) with the labels
#     self-hosted, linux, hermes; one runner = one job at a time (the workflow's
#     concurrency group says the same);
#   - a systemd USER service of that account (lingering, so it runs with nobody logged in):
#     nice 19, idle IO, MemoryHigh/MemoryMax, a high OOM score (a squeeze kills the
#     nightly, never the live gateways);
#   - a clean-up hook run before and after every job and when the service stops: the
#     job's TMPDIR, the e2e / evals / perf rigs (their processes first) and pytest's
#     temp dirs. Only paths under the runner account's home are ever removed.
#
# The workflow runs on schedule and workflow_dispatch only, never pull_request (a fork's
# code must never reach a self-hosted runner): tests/test_ci_runner.py checks it.
#
# Usage:
#   deploy/register-ci-runner.sh --dry-run                 # print every step, change nothing
#   deploy/register-ci-runner.sh --repo OWNER/NAME [--token-file FILE]
#   deploy/register-ci-runner.sh --remove [--repo OWNER/NAME]
#   deploy/register-ci-runner.sh --render DIR              # only write the unit + hooks into DIR
#
# Options:
#   --repo OWNER/NAME     the GitHub repository (default: from `git remote get-url origin`)
#   --account NAME        the runner's Linux account (default server-ci)
#   --name NAME           the runner's name on GitHub (default <hostname>-hermes)
#   --token-file FILE     a registration token (mode 0600). Default: asked from GitHub with
#                         `gh api` (the caller's gh login; the token never goes on argv)
#   --memory-max SIZE     the service's hard memory cap (default 9G; MemoryHigh = 7G)
#   --dry-run             say what would be done; no sudo, no download, no file written
#   --remove              stop the service and unregister the runner (the account stays)
#
# It needs the owner's OK before a real run (it creates an account and registers a
# machine with GitHub). Afterwards: set the repository variable HERMES_RUNNER=on.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

RUNNER_VERSION="2.338.2"
RUNNER_SHA256="baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40"
RUNNER_LABELS="hermes" # added to the runner's own self-hosted, Linux, X64
UNIT="server-ci-runner.service"
# Accounts the runner must never be (the live AGOS's, root).
FORBIDDEN_ACCOUNTS="root agos"

ACCOUNT="server-ci"
REPO=""
NAME="$(hostname -s 2>/dev/null || echo host)-hermes"
TOKEN_FILE=""
MEMORY_MAX="9G"
MEMORY_HIGH="7G"
DRY=0
MODE="install"
RENDER_DIR=""

die() {
  echo "register-ci-runner: $*" >&2
  exit 1
}
say() { echo "==> $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs OWNER/NAME}"; shift 2 ;;
    --account) ACCOUNT="${2:?--account needs a name}"; shift 2 ;;
    --name) NAME="${2:?--name needs a name}"; shift 2 ;;
    --token-file) TOKEN_FILE="${2:?--token-file needs a file}"; shift 2 ;;
    --memory-max) MEMORY_MAX="${2:?--memory-max needs a size}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --remove) MODE="remove"; shift ;;
    --render) MODE="render"; RENDER_DIR="${2:?--render needs a folder}"; shift 2 ;;
    -h | --help) sed -n '2,47p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

[[ "$ACCOUNT" =~ ^[a-z][a-z0-9-]{1,30}$ ]] || die "account name '$ACCOUNT' is not a plain lowercase name"
for bad in $FORBIDDEN_ACCOUNTS; do
  [[ "$ACCOUNT" != "$bad" ]] || die "the runner may not run as '$ACCOUNT' (the live AGOS / root)"
done
[[ "$ACCOUNT" != "$(id -un)" ]] || die "the runner needs its own account, not yours ($ACCOUNT)"
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || die "runner name '$NAME' has characters GitHub refuses"
[[ "$MEMORY_MAX" =~ ^[0-9]+[KMG]$ ]] || die "--memory-max wants a size like 9G"

if [[ -z "$REPO" && "$MODE" != "render" ]]; then
  url="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  REPO="$(sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##' <<<"$url")"
fi
if [[ "$MODE" != "render" ]]; then
  [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "no GitHub repository (give --repo OWNER/NAME)"
fi

HOME_OF="/home/$ACCOUNT"
RUNNER_DIR="$HOME_OF/actions-runner"
JOB_TMP="$HOME_OF/.hermes/cache/scratch/agos-nightly-tmp"

# ---- the files it writes (also printed by --dry-run, written alone by --render) ----------

unit_text() {
  cat <<EOF
# AGOS nightly: the GitHub Actions runner (deploy/register-ci-runner.sh). One job at a time.
[Unit]
Description=GitHub Actions runner for the AGOS nightly (real Hermes)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$RUNNER_DIR
Environment=TMPDIR=$JOB_TMP
ExecStartPre=/usr/bin/bash $RUNNER_DIR/hooks/clean.sh
ExecStart=$RUNNER_DIR/run.sh
ExecStopPost=/usr/bin/bash $RUNNER_DIR/hooks/clean.sh
# The runner finishes its job step on SIGINT; the rest of the group goes after.
KillSignal=SIGINT
TimeoutStopSec=120
Restart=on-failure
RestartSec=60
# A guest on this machine: last for CPU and disk, killed first when RAM runs out.
Nice=19
CPUWeight=20
IOSchedulingClass=idle
OOMScoreAdjust=800
MemoryHigh=$MEMORY_HIGH
MemoryMax=$MEMORY_MAX
TasksMax=4096
NoNewPrivileges=yes
UMask=0077

[Install]
WantedBy=default.target
EOF
}

clean_text() {
  cat <<'EOF'
#!/usr/bin/env bash
# The AGOS nightly runner's clean-up (deploy/register-ci-runner.sh): before and after
# every job and when the service stops. Ends the rigs' processes, then removes the
# job's temp files and the rigs. Touches nothing outside this account's home.
set -uo pipefail
home="${CI_RUNNER_HOME:-$HOME}"
case "$home" in /home/*|/tmp/*|/var/tmp/*) ;; *) echo "clean: odd home $home" >&2; exit 1 ;; esac
scratch="$home/.hermes/cache/scratch"
rigs=("$home/agos-nightly-e2e" "$scratch/agos-nightly-evals" "$scratch/agos-nightly-perf")
# The rigs' processes: the core, the fakes and every Hermes gateway whose HERMES_HOME or
# command line is under a rig (rooms_e2e.py down does the same for one rig).
for proc in /proc/[0-9]*; do
  pid="${proc#/proc/}"
  [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
  env="$(tr '\0' '\n' <"$proc/environ" 2>/dev/null)" || continue
  cmd="$(tr '\0' ' ' <"$proc/cmdline" 2>/dev/null)" || continue
  for rig in "${rigs[@]}"; do
    if grep -qxF "HERMES_HOME=$rig" <<<"$env" || grep -q "^HERMES_HOME=$rig/" <<<"$env" \
      || [[ "$cmd" == *"$rig"* ]]; then
      kill -TERM "$pid" 2>/dev/null || true
      break
    fi
  done
done
sleep "${CLEAN_GRACE_S:-3}"
for rig in "${rigs[@]}"; do
  rm -rf -- "$rig"
done
tmp="$scratch/agos-nightly-tmp"
if [[ -d "$tmp" ]]; then
  find "$tmp" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null || true
fi
mkdir -p "$tmp"
echo "clean: rigs and temp files removed under $home"
EOF
}

env_text() {
  # The runner reads .env in its folder: every job gets these, and the hooks run.
  cat <<EOF
TMPDIR=$JOB_TMP
LANG=C.UTF-8
ACTIONS_RUNNER_HOOK_JOB_STARTED=$RUNNER_DIR/hooks/clean.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=$RUNNER_DIR/hooks/clean.sh
EOF
}

render() {
  local dir="$1"
  mkdir -p "$dir/hooks"
  unit_text >"$dir/$UNIT"
  clean_text >"$dir/hooks/clean.sh"
  chmod 0755 "$dir/hooks/clean.sh"
  env_text >"$dir/.env"
  say "wrote $dir/$UNIT, $dir/hooks/clean.sh, $dir/.env"
}

if [[ "$MODE" == "render" ]]; then
  render "$RENDER_DIR"
  exit 0
fi

# ---- running steps -------------------------------------------------------------------------

# run DESCRIPTION -- COMMAND...: runs it, or only says it on --dry-run.
run() {
  local what="$1"
  shift 2
  if [[ "$DRY" == 1 ]]; then
    printf 'DRY: %s\n     %s\n' "$what" "$*"
  else
    say "$what"
    "$@"
  fi
}

# as_ci SCRIPT: a bash script run by the runner account (its own HOME and user bus).
as_ci() {
  local uid
  uid="$(id -u "$ACCOUNT")"
  sudo -u "$ACCOUNT" -H env XDG_RUNTIME_DIR="/run/user/$uid" bash -euo pipefail -c "$1"
}

registration_token() {
  # stdout: a token; never printed by this script, never on a command line.
  local kind="$1"
  if [[ -n "$TOKEN_FILE" ]]; then
    [[ -f "$TOKEN_FILE" ]] || die "no token file $TOKEN_FILE"
    [[ "$(stat -c %a "$TOKEN_FILE")" == 600 ]] || die "$TOKEN_FILE must be mode 0600"
    tr -d '[:space:]' <"$TOKEN_FILE"
    return
  fi
  command -v gh >/dev/null || die "no --token-file and no gh CLI to ask GitHub for a token"
  gh api -X POST "repos/$REPO/actions/runners/$kind" --jq .token
}

preflight() {
  [[ "$(id -u)" != 0 ]] || die "run it as your own account (it uses sudo for the two root steps)"
  [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || die "Linux x86_64 only"
  command -v systemctl >/dev/null || die "systemd is needed"
  [[ -f "$REPO_ROOT/deploy/hermes.pin" ]] || die "deploy/hermes.pin is missing"
}

install_steps() {
  local hermes_commit
  hermes_commit="$(tr -d '[:space:]' <"$REPO_ROOT/deploy/hermes.pin")"
  [[ "$hermes_commit" =~ ^[0-9a-f]{40}$ ]] || die "deploy/hermes.pin is not a commit"
  local tarball="actions-runner-linux-x64-$RUNNER_VERSION.tar.gz"
  local url="https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$tarball"

  if id "$ACCOUNT" >/dev/null 2>&1; then
    say "account $ACCOUNT exists"
    local groups
    groups="$(id -nG "$ACCOUNT")"
    if grep -qwE 'sudo|wheel|adm|docker|lxd|libvirt' <<<"$groups"; then
      die "$ACCOUNT is in a privileged group ($groups): not low-privilege"
    fi
  else
    run "create the low-privilege account $ACCOUNT (root)" -- \
      sudo useradd --create-home --user-group --shell /bin/bash --comment "AGOS CI runner" "$ACCOUNT"
  fi
  run "close its home to other accounts (0700)" -- sudo chmod 0700 "$HOME_OF"
  run "let its user services run with nobody logged in (root)" -- \
    sudo loginctl enable-linger "$ACCOUNT"

  run "uv for $ACCOUNT (astral's installer)" -- as_ci \
    'command -v uv || [ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | sh'
  run "Hermes Agent for $ACCOUNT, pinned to deploy/hermes.pin ($hermes_commit)" -- as_ci \
    "[ -x ~/.local/bin/hermes ] && ~/.local/bin/hermes --version >/dev/null 2>&1 || {
       f=\$(mktemp); curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/$hermes_commit/scripts/install.sh -o \"\$f\"
       bash \"\$f\" --commit $hermes_commit --non-interactive; rc=\$?; rm -f \"\$f\"; exit \$rc; }"

  run "the runner $RUNNER_VERSION (sha256 checked) in $RUNNER_DIR" -- as_ci \
    "mkdir -p '$RUNNER_DIR' && cd '$RUNNER_DIR' && [ -x ./run.sh ] || {
       curl -fsSL -o '$tarball' '$url'
       echo '$RUNNER_SHA256  $tarball' | sha256sum -c -
       tar -xzf '$tarball' && rm -f '$tarball'; }"

  if [[ "$DRY" == 1 ]]; then
    echo "DRY: write $RUNNER_DIR/hooks/clean.sh:"
    clean_text | sed 's/^/     | /'
    echo "DRY: write $RUNNER_DIR/.env:"
    env_text | sed 's/^/     | /'
    echo "DRY: write $HOME_OF/.config/systemd/user/$UNIT:"
    unit_text | sed 's/^/     | /'
  else
    local staged
    staged="$(mktemp -d)"
    render "$staged"
    chmod -R a+rX "$staged"
    as_ci "mkdir -p '$RUNNER_DIR/hooks' ~/.config/systemd/user '$JOB_TMP'
           install -m 0755 '$staged/hooks/clean.sh' '$RUNNER_DIR/hooks/clean.sh'
           install -m 0600 '$staged/.env' '$RUNNER_DIR/.env'
           install -m 0644 '$staged/$UNIT' ~/.config/systemd/user/$UNIT"
    rm -rf "$staged"
  fi

  if [[ "$DRY" == 1 ]]; then
    echo "DRY: register with GitHub (token from ${TOKEN_FILE:-gh api repos/$REPO/actions/runners/registration-token}, passed as ACTIONS_RUNNER_INPUT_TOKEN, never on argv)"
    echo "     ./config.sh --unattended --replace --url https://github.com/$REPO --name $NAME --labels $RUNNER_LABELS --work _work"
  else
    say "register with GitHub as $NAME (labels self-hosted, linux, $RUNNER_LABELS)"
    local token
    token="$(registration_token registration-token)"
    [[ -n "$token" ]] || die "GitHub gave no registration token"
    local uid
    uid="$(id -u "$ACCOUNT")"
    printf '%s' "$token" | sudo -u "$ACCOUNT" -H env XDG_RUNTIME_DIR="/run/user/$uid" bash -euo pipefail -c \
      "cd '$RUNNER_DIR' && ACTIONS_RUNNER_INPUT_TOKEN=\"\$(cat)\" ./config.sh --unattended --replace \
         --url 'https://github.com/$REPO' --name '$NAME' --labels '$RUNNER_LABELS' --work _work"
    unset token
  fi

  run "start the service ($UNIT, user unit of $ACCOUNT)" -- as_ci \
    "systemctl --user daemon-reload && systemctl --user enable --now $UNIT && sleep 5 && systemctl --user is-active $UNIT"

  cat <<EOF

Next (by hand, once the runner shows as Idle in Settings → Actions → Runners):
  gh variable set HERMES_RUNNER --body on --repo $REPO
  gh workflow run nightly-hermes.yml -f stage=hermes-tests --repo $REPO
Logs: sudo -u $ACCOUNT XDG_RUNTIME_DIR=/run/user/\$(id -u $ACCOUNT) journalctl --user -u $UNIT
EOF
}

remove_steps() {
  run "stop and disable $UNIT" -- as_ci \
    "systemctl --user disable --now $UNIT || true; rm -f ~/.config/systemd/user/$UNIT; systemctl --user daemon-reload"
  if [[ "$DRY" == 1 ]]; then
    echo "DRY: unregister from GitHub (removal token from ${TOKEN_FILE:-gh api repos/$REPO/actions/runners/remove-token}, as ACTIONS_RUNNER_INPUT_TOKEN)"
    echo "     ./config.sh remove"
  else
    local token uid
    token="$(registration_token remove-token)"
    uid="$(id -u "$ACCOUNT")"
    printf '%s' "$token" | sudo -u "$ACCOUNT" -H env XDG_RUNTIME_DIR="/run/user/$uid" bash -euo pipefail -c \
      "cd '$RUNNER_DIR' && ACTIONS_RUNNER_INPUT_TOKEN=\"\$(cat)\" ./config.sh remove"
    unset token
  fi
  cat <<EOF
The account $ACCOUNT stays (its Hermes install and caches). To remove it too:
  sudo loginctl disable-linger $ACCOUNT && sudo userdel --remove $ACCOUNT
And: gh variable set HERMES_RUNNER --body off --repo $REPO
EOF
}

if [[ "$DRY" == 1 ]]; then
  say "dry run: nothing is changed (account $ACCOUNT, repository $REPO, runner $NAME)"
else
  preflight
fi
if [[ "$MODE" == "remove" ]]; then
  remove_steps
else
  install_steps
fi
