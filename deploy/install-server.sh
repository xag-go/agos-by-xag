#!/usr/bin/env bash
# AGOS Linux installer (the engine behind install.sh; also runs on its own).
# Ubuntu 22.04 / 24.04 LTS (Debian 12+ should work), 64-bit, systemd.
#
# Installs system packages, Docker, Node.js + pnpm, uv, Hermes (official installer,
# pinned to deploy/hermes.pin), AGOS core + web (production build), the workspace
# sandbox image, and systemd services that start at boot with nobody logged in.
# Nothing is opened to the internet: AGOS listens on 127.0.0.1 only.
# Safe to run again: finished steps are skipped.
#
#   sudo deploy/install-server.sh [options]
#   sudo deploy/install-server.sh --check        only report what is/isn't set up
#   deploy/install-server.sh --check-machine     only: can this machine run AGOS? (no sudo)
#   deploy/install-server.sh --which-release     only: the release it would install, and the channel
#
# Questions (asked with a default; each has a flag or variable for unattended
# installs; --yes or no keyboard = every default):
#   --user NAME | --current-user   AGOS_USER / AGOS_USER_MODE=new|current
#                                  run AGOS as a new user (default "agos") or as you
#   --data-dir DIR                 AGOS_DATA_DIR  (default: <that user's home>/agos-data)
#   --provider NAME | --skip-provider
#                                  AGOS_PROVIDER (+ its key in AGOS_PROVIDER_KEY or
#                                  AGOS_PROVIDER_KEY_FILE, never on the command line)
#   --voice off|gemini|openai|local  AGOS_VOICE (default off)
#   --remote yes|no                AGOS_REMOTE: use AGOS from other devices (Tailscale)
# Other:
#   --yes                  no questions (defaults + flags)
#   --server               an always-on machine: never sleep, firewall on (ufw),
#                          automatic security updates
#   --repo DIR             install AGOS from a local folder instead of git (development)
#   --hermes-commit SHA    another Hermes commit than deploy/hermes.pin
#   --no-start             set the services up but don't start them (before a restore)
#   --no-sandbox           skip building the sandbox image (tests only)
#   --no-cage              run every workspace's agents WITHOUT the cage around them
#                          (AGOS_SANDBOXD=off: they can reach this machine's Docker).
#                          Only for a machine that can't run it; Settings and agos
#                          doctor then say so. Without it the install refuses to finish
#                          when the cage's self-test fails (code cage_refused).
# Which AGOS: the newest stable release tag, checked against its signature
# (deploy/release-verify.sh); AGOS_CHANNEL=beta|main, AGOS_REF=<tag or branch>.
# This machine must have the measured minimum (docs/INSTALL.md, "Minimum hardware");
# AGOS_SKIP_HARDWARE_CHECK=1 installs below it anyway (it will be slow or fail).
# ok/miss always succeed, so "A && ok || miss" is a plain if/else here.
# shellcheck disable=SC2015
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_URL="${AGOS_REPO_URL:-https://github.com/xag-go/agos-by-xag.git}"
REF="${AGOS_REF:-}"
CHANNEL="${AGOS_CHANNEL:-}"
AGOS_USER="${AGOS_USER:-}"
USER_MODE="${AGOS_USER_MODE:-}"
DATA_DIR="${AGOS_DATA_DIR:-}"
PROVIDER="${AGOS_PROVIDER:-}"
KEY_FILE="${AGOS_PROVIDER_KEY_FILE:-}"
VOICE="${AGOS_VOICE:-}"
REMOTE="${AGOS_REMOTE:-}"
# The cage around each workspace's gateway (engine/cage.py): required unless the
# owner says off (audit F9). A re-run keeps an earlier --no-cage (agos.conf).
CAGE="${AGOS_SANDBOXD:-}"
YES="${AGOS_YES:-0}"
INVOKER="${AGOS_INVOKING_USER:-${SUDO_USER:-}}"
HOST_OS="${AGOS_HOST_OS:-linux}"
HERMES_COMMIT="$(cat "$HERE/hermes.pin" 2>/dev/null || true)"
LOCAL_REPO=""
CHECK_ONLY=0
CHECK_MACHINE=0
WHICH_RELEASE=0
SERVER=0
START=1
SANDBOX=1
DRY_RUN="${AGOS_INSTALL_DRY_RUN:-0}"
CONF=/etc/agos/agos.conf
# A key handed over in the environment goes to a private file at once.
if [[ -n "${AGOS_PROVIDER_KEY:-}" && -z "$KEY_FILE" ]]; then
  KEY_FILE="$(umask 077; mktemp)"
  printf '%s' "$AGOS_PROVIDER_KEY" > "$KEY_FILE"
fi
unset AGOS_PROVIDER_KEY

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) AGOS_USER="$2"; USER_MODE=new; shift 2 ;;
    --current-user) USER_MODE=current; shift ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --skip-provider) PROVIDER=skip; shift ;;
    --voice) VOICE="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --server) SERVER=1; shift ;;
    --repo) LOCAL_REPO="$(cd "$2" && pwd)"; shift 2 ;;
    --hermes-commit) HERMES_COMMIT="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    --no-sandbox) SANDBOX=0; shift ;;
    --no-cage) CAGE=off; shift ;;
    --check) CHECK_ONLY=1; shift ;;
    --check-machine) CHECK_MACHINE=1; shift ;;
    --which-release) WHICH_RELEASE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option $1 (see --help)" >&2; exit 1 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf '  WARNING: %s\n' "$*"; }
run() { if [[ "$DRY_RUN" == 1 ]]; then echo "DRY: $*"; else "$@"; fi; }
ok() { printf '  [ok] %s\n' "$*"; }
miss() { printf '  [--] %s\n' "$*"; MISSING=$((MISSING + 1)); }
# As the AGOS user, with its own home and groups (docker).
as_user() { run sudo -u "$AGOS_USER" -H --preserve-env=COREPACK_ENABLE_DOWNLOAD_PROMPT,CI -- "$@"; }

# --------------------------------------------------------------- release ----------
# The release to install (REF) and the channel agos update follows (CHANNEL).
pick_release() {
  if [[ -n "$REF" ]]; then
    if [[ -z "$CHANNEL" ]]; then
      if [[ "$REF" =~ ^v[0-9] ]]; then CHANNEL=stable; else CHANNEL=main; fi
    fi
    return 0
  fi
  CHANNEL="${CHANNEL:-stable}"
  if [[ "$CHANNEL" != main ]]; then
    local re='^v[0-9]+\.[0-9]+\.[0-9]+$'
    [[ "$CHANNEL" == beta ]] && re='^v[0-9]+\.[0-9]+\.[0-9]+(-(beta|rc)\.[0-9]+)?$'
    # Version order with a beta before its release ("~" sorts first in sort -V).
    REF="$({ git ls-remote --tags --refs "$REPO_URL" 'v*' 2>/dev/null | sed 's|.*refs/tags/||' | grep -E "$re" || true; } |
      sed -E 's/-(beta|rc)\./~\1./' | sort -V | sed 's/~/-/' | awk 'END {print}')"
  fi
  if [[ -z "$REF" ]]; then
    [[ "$CHANNEL" == main ]] || warn "no $CHANNEL release is published yet: installing the main branch."
    REF=main
  fi
}

# ------------------------------------------------------------------ check ---------
check() {
  # shellcheck disable=SC1090
  [[ -r "$CONF" ]] && AGOS_USER="$(. "$CONF"; echo "$AGOS_USER")"
  AGOS_USER="${AGOS_USER:-agos}"
  local home; home="$(getent passwd "$AGOS_USER" | cut -d: -f6 || true)"
  MISSING=0
  say "AGOS check"
  command -v docker >/dev/null && systemctl is-enabled docker >/dev/null 2>&1 && ok "Docker (starts at boot)" || miss "Docker"
  id "$AGOS_USER" >/dev/null 2>&1 && ok "user $AGOS_USER" || miss "user $AGOS_USER"
  sudo -u "$AGOS_USER" -H "$home/.local/bin/hermes" --version >/dev/null 2>&1 && ok "Hermes installed" || miss "Hermes"
  for s in agos-core agos-hooks agos-web; do
    systemctl is-enabled "$s" >/dev/null 2>&1 && ok "$s service (starts at boot)" || miss "$s service"
  done
  systemctl is-enabled agos-deadman.timer >/dev/null 2>&1 && ok "dead-man check (Telegram when the core is down)" || miss "agos-deadman.timer"
  command -v agos >/dev/null && ok "agos command" || miss "agos command"
  loginctl show-user "$AGOS_USER" 2>/dev/null | grep -q "Linger=yes" && ok "linger (runs with nobody logged in)" || miss "linger"
  # shellcheck disable=SC1090
  if [[ "$( [[ -r "$CONF" ]] && (. "$CONF"; echo "${AGOS_SANDBOXD:-}") )" == off ]]; then
    echo "  [!!] workspace isolation is OFF on purpose (--no-cage): agents can reach Docker"
  else
    bash "$HERE/cage-setup.sh" self-test "$AGOS_USER" >/dev/null 2>&1 && ok "workspace isolation (the cage works)" \
      || miss "workspace isolation: the cage can't run (sudo bash $HERE/cage-setup.sh self-test $AGOS_USER says why)"
  fi
  curl -fsS -m 5 -o /dev/null http://127.0.0.1:8766/health 2>/dev/null && ok "core answers" || miss "core not answering"
  curl -fsS -m 10 -o /dev/null http://127.0.0.1:3000/ 2>/dev/null && ok "web answers on http://localhost:3000" || miss "web not answering"
  echo; [[ $MISSING -eq 0 ]] && echo "All set." || echo "$MISSING item(s) missing."
}
if [[ "$CHECK_ONLY" == 1 ]]; then check; exit 0; fi
if [[ "$WHICH_RELEASE" == 1 ]]; then pick_release; echo "$REF $CHANNEL"; exit 0; fi
[[ "$DRY_RUN" == 1 || "$CHECK_MACHINE" == 1 || $EUID -eq 0 ]] || die "Run with sudo (or use install.sh, which asks for it)."

# ------------------------------------------------------- requirements -------------
# The measured minimum (deploy/test-hardware-vm.sh; docs/INSTALL.md "Minimum hardware"):
# below MIN the install stops, below WARN it warns. MemTotal is a little under the
# machine's RAM (the kernel keeps some), so 4 GB machines show ~3.8 GB.
MIN_RAM_MB=3500
WARN_RAM_MB=7500
MIN_CPUS=2
hardware_check() {
  local ram_mb cpus
  ram_mb=$(( $(awk '/MemTotal/ {print $2}' "${AGOS_MEMINFO:-/proc/meminfo}") / 1024 ))
  cpus="${AGOS_NPROC:-$(nproc)}"
  if (( ram_mb < MIN_RAM_MB || cpus < MIN_CPUS )); then
    if [[ "${AGOS_SKIP_HARDWARE_CHECK:-0}" == 1 ]]; then
      warn "below AGOS's minimum (${ram_mb} MB memory, ${cpus} CPUs; needs 4 GB and 2 CPUs): installing anyway (AGOS_SKIP_HARDWARE_CHECK=1)."
      return 0
    fi
    die "This machine has ${ram_mb} MB of memory and ${cpus} CPU(s). AGOS needs at least 4 GB of memory and 2 CPUs
       (measured: AGOS with two workspaces uses up to 1.7 GB, and installing or updating also builds
       the web app). Use a bigger machine or VM,
       or set AGOS_SKIP_HARDWARE_CHECK=1 to install anyway. Nothing was installed."
  fi
  if (( ram_mb < WARN_RAM_MB )); then
    warn "$(( (ram_mb + 512) / 1024 )) GB of memory: enough for 1-2 workspaces; 8 GB or more is recommended (16 GB for several busy workspaces)."
  else
    ok "$(( (ram_mb + 512) / 1024 )) GB memory, ${cpus} CPUs"
  fi
}
say "Checking this machine"
# shellcheck disable=SC1091
[[ -r /etc/os-release ]] && . /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|ubuntu:26.04) ok "${PRETTY_NAME}" ;;
  ubuntu:*|debian:12|debian:13) warn "${PRETTY_NAME:-this system} is not tested; Ubuntu 24.04 LTS is." ;;
  *) die "AGOS installs on Ubuntu 22.04 or 24.04 (found ${PRETTY_NAME:-unknown}). On macOS or Windows use install.sh / install.ps1." ;;
esac
case "$(uname -m)" in x86_64|aarch64) ok "64-bit ($(uname -m))" ;; *) die "A 64-bit system is needed (found $(uname -m))." ;; esac
[[ -d /run/systemd/system ]] || die "systemd is not running. (WSL: add [boot] systemd=true to /etc/wsl.conf, then wsl --shutdown.)"
hardware_check
free_gb=$(( $(df -Pk / | awk 'NR==2 {print $4}') / 1024 / 1024 ))
if [[ $free_gb -lt 20 && "${AGOS_SKIP_DISK_CHECK:-0}" != 1 ]]; then
  die "Only ${free_gb} GB free on /: AGOS needs 20 GB (Docker images, Hermes, the build, your data)."
fi
ok "${free_gb} GB free disk"
if grep -qw landlock /sys/kernel/security/lsm 2>/dev/null; then ok "Landlock (walls between workspaces)"; else warn "this kernel has no Landlock: workspaces are not walled from each other's files."; fi
if [[ "$CHECK_MACHINE" == 1 ]]; then echo; echo "This machine can run AGOS."; exit 0; fi

# ---------------------------------------------------------- questions --------------
# Read from the keyboard even when this script came through a pipe; never echo a key.
interactive() { [[ "$YES" != 1 ]] && [[ -r /dev/tty ]] && { : </dev/tty; } 2>/dev/null; }
ask() { # ask VAR "question" default
  local reply=""
  if interactive; then read -r -p "$2 [$3]: " reply </dev/tty || true; fi
  printf -v "$1" '%s' "${reply:-$3}"
}
[[ "$INVOKER" != root ]] || INVOKER=""
# An install that is already there keeps its user and data folder.
if [[ -r "$CONF" ]]; then
  # shellcheck disable=SC1090
  PREV_USER="$(. "$CONF"; echo "${AGOS_USER:-}")"
  # shellcheck disable=SC1090
  PREV_DATA="$(. "$CONF"; echo "${AGOS_DATA_DIR:-}")"
  if [[ -z "$AGOS_USER" || "$AGOS_USER" == "$PREV_USER" ]]; then AGOS_USER="$PREV_USER"; USER_MODE=existing; fi
  [[ -z "$DATA_DIR" ]] && DATA_DIR="$PREV_DATA"
  # shellcheck disable=SC1090
  [[ -n "$CAGE" ]] || CAGE="$(. "$CONF"; echo "${AGOS_SANDBOXD:-}")"
  ok "AGOS is already installed for user $AGOS_USER: checking that install"
fi
if [[ -z "$USER_MODE" ]]; then
  if [[ -n "$INVOKER" ]] && interactive; then
    echo
    echo "Which Linux user runs AGOS?"
    echo "  1) a new user named 'agos' just for AGOS (recommended: keeps AGOS apart from your files)"
    echo "  2) you ($INVOKER)"
    choice=""; ask choice "Pick 1 or 2" 1
    [[ "$choice" == 2 ]] && USER_MODE=current || USER_MODE=new
  else
    USER_MODE=new
  fi
fi
case "$USER_MODE" in
  current) [[ -n "$INVOKER" ]] || die "--current-user needs to be run with sudo from your own account."; AGOS_USER="$INVOKER" ;;
  new) AGOS_USER="${AGOS_USER:-agos}" ;;
  existing) ;;
  *) die "AGOS_USER_MODE is new or current (got $USER_MODE)." ;;
esac
[[ "$AGOS_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "'$AGOS_USER' is not a valid user name."
HOME_DIR="$(getent passwd "$AGOS_USER" | cut -d: -f6 || true)"
HOME_DIR="${HOME_DIR:-/home/$AGOS_USER}"

if [[ -z "$DATA_DIR" ]]; then
  if interactive; then
    echo; echo "Where should AGOS keep its data (workspaces, files, settings)?"
    ask DATA_DIR "Data folder" "$HOME_DIR/agos-data"
  else
    DATA_DIR="$HOME_DIR/agos-data"
  fi
fi
DATA_DIR="${DATA_DIR/#\~/$HOME_DIR}"
[[ "$DATA_DIR" == /* ]] || die "The data folder must be a full path (got $DATA_DIR)."
DATA_DIR="${DATA_DIR%/}"
BACKUP_DIR="$(dirname "$DATA_DIR")/agos-backups"

if [[ -z "$PROVIDER" ]]; then
  [[ -z "$KEY_FILE" ]] || die "AGOS_PROVIDER_KEY needs AGOS_PROVIDER too (e.g. openrouter, anthropic, openai, gemini)."
  if interactive; then
    echo; echo "AI model: AGOS's agents need a model provider (OpenRouter, Anthropic, OpenAI, Gemini...)."
    echo "Hermes's own setup can ask for it now, or you add it later in AGOS: Settings -> Models."
    answer=""; ask answer "Set up a model provider now? (y/n)" n
    [[ "$answer" =~ ^[Yy] ]] && PROVIDER=hermes || PROVIDER=skip
  else
    PROVIDER=skip
  fi
fi
[[ "$PROVIDER" =~ ^[a-z0-9][a-z0-9-]{0,40}$ ]] || die "Odd provider name '$PROVIDER'."
if [[ "$PROVIDER" != skip && "$PROVIDER" != hermes && -z "$KEY_FILE" ]]; then
  if interactive; then
    KEY_FILE="$(umask 077; mktemp)"
    read -r -s -p "API key for $PROVIDER (not shown; empty = skip): " key </dev/tty || true; echo
    printf '%s' "${key:-}" > "$KEY_FILE"; unset key
  else
    die "--provider $PROVIDER needs its key in AGOS_PROVIDER_KEY or AGOS_PROVIDER_KEY_FILE."
  fi
fi

if [[ -z "$VOICE" ]]; then
  if interactive; then
    echo; echo "Voice notes: who turns your voice messages into text?"
    echo "  off (default) | gemini (your Gemini key) | openai (your OpenAI key) | local (on this machine, no key)"
    ask VOICE "Voice notes" off
  else
    VOICE=off
  fi
fi
case "$VOICE" in off|gemini|openai|local) ;; *) die "Voice notes: off, gemini, openai or local (got $VOICE)." ;; esac

if [[ -z "$REMOTE" ]]; then
  if interactive; then
    echo; echo "Use AGOS from other devices (your phone, another computer)? This installs"
    echo "Tailscale (a private network only your devices join); nothing is opened to the internet."
    ask REMOTE "Other devices (yes/no)" no
  else
    REMOTE=no
  fi
fi
case "$REMOTE" in [Yy]*) REMOTE=yes ;; *) REMOTE=no ;; esac
case "${CAGE,,}" in off) CAGE=off ;; *) CAGE=required ;; esac

echo
echo "Installing AGOS for user '$AGOS_USER', data in $DATA_DIR; model provider: $PROVIDER; voice notes: $VOICE; other devices: $REMOTE"

# Never wait for a question from apt/debconf/needrestart; nothing below reads the
# keyboard except Hermes's own model setup (on /dev/tty, outside the log).
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a NEEDRESTART_SUSPEND=1
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=1
exec </dev/null
cd /  # the AGOS user may not enter the folder this was started from
LOG="/var/log/agos-install.log"
if [[ "$DRY_RUN" != 1 ]]; then
  # Its own log (no "| tee" needed: a pipe after sudo can freeze apt in a terminal).
  touch "$LOG" && chmod 600 "$LOG"
  exec > >(tee -a "$LOG") 2>&1
  echo "log: $LOG"
fi
cleanup() { [[ -z "$KEY_FILE" ]] || rm -f "$KEY_FILE"; }
trap cleanup EXIT
trap 'echo; echo "ERROR: the install stopped (line $LINENO). Fix what it says above and run the same command again: finished steps are skipped. Log: $LOG" >&2' ERR

APT=(apt-get install -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
say "System packages"
run apt-get update -y -q
run "${APT[@]}" ca-certificates curl gnupg git jq sqlite3 python3 python3-venv \
  build-essential rsync xz-utils unzip libatomic1 sudo bubblewrap

# The gateways' cage is bwrap (docs/adr/0025): bubblewrap from the system's package
# manager, user namespaces where the kernel has them off, and bwrap's AppArmor
# profile where the kernel restricts user namespaces (Ubuntu 24.04). The self-test
# once the AGOS user exists decides whether the install goes on.
if [[ "$CAGE" == off ]]; then
  warn "the cage is OFF on purpose (--no-cage / AGOS_SANDBOXD=off): every workspace's agents can reach this machine's Docker."
else
  run bash "$HERE/cage-setup.sh" install
fi

say "Docker Engine (official repository)"
if ! command -v docker >/dev/null; then
  run install -m 0755 -d /etc/apt/keyrings
  run bash -c "curl -fsSL https://download.docker.com/linux/$ID/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg"
  run bash -c "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$ID ${VERSION_CODENAME} stable\" > /etc/apt/sources.list.d/docker.list"
  run apt-get update -y -q
  run "${APT[@]}" docker-ce docker-ce-cli containerd.io docker-buildx-plugin
fi
run systemctl enable --now docker

# The web app asks for Node >= 24 (package.json "engines").
NODE_MAJOR=24
say "Node.js $NODE_MAJOR + pnpm"
if ! command -v node >/dev/null || [[ "$(node -v | cut -d. -f1 | tr -d v)" -lt $NODE_MAJOR ]]; then
  run bash -c "curl -fsSL https://deb.nodesource.com/setup_$NODE_MAJOR.x | bash - && apt-get install -y -q nodejs"
fi
[[ "$DRY_RUN" == 1 ]] || [[ "$(node -v | cut -d. -f1 | tr -d v)" -ge $NODE_MAJOR ]] \
  || die "Node $NODE_MAJOR or newer is needed (found $(node -v))."
run corepack enable

say "User $AGOS_USER"
# A user made here is removed again by `agos uninstall`; your own user never is.
# shellcheck disable=SC1090
DEDICATED="$( [[ -r "$CONF" ]] && (. "$CONF"; echo "${AGOS_DEDICATED_USER:-no}") || echo no)"
if ! id "$AGOS_USER" >/dev/null 2>&1; then
  run useradd --create-home --shell /bin/bash "$AGOS_USER"
  DEDICATED=yes
  # A home left by an earlier install (data kept) belongs to the new user.
  run chown "$AGOS_USER:$AGOS_USER" "$(getent passwd "$AGOS_USER" | cut -d: -f6)"
fi
HOME_DIR="$(getent passwd "$AGOS_USER" | cut -d: -f6 || echo "/home/$AGOS_USER")"
# docker: its sandboxes; systemd-journal: `agos logs` without sudo.
run usermod -aG docker,systemd-journal "$AGOS_USER"
run loginctl enable-linger "$AGOS_USER"
UID_N="$(id -u "$AGOS_USER" 2>/dev/null || echo 1000)"
# The user's own systemd (Hermes's gateways run there) must be up before Hermes.
for _ in $(seq 1 30); do [[ -S /run/user/$UID_N/bus || "$DRY_RUN" == 1 ]] && break; sleep 1; done
if [[ "$CAGE" != off ]]; then
  say "Workspace isolation (the cage around each workspace's agents)"
  # The same kind of bwrap run as each gateway's cage, as the AGOS user. No cage =
  # no install: it prints "ERROR cage_refused" with the fix for this machine.
  if ! run bash "$HERE/cage-setup.sh" self-test "$AGOS_USER"; then
    echo "The install stopped before Hermes and the build: nothing else changed. Log: $LOG" >&2
    exit 3
  fi
fi
# The AGOS user may start/stop/restart ITS services (agos command, update) and read
# the firewall state, nothing else.
SUDOERS="$(
  printf 'Cmnd_Alias AGOS_SERVICES = /usr/sbin/ufw status'
  for verb in start stop restart; do
    for set in "agos-core agos-hooks agos-web" "agos-web agos-hooks agos-core" "agos-core agos-web agos-hooks" \
               "agos-web agos-core agos-hooks" "agos-web agos-core" "agos-core agos-web"; do
      printf ', /usr/bin/systemctl %s %s' "$verb" "$set"
    done
  done
  printf '\n%s ALL=(root) NOPASSWD: AGOS_SERVICES\n' "$AGOS_USER"
)"
run bash -c 'printf "%s\n" "$1" > /etc/sudoers.d/agos.tmp && chmod 440 /etc/sudoers.d/agos.tmp && visudo -cqf /etc/sudoers.d/agos.tmp && mv /etc/sudoers.d/agos.tmp /etc/sudoers.d/agos' _ "$SUDOERS"

[[ -n "$HERMES_COMMIT" ]] || die "deploy/hermes.pin is missing (the Hermes commit to install)."
say "Hermes Agent (pinned to ${HERMES_COMMIT:0:12})"
HERMES="$HOME_DIR/.local/bin/hermes"
have="$(sudo -u "$AGOS_USER" -H "$HERMES" --version 2>/dev/null || true)"
if ! grep -q "${HERMES_COMMIT:0:7}" <<<"$have"; then
  [[ -z "$have" ]] || echo "  Hermes ($(head -1 <<<"$have")) moves to the commit AGOS is tested with."
  # Download first (a refused download, e.g. GitHub 429, must stop here, not be
  # piped into bash as nothing); retried a few times.
  for try in 1 2 3 4 5; do
    # A fresh private file (mktemp), never a predictable /tmp name.
    as_user bash -c "set -o pipefail; f=\$(mktemp) || exit 1; curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/$HERMES_COMMIT/scripts/install.sh -o \"\$f\" && XDG_RUNTIME_DIR=/run/user/$UID_N bash \"\$f\" --commit $HERMES_COMMIT --non-interactive; rc=\$?; rm -f \"\$f\"; exit \$rc" && break
    [[ $try == 5 ]] && die "Hermes did not install (network?). Run this again in a few minutes."
    echo "  Hermes install failed (try $try), retrying in $((try * 20))s"; sleep $((try * 20))
  done
else
  ok "Hermes is at the pinned commit"
fi
[[ "$DRY_RUN" == 1 ]] || sudo -u "$AGOS_USER" -H "$HERMES" --version >/dev/null || die "Hermes is not installed: run this again."
sudo -u "$AGOS_USER" -H test -x "$HOME_DIR/.local/bin/uv" || as_user bash -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
# Approvals for anything not managed by AGOS stay manual.
as_user "$HERMES" config set approvals.mode manual >/dev/null || true

say "AGOS (core + web, production build)"
APP="$HOME_DIR/agos"
if [[ -n "$LOCAL_REPO" ]]; then
  run rsync -a --delete --exclude node_modules --exclude .next --exclude .venv --exclude agos-data "$LOCAL_REPO/" "$APP/"
  run chown -R "$AGOS_USER:$AGOS_USER" "$APP"
elif [[ ! -d "$APP/.git" ]]; then
  [[ ! -e "$APP" ]] || die "$APP exists but is not an AGOS checkout; move it away first."
  pick_release
  as_user git clone -q --branch "$REF" "$REPO_URL" "$APP" || die "Could not download AGOS from $REPO_URL ($REF)."
  if [[ "$REF" =~ ^v[0-9] ]]; then
    # Before any of it is built or run: the tag is the signed release (ADR 0028).
    as_user env AGOS_VERIFY="${AGOS_VERIFY:-require}" bash "$APP/deploy/release-verify.sh" "$REF" \
      "$(sudo -u "$AGOS_USER" git -C "$APP" rev-parse HEAD)" "$HOME_DIR/.local/bin" \
      || { run rm -rf "$APP"; die "AGOS $REF is not the signed release; nothing of it was installed (see above)."; }
  fi
else
  ok "already downloaded (agos update brings new releases)"
fi
# Build only when the code changed since the last good build (a re-run is quick).
built="$(cat "$APP/.agos-built" 2>/dev/null || true)"
head_id="$(sudo -u "$AGOS_USER" git -C "$APP" rev-parse HEAD 2>/dev/null || echo "folder-$(date +%s)")"
if [[ "$built" != "$head_id" || ! -f "$APP/apps/web/.next/BUILD_ID" ]]; then
  as_user bash -c "cd '$APP' && pnpm install --frozen-lockfile && pnpm --filter @agos/web build"
  as_user bash -c "cd '$APP/services/core' && ~/.local/bin/uv sync --frozen"
  as_user bash -c "echo '$head_id' > '$APP/.agos-built'"
else
  ok "build is current (${head_id:0:12})"
fi
if [[ "$SANDBOX" == 1 ]]; then
  if sudo -u "$AGOS_USER" -H docker image inspect agos-sandbox:desktop >/dev/null 2>&1; then
    ok "sandbox image is there"
  else
    as_user bash -c "cd '$APP' && scripts/build-sandbox.sh"
  fi
fi
run install -d -o "$AGOS_USER" -g "$AGOS_USER" -m 700 "$DATA_DIR" "$BACKUP_DIR"
# Data kept from an earlier install (agos uninstall --keep-data) becomes this user's.
for d in "$DATA_DIR" "$BACKUP_DIR"; do
  [[ "$(stat -c %u "$d" 2>/dev/null)" == "$UID_N" && "$(stat -c %u "$d/system" 2>/dev/null || echo "$UID_N")" == "$UID_N" ]] \
    || run chown -R "$AGOS_USER:$AGOS_USER" "$d"
done

say "systemd services (start at boot, restart on failure, nobody logged in)"
# Resource limits, scaled to this machine's RAM (one runaway service must not take
# the machine; docs/adr/0025-workspace-isolation.md). Overridable per service:
# AGOS_CORE_MEMORY_MAX / AGOS_WEB_MEMORY_MAX / AGOS_HOOKS_MEMORY_MAX (e.g. "3072M").
# Each workspace's Hermes gateway gets its own (core writes them: engine/unit_limits.py).
total_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
clamp_mb() { local v=$(( total_mb / $1 )); (( v < $2 )) && v=$2; (( v > $3 )) && v=$3; echo "$v"; }
CORE_MEM_MAX="${AGOS_CORE_MEMORY_MAX:-$(clamp_mb 4 1024 3072)M}"
CORE_MEM_HIGH="${AGOS_CORE_MEMORY_HIGH:-$(clamp_mb 6 768 2048)M}"
WEB_MEM_MAX="${AGOS_WEB_MEMORY_MAX:-$(clamp_mb 8 512 1024)M}"
HOOKS_MEM_MAX="${AGOS_HOOKS_MEMORY_MAX:-256M}"
write_unit() {
  if [[ "$DRY_RUN" == 1 ]]; then echo "DRY: write /etc/systemd/system/$1.service"; else printf '%s\n' "$2" > "/etc/systemd/system/$1.service"; fi
}
write_unit agos-core "[Unit]
Description=AGOS core
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/services/core
Environment=AGOS_ENGINE=hermes
Environment=AGOS_DATA_DIR=$DATA_DIR
Environment=AGOS_BACKUP_DIR=$BACKUP_DIR
Environment=AGOS_APP_DIR=$APP
Environment=PATH=$HOME_DIR/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=AGOS_HERMES_BIN=$HERMES
Environment=XDG_RUNTIME_DIR=/run/user/$UID_N
Environment=LANG=C.UTF-8
$( [[ "$CAGE" == off ]] && echo "# --no-cage: gateways run WITHOUT the cage (Settings and agos doctor say so)." && echo "Environment=AGOS_SANDBOXD=off" )
ExecStart=$HOME_DIR/.local/bin/uv run --frozen uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port 8766
Restart=always
RestartSec=3
# process: a restart of the core leaves whatever it started running. Each
# workspace's Hermes gateway is Hermes's own systemd user service (outside the
# core's cgroup); this only spares helper processes the core itself spawned.
KillMode=process
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
# Limits (scaled to RAM; see above): reclaimed hard above High, killed above Max.
# The OOM killer takes a runaway gateway or sandbox first, never the core.
MemoryAccounting=yes
MemoryHigh=$CORE_MEM_HIGH
MemoryMax=$CORE_MEM_MAX
TasksMax=512
OOMScoreAdjust=-500
# Other users' processes are invisible in /proc (gateways run as this same user
# and stay visible). The core keeps the Docker socket: it builds the sandbox
# image and starts each workspace's egress proxy and MCP containers.
ProtectProc=invisible
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes

[Install]
WantedBy=multi-user.target"
# The webhook relay: passes ONLY "POST /hooks/<token>" to the core. It is the one
# port a public tunnel may point at (optional).
write_unit agos-hooks "[Unit]
Description=AGOS webhook relay
After=agos-core.service
Wants=agos-core.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/services/core
Environment=PATH=$HOME_DIR/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$HOME_DIR/.local/bin/uv run --frozen python -m agos_core.hook_relay
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
# A tiny relay: tight limits, no Docker socket, only its own /proc pids.
MemoryAccounting=yes
MemoryMax=$HOOKS_MEM_MAX
TasksMax=64
InaccessiblePaths=-/run/docker.sock
ProtectProc=invisible
ProcSubset=pid
PrivateDevices=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target"
write_unit agos-web "[Unit]
Description=AGOS web
After=agos-core.service
Wants=agos-core.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/apps/web
Environment=NODE_ENV=production
Environment=AGOS_CORE_URL=http://127.0.0.1:8766
Environment=AGOS_INTERNAL_TOKEN_FILE=$DATA_DIR/system/internal.token
ExecStart=/usr/bin/env pnpm exec next start -H 127.0.0.1 -p 3000
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
# The web never talks to Docker and never looks at other processes.
MemoryAccounting=yes
MemoryMax=$WEB_MEM_MAX
TasksMax=256
InaccessiblePaths=-/run/docker.sock
ProtectProc=invisible
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes

[Install]
WantedBy=multi-user.target"

# Journal size cap: AGOS's three services plus every gateway log to journald;
# without a cap they ride Ubuntu's 10% / 4 GB default (docs-ops audit §5).
run install -d /etc/systemd/journald.conf.d
run bash -c 'printf "%s\n" "# Written by the AGOS installer." "[Journal]" "SystemMaxUse=1G" > /etc/systemd/journald.conf.d/agos.conf'
run systemctl restart systemd-journald || true

say "The agos command"
run install -d -m 755 /etc/agos
CONF_TEXT="# Written by the AGOS installer; read by the agos command.
AGOS_USER=$AGOS_USER
AGOS_HOME=$HOME_DIR
AGOS_APP=$APP
AGOS_DATA_DIR=$DATA_DIR
AGOS_BACKUP_DIR=$BACKUP_DIR
AGOS_REPO_URL=$REPO_URL
AGOS_REF=$( [[ "$REF" =~ ^v[0-9] ]] && echo main || echo "$REF" )
AGOS_CHANNEL=$CHANNEL
AGOS_LOCAL_REPO=$LOCAL_REPO
AGOS_HOST_OS=$HOST_OS
AGOS_DEDICATED_USER=$DEDICATED
AGOS_SANDBOXD=$CAGE"
run bash -c 'printf "%s\n" "$1" > "$2" && chmod 644 "$2"' _ "$CONF_TEXT" "$CONF"
# A small launcher: the real command is in the release (deploy/agos), so it is
# updated with AGOS. AGOS's files are its user's: anyone else runs it through sudo.
# shellcheck disable=SC2016  # expanded when the launcher runs, not now
LAUNCHER='#!/bin/bash
# The agos command (AGOS installer). The real one: $AGOS_APP/deploy/agos.
. /etc/agos/agos.conf
real="$AGOS_APP/deploy/agos"
if [[ -r "$real" ]]; then exec bash "$real" "$@"; fi
[[ -e /etc/agos/agos.conf ]] || { echo "AGOS is not installed." >&2; exit 1; }
exec sudo bash "$real" "$@"'
run rm -f /usr/local/bin/agos
run bash -c 'printf "%s\n" "$1" > /usr/local/bin/agos && chmod 755 /usr/local/bin/agos' _ "$LAUNCHER"

# The dead-man (docs/error-monitoring.md): every minute, outside the core, a tiny
# check of the core's /health; down for 3 minutes = one Telegram message to the
# owner straight from the Bot API (deploy/agos-deadman.py), "back up" after.
write_unit agos-deadman "[Unit]
Description=AGOS dead-man (tells the owner on Telegram when the core is down)

[Service]
Type=oneshot
User=$AGOS_USER
Environment=AGOS_DATA_DIR=$DATA_DIR
ExecStart=/usr/bin/python3 $APP/deploy/agos-deadman.py
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes"
if [[ "$DRY_RUN" == 1 ]]; then echo "DRY: write /etc/systemd/system/agos-deadman.timer"; else
  printf '%s\n' "[Unit]
Description=AGOS dead-man check every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s

[Install]
WantedBy=timers.target" > /etc/systemd/system/agos-deadman.timer
fi

run systemctl daemon-reload
run systemctl enable agos-core agos-web agos-hooks
run systemctl enable --now agos-deadman.timer
# Core API as the AGOS user (its internal token stays in its data folder, and reaches
# curl through a pipe, never its command line: other users can read argv in ps).
core_api() { # core_api METHOD PATH [body on stdin when a 3rd argument is given]
  sudo -u "$AGOS_USER" -H bash -c 'curl -fsS -m 300 -X "$2" -H @<(printf "x-agos-internal: %s\n" "$(cat "$1")") -H "content-type: application/json" ${4:+--data-binary @-} "http://127.0.0.1:8766$3"' \
    _ "$DATA_DIR/system/internal.token" "$1" "$2" "${3:-}"
}
if [[ "$START" == 1 ]]; then
  say "Starting AGOS"
  run systemctl restart agos-core agos-hooks agos-web
  if [[ "$DRY_RUN" != 1 ]]; then
    for _ in $(seq 1 120); do curl -fsS -m 3 -o /dev/null http://127.0.0.1:8766/health 2>/dev/null && break; sleep 2; done
    curl -fsS -m 3 -o /dev/null http://127.0.0.1:8766/health || die "The core did not start: journalctl -u agos-core -n 50"
    for _ in $(seq 1 60); do curl -fsS -m 5 -o /dev/null http://127.0.0.1:3000/ 2>/dev/null && break; sleep 2; done
    ok "AGOS is running"

    say "Model provider"
    case "$PROVIDER" in
      skip) echo "  Skipped. Add one later in AGOS: Settings -> Models." ;;
      hermes)
        # Hermes's own picker (provider, key or sign-in, default model). It talks to
        # the terminal directly, so nothing typed there lands in the install log.
        if [[ -r /dev/tty ]]; then
          # shellcheck disable=SC2024  # the terminal itself, on purpose
          sudo -u "$AGOS_USER" -H "$HERMES" model </dev/tty >/dev/tty 2>&1 \
            || warn "Hermes's model setup did not finish: do it later in Settings -> Models."
        else
          warn "No keyboard here: add the provider in Settings -> Models."
        fi ;;
      *)
        # The same call as Settings -> Models: Hermes tests the key, then keeps it.
        if [[ -s "$KEY_FILE" ]]; then
          if jq -Rs '{key: .}' < "$KEY_FILE" | core_api PUT "/models/providers/$PROVIDER/key" json >/dev/null 2>&1; then
            ok "$PROVIDER key saved in Hermes (every workspace can use it)"
          else
            warn "Hermes did not accept the $PROVIDER key: add it in Settings -> Models."
          fi
        else
          echo "  No key given: add it later in Settings -> Models."
        fi ;;
    esac
    [[ -z "$KEY_FILE" ]] || rm -f "$KEY_FILE"

    say "Voice notes: $VOICE"
    # Settings -> General -> Voice notes writes the same thing through the core.
    if printf '{"provider":"%s","model":""}' "$VOICE" | core_api PUT /preferences/hermes-voice json >/dev/null 2>&1; then
      ok "voice notes: $VOICE"
    else
      warn "voice notes not set: pick them in Settings -> General -> Voice notes."
    fi
  fi
else
  echo "  Services set up, not started (--no-start). Start them with: agos start"
fi

if [[ "$REMOTE" == yes ]]; then
  say "Tailscale (use AGOS from your other devices)"
  command -v tailscale >/dev/null || run bash -c "curl -fsSL https://tailscale.com/install.sh | sh"
  run systemctl enable --now tailscaled
  # AGOS itself turns Tailscale on and shares itself later, without sudo.
  run tailscale set --operator="$AGOS_USER"
  echo "  To finish: open AGOS -> Settings -> Access (sign in to Tailscale, scan the code with your phone)."
fi

if [[ "$SERVER" == 1 ]]; then
  say "Always-on machine: never sleep (the screen still locks), firewall, security updates"
  run systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  run bash -c "mkdir -p /etc/systemd/logind.conf.d && printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nIdleAction=ignore\n' > /etc/systemd/logind.conf.d/agos.conf"
  # GNOME: lock after 5 min idle, never suspend (applies to any desktop session).
  run bash -c "mkdir -p /etc/dconf/db/local.d && printf \"[org/gnome/desktop/session]\nidle-delay=uint32 300\n[org/gnome/desktop/screensaver]\nlock-enabled=true\nlock-delay=uint32 0\n[org/gnome/settings-daemon/plugins/power]\nsleep-inactive-ac-type='nothing'\nsleep-inactive-battery-type='nothing'\n\" > /etc/dconf/db/local.d/00-agos && (command -v dconf >/dev/null && dconf update || true)"
  run "${APT[@]}" ufw unattended-upgrades
  run ufw default deny incoming
  run ufw default allow outgoing
  if command -v tailscale >/dev/null; then run ufw allow in on tailscale0; fi
  run ufw --force enable
  run dpkg-reconfigure -f noninteractive unattended-upgrades
fi

check
cat <<EOF

AGOS is installed.
  Open:     http://localhost:3000   (or: agos open)
  Manage:   agos status | logs | update | backup | stop | start | uninstall
  Help:     docs/INSTALL.md
EOF
