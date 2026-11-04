#!/usr/bin/env bash
# agos staging: a second AGOS on this machine, on a copy of this one's data, for
# trying a release before it reaches the real one. Quiet by design: its Hermes
# cron jobs are paused, no Kanban dispatcher works its copied cards
# (kanban.dispatch_in_gateway=false in every root and member), AGOS's automation and
# channel loops are off, no phone push, and it has no keys (a backup holds none), so
# no Telegram bot runs in it (and so no Hermes session heartbeat has a chat to fire in).
#
#   agos staging up [--ref <git ref>]       build it (first time) and start it; the
#                                          first time it also takes the data (refresh)
#   agos staging refresh [--ref <git ref>]  the newest live backup -> staging's data
#                                          (staging's own data is replaced)
#   agos staging status
#   agos staging down [--purge]             stop it, its gateways no longer start at
#                                          boot (--purge: remove it all, its sandboxes too)
#
# Everything lives in <agos home>/agos-staging (app = a git worktree of this
# install's checkout, data, backups), its units are agos-staging-{core,hooks,web}
# (not started at boot), its config /etc/agos/staging.conf. Ports: web 3100, core
# 8866, hooks 8867, webhooks from 9100 (AGOS_STAGING_*_PORT). Its Hermes roots are
# named stg-<workspace> and its sandboxes use their own networks and egress proxy
# (agos-stg-egress), so nothing of live's is touched. It shares Hermes's install
# and shared home (provider logins) with live: change logins in live only.
# Promote = `agos update` on live to the same commit.
set -euo pipefail

CONF="${AGOS_CONF:-/etc/agos/agos.conf}"
[[ -r "$CONF" ]] || { echo "AGOS is not installed here ($CONF is missing)." >&2; exit 1; }
# shellcheck disable=SC1090
. "$CONF"
: "${AGOS_USER:?}" "${AGOS_HOME:?}" "${AGOS_APP:?}" "${AGOS_DATA_DIR:?}"
AGOS_BACKUP_DIR="${AGOS_BACKUP_DIR:-$(dirname "$AGOS_DATA_DIR")/agos-backups}"
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
ME="$(id -un)"

BASE="${AGOS_STAGING_DIR:-$AGOS_HOME/agos-staging}"
APP="$BASE/app"
DATA="$BASE/data"
BACKUPS="$BASE/backups"
UNIT_DIR="${AGOS_UNIT_DIR:-/etc/systemd/system}"
STG_CONF="${AGOS_STAGING_CONF:-/etc/agos/staging.conf}"
CORE_PORT="${AGOS_STAGING_CORE_PORT:-8866}"
WEB_PORT="${AGOS_STAGING_WEB_PORT:-3100}"
HOOKS_PORT="${AGOS_STAGING_HOOKS_PORT:-8867}"
WEBHOOK_PORT="${AGOS_STAGING_WEBHOOK_PORT:-9100}"
LIVE_PREFIX="${AGOS_PROFILE_PREFIX:-agos-}"
PREFIX=stg-
EGRESS=agos-stg-egress
# Staging's own sandbox broker (engine/sandbox_broker.py): live's is agos-sandboxd.
BROKER=agos-stg-sandboxd.service
UNITS=(agos-staging-core agos-staging-hooks agos-staging-web)
HERMES="$AGOS_HOME/.local/bin/hermes"
UV="$AGOS_HOME/.local/bin/uv"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '==> %s\n' "$*"; }
as_agos() {
  if [[ "$ME" == "$AGOS_USER" ]]; then "$@"
  else runuser -u "$AGOS_USER" -- env HOME="$AGOS_HOME" "$@"
  fi
}
user_systemctl() { as_agos env XDG_RUNTIME_DIR="/run/user/$(id -u "$AGOS_USER")" systemctl --user "$@"; }
# The staging copy's gateways: Hermes's user services whose home is under its data.
# grep reads all of `systemctl cat` (never -q): under pipefail an early exit kills
# systemctl with SIGPIPE and the pipeline reads as no match.
staging_gateways() {
  local u
  for u in $(user_systemctl list-units --type=service --state=running --no-legend --plain 'hermes-gateway*' 2>/dev/null | awk '{print $1}'); do
    user_systemctl cat "$u" 2>/dev/null | grep -F "$DATA/hermes/" >/dev/null && echo "$u"
  done
  return 0
}
need_root() {
  [[ "$UNIT_DIR" != /etc/systemd/system || $EUID -eq 0 ]] && return 0
  # sudo drops the environment: the backup's password (AGOS_BACKUP_PASSWORD) is the
  # one name kept, so a scripted refresh still opens the backup.
  exec sudo --preserve-env=AGOS_BACKUP_PASSWORD -- bash "$SELF" "$@"
}
# All of staging's gateways (running or not): Hermes's user services whose home is
# under staging's data.
staging_gateway_units() {
  local u
  for u in $(user_systemctl list-unit-files --type=service --no-legend --plain 'hermes-gateway*' 2>/dev/null | awk '{print $1}'); do
    user_systemctl cat "$u" 2>/dev/null | grep -F "$DATA/hermes/" >/dev/null && echo "$u"
  done
  return 0
}

stop_all() {
  local gw; gw="$(staging_gateways | tr '\n' ' ')"
  # shellcheck disable=SC2086
  [[ -z "$gw" ]] || user_systemctl stop $gw || true
  systemctl stop "${UNITS[@]}" 2>/dev/null || true
}

app_at() { # app_at [ref]: the staging checkout (a worktree of live's), at ref
  local ref="${1:-}"
  if [[ ! -e "$APP/.git" ]]; then
    say "A checkout for staging ($APP)"
    as_agos mkdir -p "$BASE"
    as_agos git -C "$AGOS_APP" worktree add -q --detach "$APP" "${ref:-HEAD}"
  elif [[ -n "$ref" ]]; then
    as_agos git -C "$APP" fetch -q origin "$ref" 2>/dev/null || true
    as_agos git -C "$APP" checkout -q --detach "$(as_agos git -C "$APP" rev-parse -q --verify FETCH_HEAD 2>/dev/null || echo "$ref")"
  fi
}

build() {
  [[ "${AGOS_STAGING_NO_BUILD:-0}" == 1 ]] && return 0
  say "Building staging ($(as_agos git -C "$APP" rev-parse --short=12 HEAD))"
  as_agos bash -c 'cd "$1" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=1 pnpm install --frozen-lockfile && pnpm --filter @agos/web build && cd services/core && "$2" sync --frozen' _ "$APP" "$UV"
}

# The live install's paths, roots, network and proxy names in the staging roots
# (settings, member profiles, cron jobs, Kanban boards) become staging's own
# (deploy/staging-own-paths.py, literal text; the staging core re-syncs every
# sandbox at start too), so a staging sandbox or card can never use live's files.
own_paths() {
  as_agos python3 "$HERE/staging-own-paths.py" fix "$DATA/hermes" "$AGOS_DATA_DIR" "$DATA" "$LIVE_PREFIX" "$PREFIX" "$EGRESS" &&
    as_agos python3 "$HERE/staging-own-paths.py" check "$DATA/hermes" "$AGOS_DATA_DIR"
}
# No Kanban dispatcher in any staging root or member: copied cards would be worked
# with the provider logins staging shares with live. Hermes's own setting, written by
# Hermes; the staging core keeps it off too (actions/agent_profiles.kanban_pairs).
no_dispatcher() {
  local home
  while IFS= read -r -d '' home; do
    home="$(dirname "$home")"
    as_agos env HERMES_HOME="$home" "$HERMES" config set kanban.dispatch_in_gateway false >/dev/null || return 1
  done < <(find "$DATA/hermes" -maxdepth 4 -name config.yaml -not -path '*/installs/*' -print0 2>/dev/null)
}
# Staging's data must be its own folder: never live's, inside it, or holding it.
data_is_its_own() {
  local d l
  d="$(readlink -m "$DATA")"; l="$(readlink -m "$AGOS_DATA_DIR")"
  [[ "$d" != "$l" && "$d/" != "$l/"* && "$l/" != "$d/"* ]]
}

refresh() {
  local newest stamp tmp
  newest="$(find "$AGOS_BACKUP_DIR" -maxdepth 1 -name 'agos-backup-*.agosb' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
  [[ -n "$newest" ]] || die "No backup of AGOS yet: run agos backup first (staging is a copy of the newest one)."
  [[ -t 0 || -n "${AGOS_BACKUP_PASSWORD:-}" ]] || die "Run this in a terminal (it asks the backup's password) or set AGOS_BACKUP_PASSWORD."
  say "Staging gets the data of $(basename "$newest")"
  data_is_its_own || die "Staging's data ($DATA) would be live's data ($AGOS_DATA_DIR) or inside it: refusing."
  stop_all
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$BASE/restore-$stamp"
  as_agos mkdir -p "$BASE"
  # The decrypted copy is private (0700) and never outlives this refresh, failed or not.
  as_agos mkdir -m 700 "$tmp"
  RESTORE_TMP="$tmp"; trap 'rm -rf "${RESTORE_TMP:-}"' EXIT
  # The password (asked, or AGOS_BACKUP_PASSWORD) never goes on a command line:
  # runuser keeps the environment.
  (cd "$AGOS_APP/services/core" && as_agos "$UV" run --frozen python scripts/restore_and_verify.py "$newest" "$tmp") \
    || die "The backup could not be opened or is incomplete; staging was not changed."
  [[ -d "$tmp/agos-data" ]] || die "$tmp is not a restored backup."
  # Staging's data is disposable: the old copy goes (live's is never touched).
  rm -rf "$DATA"
  as_agos mkdir -m 700 -p "$DATA" "$BACKUPS"
  as_agos cp -a "$tmp/agos-data/." "$DATA/"
  # Each root by Hermes's own import, under staging's own names. The shared home's
  # backup (hermes/hermes-backup.zip) is live's ~/.hermes: never imported here.
  as_agos env AGOS_ROOT_RENAME="$LIVE_PREFIX:$PREFIX" HERMES_BIN="$HERMES" \
    bash "$HERE/import-roots.sh" "$tmp" "$DATA/hermes" || die "The workspaces' Hermes roots could not be imported."
  own_paths || die "A staging root still names live's data (above); staging was not started."
  no_dispatcher || die "Hermes's Kanban dispatcher could not be turned off in the staging roots; staging was not started."
  rm -rf "$tmp"
  chmod 700 "$DATA"
  say "Staging data ready ($DATA)"
}

write_units() {
  local uid; uid="$(id -u "$AGOS_USER")"
  # The same limits as live's units (install-server.sh, scaled to RAM): a runaway
  # staging copy must not take the machine (its gateways get engine/unit_limits.py's
  # drop-ins from the staging core, like live's). Overridable with the same names.
  local total_mb core_max core_high web_max hooks_max
  total_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  clamp_mb() { local v=$(( total_mb / $1 )); (( v < $2 )) && v=$2; (( v > $3 )) && v=$3; echo "$v"; }
  core_max="${AGOS_CORE_MEMORY_MAX:-$(clamp_mb 4 1024 3072)M}"
  core_high="${AGOS_CORE_MEMORY_HIGH:-$(clamp_mb 6 768 2048)M}"
  web_max="${AGOS_WEB_MEMORY_MAX:-$(clamp_mb 8 512 1024)M}"
  hooks_max="${AGOS_HOOKS_MEMORY_MAX:-256M}"
  mkdir -p "$(dirname "$STG_CONF")" "$UNIT_DIR"
  # Its own config: AGOS_LOCAL_REPO makes the staging core's Update button refuse
  # (staging moves with `agos staging refresh --ref`, never by itself).
  cat > "$STG_CONF" <<EOF
AGOS_USER=$AGOS_USER
AGOS_HOME=$AGOS_HOME
AGOS_APP=$APP
AGOS_DATA_DIR=$DATA
AGOS_BACKUP_DIR=$BACKUPS
AGOS_LOCAL_REPO=$APP
AGOS_STAGING=1
EOF
  cat > "$UNIT_DIR/agos-staging-core.service" <<EOF
[Unit]
Description=AGOS staging core (quiet copy)
After=network-online.target docker.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/services/core
Environment=AGOS_ENGINE=hermes
Environment=AGOS_STAGING=1
Environment=AGOS_CONF=$STG_CONF
Environment=AGOS_DATA_DIR=$DATA
Environment=AGOS_BACKUP_DIR=$BACKUPS
Environment=AGOS_APP_DIR=$APP
Environment=AGOS_PROFILE_PREFIX=$PREFIX
Environment=AGOS_EGRESS_NAME=$EGRESS
Environment=AGOS_SANDBOXD_UNIT=$BROKER
Environment=AGOS_SANDBOXD_RUN_DIR=/run/user/$uid/agos-sandboxd/stg
Environment=AGOS_HOOKS_PORT=$HOOKS_PORT
Environment=AGOS_WEBHOOK_FIRST_PORT=$WEBHOOK_PORT
Environment=PATH=$AGOS_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=AGOS_HERMES_BIN=$HERMES
Environment=XDG_RUNTIME_DIR=/run/user/$uid
Environment=LANG=C.UTF-8
ExecStart=$UV run --frozen uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port $CORE_PORT
Restart=on-failure
RestartSec=5
KillMode=process
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
MemoryAccounting=yes
MemoryHigh=$core_high
MemoryMax=$core_max
TasksMax=512
ProtectProc=invisible
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
EOF
  cat > "$UNIT_DIR/agos-staging-hooks.service" <<EOF
[Unit]
Description=AGOS staging webhook relay
After=agos-staging-core.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/services/core
Environment=AGOS_DATA_DIR=$DATA
Environment=AGOS_HOOKS_PORT=$HOOKS_PORT
Environment=PATH=$AGOS_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$UV run --frozen python -m agos_core.hook_relay
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
MemoryAccounting=yes
MemoryMax=$hooks_max
TasksMax=64
InaccessiblePaths=-/run/docker.sock
ProtectProc=invisible
ProcSubset=pid
PrivateDevices=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
CapabilityBoundingSet=
EOF
  cat > "$UNIT_DIR/agos-staging-web.service" <<EOF
[Unit]
Description=AGOS staging web
After=agos-staging-core.service

[Service]
User=$AGOS_USER
WorkingDirectory=$APP/apps/web
Environment=NODE_ENV=production
Environment=AGOS_CORE_URL=http://127.0.0.1:$CORE_PORT
Environment=AGOS_INTERNAL_TOKEN_FILE=$DATA/system/internal.token
ExecStart=/usr/bin/env pnpm exec next start -H 127.0.0.1 -p $WEB_PORT
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=yes
MemoryAccounting=yes
MemoryMax=$web_max
TasksMax=256
InaccessiblePaths=-/run/docker.sock
ProtectProc=invisible
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
EOF
  [[ "$UNIT_DIR" != /etc/systemd/system ]] || systemctl daemon-reload
}

wait_up() {
  local _ tries="${AGOS_WAIT_TRIES:-120}" pause="${AGOS_WAIT_SLEEP:-2}"
  for _ in $(seq 1 "$tries"); do curl -fsS -m 3 -o /dev/null "http://127.0.0.1:$CORE_PORT/health" 2>/dev/null && break; sleep "$pause"; done
  for _ in $(seq 1 "$tries"); do curl -fsS -m 5 -o /dev/null "http://localhost:$WEB_PORT/" 2>/dev/null && return 0; sleep "$pause"; done
  return 1
}

cmd_up() {
  local ref="" fresh=0
  [[ "${1:-}" == --ref ]] && ref="${2:?usage: agos staging up --ref <git ref>}"
  need_root up "$@"
  [[ -e "$APP/.git" ]] || fresh=1
  app_at "$ref"
  [[ "$fresh" == 1 || -n "$ref" ]] && build
  [[ -e "$DATA/system/agos.db" ]] || refresh
  write_units
  [[ "${AGOS_STAGING_NO_START:-0}" == 1 ]] && { echo "Staging is set up (not started)."; return 0; }
  say "Starting staging"
  systemctl start "${UNITS[@]}"
  wait_up || die "Staging is not answering: journalctl -u agos-staging-core"
  echo "Staging runs: http://localhost:$WEB_PORT (quiet: no automations, no Telegram, no phone push)."
}

cmd_refresh() {
  local ref=""
  [[ "${1:-}" == --ref ]] && ref="${2:?usage: agos staging refresh --ref <git ref>}"
  need_root refresh "$@"
  [[ -e "$APP/.git" ]] || die "No staging yet: agos staging up"
  if [[ -n "$ref" ]]; then app_at "$ref"; build; fi
  refresh
  write_units
  [[ "${AGOS_STAGING_NO_START:-0}" == 1 ]] && return 0
  systemctl start "${UNITS[@]}"
  wait_up || die "Staging is not answering: journalctl -u agos-staging-core"
  echo "Staging runs on the newest backup: http://localhost:$WEB_PORT"
}

cmd_status() {
  local u
  if [[ ! -e "$APP/.git" ]]; then echo "No staging copy (agos staging up makes one)."; return 0; fi
  for u in "${UNITS[@]}"; do printf '  %-19s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || true)"; done
  printf '  release             %s\n' "$(as_agos git -C "$APP" log -1 --format='%h %s' 2>/dev/null | cut -c1-70)"
  printf '  gateways            %s running\n' "$(staging_gateways | wc -l)"
  echo "  web                 http://localhost:$WEB_PORT"
  echo "  data                $DATA"
  echo "  quiet               cron jobs paused, no automations, no Telegram, no phone push"
}

cmd_down() {
  local purge=0
  [[ "${1:-}" == --purge ]] && purge=1
  need_root down "$@"
  say "Stopping staging"
  stop_all
  # Its gateways stay off after a reboot too (Hermes's install enables them).
  local u gw
  gw="$(staging_gateway_units | tr '\n' ' ')"
  if [[ -n "$gw" ]]; then
    # shellcheck disable=SC2086
    user_systemctl disable --now $gw 2>/dev/null || true
  fi
  user_systemctl disable --now "$BROKER" 2>/dev/null || true
  [[ "$purge" == 1 ]] || { echo "Staging is stopped (its data stays: agos staging down --purge removes it)."; return 0; }
  # Its gateways' unit files, sandboxes, proxy and networks, then its folder and
  # units. Live is never touched.
  for u in $gw "$BROKER"; do as_agos rm -f "$AGOS_HOME/.config/systemd/user/$u"; done
  user_systemctl daemon-reload 2>/dev/null || true
  local ids=() line
  # Staging's sandboxes: Hermes labels each with its profile's container key, which
  # starts with staging's prefix (stg-...). They hold its networks, so they go first.
  while IFS= read -r line; do
    [[ "${line#* }" == "$PREFIX"* ]] && ids+=("${line%% *}")
  done < <(docker ps -a --filter label=hermes-agent=1 --format '{{.ID}} {{.Label "hermes-profile"}}' 2>/dev/null || true)
  [[ ${#ids[@]} -eq 0 ]] || docker rm -f "${ids[@]}" >/dev/null || true
  ids=()
  mapfile -t ids < <(docker ps -aq --filter "name=$EGRESS" 2>/dev/null || true)
  [[ ${#ids[@]} -eq 0 ]] || docker rm -f "${ids[@]}" >/dev/null || true
  mapfile -t ids < <(docker network ls -q --filter "name=agos-net-$PREFIX" 2>/dev/null || true)
  [[ ${#ids[@]} -eq 0 ]] || docker network rm "${ids[@]}" >/dev/null || true
  as_agos git -C "$AGOS_APP" worktree remove --force "$APP" 2>/dev/null || true
  rm -rf "$BASE"
  rm -f "$UNIT_DIR"/agos-staging-{core,hooks,web}.service "$STG_CONF"
  [[ "$UNIT_DIR" != /etc/systemd/system ]] || systemctl daemon-reload
  echo "Staging is removed."
}

cmd="${1:-status}"; shift || true
case "$cmd" in
  up) cmd_up "$@" ;;
  refresh) cmd_refresh "$@" ;;
  status) cmd_status ;;
  down) cmd_down "$@" ;;
  *) die "usage: agos staging up|refresh|status|down" ;;
esac
