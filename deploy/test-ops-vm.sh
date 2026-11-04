#!/usr/bin/env bash
# VM proof of the ops tools (rollback, the watch after an update, staging,
# doctor), on the same throwaway Ubuntu VM as deploy/test-install-vm.sh. Its disk
# is always kept (AGOS_VM_KEEP_DISK=1): this script never deletes it.
#
#   deploy/test-ops-vm.sh all       boot (kept disk), install this checkout's HEAD (a
#                                   kept disk's live is updated to it with this
#                                   checkout's agos), run every check below, then shut
#                                   the VM down
#   deploy/test-ops-vm.sh checks    only the checks (the VM is up, AGOS installed)
#
# Checks:
#   1. update to a new release: the snapshot (agos-data/system/update-snapshots,
#      0700; nothing in agos-backups) holds roots.tar (0600, a root's config.yaml,
#      no sessions), /health?deep=1 is ok, the watch runs; agos stop ends the
#      watch (no rollback);
#   2. a release whose background loop dies after start: the watch rolls it back
#      (HEAD back, agos-update.json watch=rolled-back);
#   3. agos rollback --yes after a good update: code and database back, today's
#      kept in update-snapshots/rolled-from-<time>; a second agos rollback is
#      refused and changes nothing;
#   4. agos doctor --bundle: the report, no key, no internal token, no workspace
#      name; written by the owner's own user, readable without sudo;
#   5. the restore test of a backup after live moved on (a new chat): OK;
#   6. agos staging up / status / down / down --purge beside live: its own ports,
#      roots (stg-*), egress proxy and gateways; no staging root file or Kanban
#      board names live's data; no Kanban dispatcher; cron paused; down disables
#      its gateways; --purge leaves no stg-* sandbox; live untouched; staging's
#      caged terminal can't reach live's broker socket, nor live's staging's;
#   7. the internet through the cage: a live gateway restarted caged (bwrap,
#      agos-sandboxd), then Hermes's own terminal tool, behind that gateway's cage
#      and wall, runs curl -sI https://example.com and pip install --user requests
#      in the workspace's sandbox, through the egress proxy; then the bare docker
#      CLI (PATH+HOME only, as Hermes's browser runs it) reaches the filtered socket
#      and Hermes's own browser_navigate https://example.com loads Example Domain;
#   8. the cage is required (audit F9): agos-core has no AGOS_SANDBOXD, agos doctor
#      says "mode: required" and "cage: ok"; then with bwrap moved away a core
#      restart does NOT start a stopped gateway (its drop-in stays caged), the core
#      log, agos doctor and Settings -> Server & backup say cage_refused; bwrap back
#      = the gateway runs caged again.
# shellcheck disable=SC2015,SC2016
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DIR="${AGOS_VM_DIR:-$HOME/.cache/agos-test-vm}"
SSH_PORT="${AGOS_VM_SSH_PORT:-2232}"
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
export AGOS_VM_KEEP_DISK=1
VMT() { bash "$HERE/test-install-vm.sh" "$@"; }
vm() { ssh -q -i "$DIR/key" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 -o ServerAliveInterval=30 tester@127.0.0.1 "$@"; }
log() { printf '\n##### %s\n' "$*"; }
FAIL=0
ok() { echo "  [ok]   $*"; }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

release() { # release "title" [loop-dies]: one more commit on the published branch
  local tmp sha; tmp="$(mktemp -d)"
  git clone -q "$DIR/www/agos.git" "$tmp/r"
  if [[ "${2:-}" == loop-dies ]]; then
    # The core starts and answers /health, then its ops loop dies: deep health 503.
    sed -i 's/^async def run_forever(core: Any) -> None:$/async def run_forever(core: Any) -> None:\n    raise RuntimeError("test: this release breaks after start")/' \
      "$tmp/r/services/core/src/agos_core/actions/ops_watch.py"
    git -C "$tmp/r" add -A
  fi
  git -C "$tmp/r" -c user.email=t@example.com -c user.name=Test commit -q --allow-empty -m "$1"
  git -C "$tmp/r" push -q origin "HEAD:$BRANCH"
  git -C "$DIR/www/agos.git" update-server-info
  sha="$(git -C "$tmp/r" rev-parse HEAD)"; rm -rf "$tmp"; echo "$sha"
}
head_is() { vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD" | grep -q "$1"; }
state() { vm "sudo jq -r '$1' /home/agos/agos-data/system/agos-update.json"; }

to_head() { # a kept disk keeps its older checkout (the installer never moves it): update live to this HEAD with THIS checkout's agos
  local head; head="$(git -C "$ROOT" rev-parse HEAD)"
  head_is "$head" && return 0
  log "Kept disk: live to this checkout's HEAD ${head:0:12} (with this checkout's agos: an older one may not update)"
  scp -q -i "$DIR/key" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    "$ROOT/deploy/agos" tester@127.0.0.1:/tmp/agos-head
  # The installer keeps an existing checkout and its remote: after the upgrade test the
  # disk's checkout still fetches from that test's repository (no $BRANCH there).
  vm "sudo -u agos git -C /home/agos/agos remote set-url origin http://10.0.2.2:${AGOS_VM_HTTP_PORT:-8799}/agos.git"
  vm 'chmod 755 /tmp/agos-head && bash /tmp/agos-head update --yes' | tail -5 || true
  head_is "$head" && ok "live runs $head" || { bad "live is not on this checkout's HEAD"; return 1; }
}

checks() {
  local good bad_sha before
  log "Setup: a workspace and a backup password on live"
  vm 'bash -s' <<'EOF'
T=$(sudo cat /home/agos/agos-data/system/internal.token)
# --fail-with-body: a refused call prints the core's own reason, not only its status.
api() { curl -sS --fail-with-body -m 600 -X "$1" -H "x-agos-internal: $T" -H "content-type: application/json" "http://127.0.0.1:8766$2" ${3:+--data "$3"}; }
# A fresh VM has no workspace: without one there is no Hermes root to snapshot,
# stage or cage, so every root check below would test nothing.
[[ "$(api GET /workspaces | jq length)" -gt 0 ]] ||
  api POST /workspaces '{"name":"Ops Test Shop","defaultModel":{"provider":"openrouter","mode":"api","model":"x/y","effort":"medium"}}' | jq -c '{id}'
api PUT /backups/password '{"password":"test-backup-password"}' >/dev/null
api POST /backups/run | jq -c '{name}'
EOF
  vm 'sudo ls /home/agos/agos-data/hermes' | grep -q '^agos-' && ok "a workspace with its Hermes root" || bad "no workspace root on live"

  log "1. update: roots snapshot, deep health, the watch"
  good="$(release "Ops test release A")"
  vm "agos update --yes" >/dev/null && head_is "$good" && ok "updated to $good" || bad "update to $good"
  # The snapshots folder is 0700 (agos): its globs expand as root, never as the tester.
  vm 'sudo bash -c '"'"'snap=$(ls -d /home/agos/agos-data/system/update-snapshots/update-* | tail -1); stat -c %a "$snap/roots.tar"; tar -tf "$snap/roots.tar"'"'"'' > "$DIR/roots.list" || true
  [[ "$(vm 'sudo stat -c %a /home/agos/agos-data/system/update-snapshots')" == 700 ]] && ok "snapshots folder 0700" || bad "snapshots folder mode"
  vm 'sudo ls -d /home/agos/agos-backups/update-* 2>/dev/null' | grep -q update- && bad "an update snapshot (keys) in the backup folder" || ok "no snapshot in the backup folder"
  head -1 "$DIR/roots.list" | grep -qx 600 && ok "roots.tar is 0600" || bad "roots.tar mode: $(head -1 "$DIR/roots.list")"
  grep -q '^hermes/agos-[^/]*/config.yaml$' "$DIR/roots.list" && ok "roots.tar has a root's config.yaml" || bad "no root config in roots.tar"
  # A sessions folder, not any name with "sessions" in it (agos-guard's bridge_sessions.py).
  grep -qE '^hermes/[^/]+/(profiles/[^/]+/)?sessions(/|$)' "$DIR/roots.list" && bad "roots.tar holds sessions" || ok "no sessions in roots.tar"
  vm 'curl -fsS "http://127.0.0.1:8766/health?deep=1"' | jq -e .ok >/dev/null && ok "deep health ok" || bad "deep health"
  vm 'sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user is-active agos-update-watch' | grep -qx active && ok "watch running" || bad "no watch after the update"
  vm 'agos stop >/dev/null; sleep 3; sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user is-active agos-update-watch; agos start >/dev/null' | grep -qx active \
    && bad "the watch still runs after agos stop" || ok "agos stop ends the watch"
  head_is "$good" && ok "no rollback after agos stop" || bad "agos stop rolled the update back"

  log "2. a release that breaks after start: the watch rolls it back"
  bad_sha="$(release "Ops test release B (loop dies)" loop-dies)"
  vm "agos update --yes" >/dev/null || true
  for _ in $(seq 1 60); do [[ "$(state .watch)" == rolled-back ]] && break; sleep 10; done
  head_is "$good" && ok "back on $good (not $bad_sha)" || bad "not rolled back"
  [[ "$(state .watch)" == rolled-back && "$(state .rolled_back)" == true ]] && ok "agos-update.json: watch rolled-back" || bad "state: $(vm "sudo jq -c . /home/agos/agos-data/system/agos-update.json")"
  vm 'curl -fsS "http://127.0.0.1:8766/health?deep=1"' | jq -e .ok >/dev/null && ok "deep health ok after the rollback" || bad "deep health after the rollback"

  log "3. agos rollback after a good update"
  before="$(vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD")"
  good="$(release "Ops test release C")"
  vm "agos update --yes" >/dev/null && head_is "$good" || bad "update to $good"
  vm "agos rollback --yes" && head_is "$before" && ok "agos rollback: back on $before" || bad "agos rollback"
  vm 'sudo bash -c '"'"'k=$(ls -d /home/agos/agos-data/system/update-snapshots/rolled-from-* | tail -1); test -s "$k/agos.db" && test -s "$k/roots.tar"'"'"'' && ok "today's data kept in rolled-from-<time>" || bad "no rolled-from copy"
  [[ "$(state .phase)" == rolled-back ]] && ok "update card: rolled-back" || bad "phase $(state .phase)"
  vm "agos rollback --yes" && bad "a second rollback ran" || ok "a second rollback is refused"
  head_is "$before" && ok "still on $before after the refused rollback" || bad "HEAD moved"

  log "4. agos doctor --bundle"
  vm 'sudo -u agos agos doctor --bundle /home/agos/d.md >/dev/null && sudo cat /home/agos/d.md' > "$DIR/doctor.md" || true
  grep -q "## AGOS diagnostics" "$DIR/doctor.md" && ok "report written" || bad "no report"
  grep -q "Ops Test Shop" "$DIR/doctor.md" && bad "workspace name in the report" || ok "no workspace name"
  grep -q "$(vm 'sudo cat /home/agos/agos-data/system/internal.token')" "$DIR/doctor.md" && bad "internal token in the report" || ok "no internal token"
  grep -qE 'sk-or-[A-Za-z]' "$DIR/doctor.md" && bad "a key in the report" || ok "no key"
  vm 'rm -f ~/own.md; agos doctor --bundle ~/own.md >/dev/null && test "$(stat -c %U ~/own.md)" = "$(id -un)" && head -1 ~/own.md' | grep -q "## AGOS diagnostics" \
    && ok "the owner's own bundle is his and readable" || bad "doctor --bundle as the owner"

  log "5. the restore test after live moved on"
  vm 'bash -s' <<'EOF' > "$DIR/rehearse.json" || true
T=$(sudo cat /home/agos/agos-data/system/internal.token)
api() { curl -fsS -m 600 -X "$1" -H "x-agos-internal: $T" -H "content-type: application/json" "http://127.0.0.1:8766$2" ${3:+--data "$3"}; }
api POST /backups/run >/dev/null
ws=$(api GET /workspaces | jq -r '.[0].id')
api POST "/workspaces/$ws/chats" '{"title":"after the backup"}' >/dev/null
api POST /backups/rehearse '{}'
EOF
  jq -e .ok "$DIR/rehearse.json" >/dev/null && ok "restore test OK with newer live data" || bad "restore test: $(jq -r .detail "$DIR/rehearse.json" 2>/dev/null)"

  log "6. staging beside live"
  vm 'sudo env AGOS_BACKUP_PASSWORD=test-backup-password agos staging up' && ok "agos staging up" || bad "agos staging up"
  vm 'bash -s' <<'EOF' | tee "$DIR/staging.log"
set -uo pipefail
ok() { echo "  [ok]   $*"; }; bad() { echo "  [FAIL] $*"; }
for s in agos-staging-core agos-staging-web agos-staging-hooks agos-core agos-web; do
  systemctl is-active --quiet "$s" && ok "$s running" || bad "$s not running"
done
curl -fsS "http://127.0.0.1:8866/health?deep=1" | jq -e .ok >/dev/null && ok "staging core answers" || bad "staging core"
[[ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3100/)" == 200 ]] && ok "staging web 200" || bad "staging web"
curl -fsS "http://127.0.0.1:8766/health?deep=1" | jq -e .ok >/dev/null && ok "live core still answers" || bad "live core"
sudo ls /home/agos/agos-staging/data/hermes | grep -q '^stg-' && ok "staging roots are stg-*" || bad "no stg-* root"
for r in $(sudo find /home/agos/agos-staging/data/hermes -mindepth 1 -maxdepth 1 -name 'stg-*' 2>/dev/null); do
  n=$(basename "$r")
  sudo grep -rIl --include=config.yaml --include=profile.yaml --include=jobs.json --exclude-dir=installs --exclude-dir=sessions /home/agos/agos-data "$r" \
    && bad "$n: a settings/profile/cron file names live's data" || ok "$n: no settings/profile/cron file names live's data"
  sudo -u agos python3 /home/agos/agos/deploy/staging-own-paths.py check /home/agos/agos-staging/data/hermes /home/agos/agos-data >/dev/null \
    && ok "$n: no Kanban board names live's data" || bad "$n: a staging file or board names live's data"
  sudo grep -q 'dispatch_in_gateway: true' "$r/config.yaml" && bad "$n: Kanban dispatcher on" || ok "$n: no Kanban dispatcher"
done
sleep 60
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
n=0; for u in $($U list-units --type=service --state=running --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  $U cat "$u" | grep agos-staging/data >/dev/null && n=$((n+1)); done
[[ $n -gt 0 ]] && ok "$n staging gateway(s) on staging roots" || bad "no staging gateway"
# One broker per AGOS: staging's own unit; live's still serves live's policies.
sudo grep -q -- '--policies" "/home/agos/agos-data/sandboxd"' /home/agos/.config/systemd/user/agos-sandboxd.service \
  && ok "live's sandbox broker untouched" || bad "live's sandbox broker was rewritten"
sudo grep -q -- '/home/agos/agos-staging/data/sandboxd' /home/agos/.config/systemd/user/agos-stg-sandboxd.service \
  && ok "staging runs its own sandbox broker" || bad "no staging sandbox broker of its own"
# Review H1: staging's sockets sit inside live's family folder, and every cage
# hides that family whole: a caged terminal reaches only its own broker socket.
AU=$(id -u agos); FAM="/run/user/$AU/agos-sandboxd"
caged_ping() { # caged_ping <gateway unit> <socket>: the broker's _ping answer from that gateway's cage + wall, or DOWN
  local conf="/home/agos/.config/systemd/user/$1.d/agos-runtime.conf" cage envs
  mapfile -t cage < <(sudo grep '^ExecStart=.*wall\.py' "$conf" | sed 's/^ExecStart=//' | python3 -c '
import shlex, sys
a = shlex.split(sys.stdin.read()); last = len(a) - 1 - a[::-1].index("--")
print("\n".join(x.replace("$$", "$").replace("%%", "%") for x in a[: last + 1]))')
  mapfile -t envs < <($U show "$1" -p Environment --value | tr ' ' '\n' | grep '=')
  sudo -u agos env -i HOME=/home/agos USER=agos XDG_RUNTIME_DIR="/run/user/$AU" "${envs[@]}" \
    bash -c 'cd "$HERMES_HOME" && exec "$@"' _ "${cage[@]}" /usr/bin/curl -s -m 5 --unix-socket "$2" http://d/_ping 2>/dev/null || echo DOWN
}
stg_unit=""; live_unit=""
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  body=$($U cat "$u" 2>/dev/null || true)
  [[ -z "$stg_unit" && "$body" == *"HERMES_HOME=/home/agos/agos-staging/data/hermes/"* ]] && stg_unit="$u"
  [[ -z "$live_unit" && "$body" == *"HERMES_HOME=/home/agos/agos-data/hermes/"* ]] && live_unit="$u"
done
live_sock=$(sudo find "$FAM" -mindepth 2 -maxdepth 2 -name docker.sock -path "$FAM/agos-*" 2>/dev/null | head -1)
stg_sock=$(sudo find "$FAM/stg" -mindepth 2 -maxdepth 2 -name docker.sock 2>/dev/null | head -1)
if [[ -z "$stg_unit" || -z "$live_unit" || -z "$live_sock" || -z "$stg_sock" ]]; then
  bad "cross-instance socket check: missing a piece (staging unit '$stg_unit', live unit '$live_unit', live socket '$live_sock', staging socket '$stg_sock')"
else
  [[ "$(sudo -u agos curl -s -m 5 --unix-socket "$live_sock" http://d/_ping)" == OK ]] \
    && ok "live's broker socket answers outside the cages ($live_sock)" || bad "live's broker socket is down: the checks below would prove nothing"
  [[ "$(caged_ping "$stg_unit" "$stg_sock")" == OK ]] && ok "staging's caged terminal reaches its own broker socket" \
    || bad "staging's caged terminal can't reach its own broker socket ($stg_sock)"
  [[ "$(caged_ping "$stg_unit" "$live_sock")" == DOWN ]] && ok "staging's caged terminal can't reach live's broker socket" \
    || bad "staging's caged terminal REACHES live's broker socket ($live_sock)"
  [[ "$(caged_ping "$live_unit" "$stg_sock")" == DOWN ]] && ok "live's caged terminal can't reach staging's broker socket" \
    || bad "live's caged terminal REACHES staging's broker socket ($stg_sock)"
fi
sudo docker ps --format '{{.Names}}' | grep -qx agos-stg-egress && ok "staging egress proxy" || echo "  [--]   no staging egress proxy (no sandbox started yet)"
sudo docker ps --format '{{.Names}}' | grep -qx agos-egress && ok "live egress proxy still there" || echo "  [--]   no live egress proxy"
for f in $(sudo bash -c 'ls /home/agos/agos-staging/data/hermes/stg-*/cron/jobs.json 2>/dev/null'); do
  sudo jq -e '[(.jobs // []) | (if type=="object" then .[] else .[] end) | select(.enabled == true)] | length == 0' "$f" >/dev/null \
    && ok "no enabled cron job in $(basename "$(dirname "$(dirname "$f")")")" || bad "an enabled cron job in $f"
done
agos staging status
EOF
  grep -q FAIL "$DIR/staging.log" && FAIL=$((FAIL + 1))
  vm 'sudo agos staging down' && ok "agos staging down" || bad "staging down"
  vm 'bash -s' <<'EOF' | tee -a "$DIR/staging.log"
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  $U cat "$u" | grep agos-staging/data >/dev/null || continue
  $U is-enabled --quiet "$u" && echo "  [FAIL] $u still starts at boot" || echo "  [ok]   $u disabled"
done
EOF
  grep -q 'FAIL.*starts at boot' "$DIR/staging.log" && FAIL=$((FAIL + 1))
  vm 'sudo agos staging down --purge' && ok "agos staging down --purge" || bad "staging down --purge"
  vm "sudo docker ps -a --filter label=hermes-agent=1 --format '{{.Label \"hermes-profile\"}}'" | grep -q '^stg-' && bad "a staging sandbox left" || ok "no staging sandbox left"
  vm 'systemctl cat agos-staging-core >/dev/null 2>&1' && bad "staging unit still there" || ok "staging units gone"
  vm 'systemctl is-active --quiet agos-core && curl -fsS http://127.0.0.1:8766/health >/dev/null' && ok "live fine after staging down" || bad "live after staging down"

  log "7. agents keep the internet and the browser through the cage"
  vm 'bash -s' <<'EOF' | tee "$DIR/internet.log"
set -uo pipefail
ok() { echo "  [ok]   $*"; }; bad() { echo "  [FAIL] $*"; }
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
unit=""
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  $U cat "$u" | grep 'HERMES_HOME=/home/agos/agos-data/hermes/' >/dev/null && { unit="$u"; break; }
done
[[ -n "$unit" ]] || { bad "no live gateway unit"; exit 0; }
# A gateway takes the cage at its next start (ADR 0025 step 4).
$U restart "$unit"; sleep 15
$U is-active -q "$unit" && ok "$unit running" || bad "$unit not running"
conf="/home/agos/.config/systemd/user/$unit.d/agos-runtime.conf"
sudo grep -q '"bwrap"' "$conf" && ok "$unit: caged (bwrap)" || bad "$unit: not caged"
$U is-active -q agos-sandboxd && ok "agos-sandboxd active" || bad "agos-sandboxd not active"
# The gateway's own cage + wall prefix (everything up to the last "--"), its own
# environment, then Hermes's own terminal tool: the path an agent's command takes.
launcher=$(sudo grep '^ExecStart=.*wall\.py' "$conf" | sed 's/^ExecStart=//')
mapfile -t CAGE < <(python3 - "$launcher" <<'PY'
import shlex, sys
argv = shlex.split(sys.argv[1])
last = len(argv) - 1 - argv[::-1].index("--")
print("\n".join(a.replace("$$", "$").replace("%%", "%") for a in argv[: last + 1]))
PY
)
mapfile -t ENVS < <($U show "$unit" -p Environment --value | tr ' ' '\n' | grep '=')
# Hermes's own runtime command (as engine/hermes.py runs its modules), running this
# probe file instead of a module.
mapfile -t PY < <(sudo -u agos /home/agos/.local/bin/hermes --print-runtime-command --module agos_probe |
  python3 -c '
import json, re, sys
argv = json.load(sys.stdin)
argv[-1] = re.sub(r"runpy\.run_module\(.*\)", "exec(open(\"/tmp/agos-net-probe.py\").read())", argv[-1])
print("\n".join(argv))')
cat > /tmp/agos-net-probe.py <<'PY'
import json, os, socket, sys
os.chdir(os.environ["HERMES_HOME"])
host = os.environ.get("DOCKER_HOST", "")
real = "reachable"
try:
    socket.socket(socket.AF_UNIX).connect("/var/run/docker.sock")
except OSError:
    real = "blocked"
print("CAGE", "filtered" if "agos-sandboxd" in host else "unfiltered:" + host, real)
from hermes_cli.config import apply_terminal_config_to_env
apply_terminal_config_to_env()
from tools.terminal_tool import terminal_tool
COMMANDS = [
    "curl -sI -m 60 https://example.com | grep -i '^HTTP/'",
    "curl -sS -o /dev/null -m 60 -w 'EXAMPLE %{http_code}\\n' https://example.com",
    "pip install --user --no-cache-dir --force-reinstall requests 2>&1 | tail -2 && python3 -c 'import requests; print(\"REQUESTS\", requests.__version__)'",
    "curl -sI -m 20 --noproxy '*' https://example.com >/dev/null && echo DIRECT-OPEN || echo DIRECT-CLOSED",
]
for cmd in COMMANDS:
    out = json.loads(terminal_tool(command=cmd, timeout=600))
    print("CMD", cmd)
    print("EXIT", out.get("exit_code"))
    print(str(out.get("output", "")).strip()[-1200:] or json.dumps(out)[:1200])
# Hermes's sandboxed browser runs `docker exec` with only PATH + HOME (no DOCKER_HOST):
# the cage's ~/.docker context must lead the bare docker CLI to the filtered socket.
import subprocess
bare = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "")}
v = subprocess.run(["docker", "version", "--format", "{{.Server.APIVersion}}"], env=bare,
                   capture_output=True, text=True, timeout=60)
print("BARE-DOCKER rc", v.returncode, (v.stdout or v.stderr).strip()[-200:])
from tools import browser_tool
try:
    nav = browser_tool.browser_navigate("https://example.com", task_id="agos-ops-vm-browser")
    print("NAVIGATE", nav[:800])
    try:
        ok = bool(json.loads(nav).get("success")) and "Example Domain" in nav
    except ValueError:
        ok = False
    print("BROWSER", "OK" if ok else "FAILED")
except Exception as error:  # noqa: BLE001 — the check reports it
    print("BROWSER FAILED", repr(error)[:400])
finally:
    try:
        from tools.browser_tool_lifecycle import cleanup_browser
        cleanup_browser("agos-ops-vm-browser")
    except Exception as error:  # noqa: BLE001
        print("browser cleanup:", repr(error)[:200])
PY
chmod 644 /tmp/agos-net-probe.py
sudo -u agos env -i HOME=/home/agos USER=agos LOGNAME=agos XDG_RUNTIME_DIR="/run/user/$(id -u agos)" "${ENVS[@]}" \
  bash -c 'cd "$HERMES_HOME" && exec "$@"' _ "${CAGE[@]}" "${PY[@]}" > /tmp/agos-net.out 2>&1
sed 's/^/    /' /tmp/agos-net.out | tail -50
grep -q '^CAGE filtered blocked' /tmp/agos-net.out && ok "the probe ran in the cage (filtered Docker socket, real one blocked)" || bad "the probe was not caged"
# The proxy's own "200 Connection established" comes first: example.com's answer is
# curl's http_code of the final response.
grep -q '^EXAMPLE 200' /tmp/agos-net.out && ok "Hermes terminal in the sandbox: curl -sI https://example.com -> 200 (example.com's own)" || bad "no HTTP 200 from example.com"
grep -q '^REQUESTS ' /tmp/agos-net.out && ok "Hermes terminal in the sandbox: pip install --user requests works" || bad "pip install --user requests failed"
grep -q '^DIRECT-CLOSED' /tmp/agos-net.out && ok "no direct route: the traffic goes through the egress proxy" \
  || echo "  [--]   a direct route out of the sandbox is open (not through agos-egress)"
sudo docker ps --format '{{.Names}}' | grep -qx agos-egress && ok "live egress proxy up" || bad "no live egress proxy"
grep -qE '^BARE-DOCKER rc 0 [0-9.]+$' /tmp/agos-net.out && ok "docker CLI with only PATH+HOME reaches the filtered socket (the cage's docker context)" \
  || bad "docker CLI without DOCKER_HOST does not reach the sandbox broker"
grep -q '^BROWSER OK' /tmp/agos-net.out && ok "Hermes browser in the sandbox: browser_navigate https://example.com -> Example Domain" \
  || bad "Hermes browser_navigate https://example.com failed in the cage"
EOF
  grep -q FAIL "$DIR/internet.log" && FAIL=$((FAIL + 1))

  log "8. the cage is required: without bwrap a gateway refuses (cage_refused), never runs uncaged"
  vm 'bash -s' <<'EOF' | tee "$DIR/cage-required.log"
set -uo pipefail
ok() { echo "  [ok]   $*"; }; bad() { echo "  [FAIL] $*"; }
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
T=$(sudo cat /home/agos/agos-data/system/internal.token)
core_up() { for _ in $(seq 1 90); do curl -fsS -m 3 -o /dev/null http://127.0.0.1:8766/health && return 0; sleep 2; done; return 1; }
grep 'AGOS_SANDBOXD=off' <<<"$(systemctl show agos-core -p Environment --value)" >/dev/null \
  && bad "agos-core runs with AGOS_SANDBOXD=off" || ok "agos-core: no AGOS_SANDBOXD (required by default)"
doc="$(sudo agos doctor 2>&1)"
grep -e '- mode: required' <<<"$doc" >/dev/null && grep -e '- cage: ok' <<<"$doc" >/dev/null \
  && ok "agos doctor: mode required, cage ok" || { bad "agos doctor: no working required cage"; grep -A6 'Workspace isolation' <<<"$doc"; }
unit=""
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  $U cat "$u" | grep 'HERMES_HOME=/home/agos/agos-data/hermes/' >/dev/null && { unit="$u"; break; }
done
[[ -n "$unit" ]] || { bad "no live gateway unit"; exit 0; }
conf="/home/agos/.config/systemd/user/$unit.d/agos-runtime.conf"
BW="$(command -v bwrap)"
[[ -n "$BW" ]] || { bad "no bwrap on the VM"; exit 0; }
# Put bwrap back whatever happens below.
trap 'sudo mv "$BW.agos-test-off" "$BW" 2>/dev/null; sudo systemctl restart agos-core' EXIT
$U stop "$unit"
sudo mv "$BW" "$BW.agos-test-off"
since="$(date '+%Y-%m-%d %H:%M:%S')"
sudo systemctl restart agos-core
core_up && ok "core up without bwrap" || bad "core did not come up without bwrap"
sleep 30  # the start pass (actions/idle.py ensure_all) asks for every gateway
$U is-active -q "$unit" && bad "$unit started without bwrap" || ok "$unit refused to start without bwrap"
sudo grep '"bwrap"' "$conf" >/dev/null && ok "its drop-in still cages it (never rewritten uncaged)" || bad "drop-in rewritten without the cage"
# The refusal is an agos.* ERROR: Settings -> Errors (GET /errors) keeps it.
{ curl -fsS -m 30 -H "x-agos-internal: $T" http://127.0.0.1:8766/errors; sudo journalctl -u agos-core --since "$since" --no-pager; } \
  | grep cage_refused >/dev/null && ok "Settings -> Errors: cage_refused" || bad "no cage_refused in Settings -> Errors or the core's log since $since"
grep 'REFUSED (cage_refused)' <<<"$(sudo agos doctor 2>&1)" >/dev/null && ok "agos doctor: cage REFUSED (cage_refused)" || bad "agos doctor does not show the refusal"
curl -fsS -m 30 -H "x-agos-internal: $T" http://127.0.0.1:8766/backups | jq -r '.warnings[]' | grep cage_refused >/dev/null \
  && ok "Settings -> Server & backup: the cage_refused line" || bad "no cage_refused line in Settings -> Server & backup"
sudo mv "$BW.agos-test-off" "$BW"
trap - EXIT
sudo systemctl restart agos-core
core_up || bad "core did not come back with bwrap"
sleep 30
$U is-active -q "$unit" || $U start "$unit"
sleep 10
$U is-active -q "$unit" && sudo grep '"bwrap"' "$conf" >/dev/null && ok "bwrap back: $unit runs caged again" || bad "$unit not running caged after bwrap came back"
EOF
  grep -q FAIL "$DIR/cage-required.log" && FAIL=$((FAIL + 1))

  [[ $FAIL -eq 0 ]] && echo "OPS-OK" || { echo "$FAIL ops check(s) failed"; return 1; }
}

case "${1:-all}" in
  checks) checks ;;
  all)
    trap 'VMT down' EXIT
    VMT up
    VMT install
    to_head
    checks ;;
  *) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 1 ;;
esac
