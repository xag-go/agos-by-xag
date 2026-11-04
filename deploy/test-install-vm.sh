#!/usr/bin/env bash
# End-to-end test of the Linux install in a throwaway Ubuntu 24.04 virtual machine
# (QEMU + KVM, no root needed on this machine: only access to /dev/kvm). The VM
# runs real systemd, Docker and Landlock, as a user's machine does.
#
# It publishes THIS checkout's committed HEAD as a git repository over HTTP (the
# stand-in for GitHub), runs `curl .../install.sh | bash -s -- --yes` in the VM,
# then checks the services, the web, the core, the agos command, a second
# install, `agos update` (a good release, a broken one that must roll back, and
# the Settings button's path through the core) and `agos uninstall`.
#
#   deploy/test-install-vm.sh all        everything, then the VM is shut down (disk kept)
#   deploy/test-install-vm.sh up | install | check | update | uninstall | purge | ssh | down | delete
#
# down shuts the VM down and keeps its disk; AGOS_VM_KEEP_DISK=1 ... up boots that
# same VM again (the web: ssh -i $DIR/key -p 2232 -L 3300:127.0.0.1:3000 tester@127.0.0.1,
# then http://localhost:3300). delete removes the disk.
#
# AGOS_VM_DIR (default ~/.cache/agos-test-vm), AGOS_VM_MEMORY (MB, 5120),
# AGOS_VM_CPUS (4), AGOS_VM_SSH_PORT (2232), AGOS_VM_HTTP_PORT (8799).
# Ports are on 127.0.0.1 only and never AGOS's own (3000/8766/8767).
# [ok]/[FAIL] lines: "A && echo ok || fail" is a plain if/else here; the VM-side
# scripts are single-quoted on purpose (they expand in the VM).
# shellcheck disable=SC2015,SC2016
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${AGOS_VM_DIR:-$HOME/.cache/agos-test-vm}"
MEM="${AGOS_VM_MEMORY:-5120}"
CPUS="${AGOS_VM_CPUS:-4}"
SSH_PORT="${AGOS_VM_SSH_PORT:-2232}"
HTTP_PORT="${AGOS_VM_HTTP_PORT:-8799}"
IMG_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
REPO_URL="http://10.0.2.2:$HTTP_PORT/agos.git"   # the host, as the VM sees it
mkdir -p "$DIR/www"

vm() { ssh -q -i "$DIR/key" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 -o ServerAliveInterval=30 tester@127.0.0.1 "$@"; }
log() { printf '\n##### %s\n' "$*"; }

publish() { # this checkout's HEAD as the "public" repository
  rm -rf "$DIR/www/agos.git"
  git clone -q --bare --branch "$BRANCH" "$ROOT" "$DIR/www/agos.git"
  git -C "$DIR/www/agos.git" update-server-info
  cp "$ROOT/install.sh" "$DIR/www/install.sh"
}

up() {
  command -v qemu-system-x86_64 >/dev/null || { echo "qemu-system-x86_64 is needed" >&2; exit 1; }
  [[ -w /dev/kvm ]] || { echo "no access to /dev/kvm" >&2; exit 1; }
  [[ -f "$DIR/base.img" ]] || { log "Downloading Ubuntu 24.04 cloud image"; curl -fL -o "$DIR/base.img.part" "$IMG_URL"; mv "$DIR/base.img.part" "$DIR/base.img"; }
  [[ -f "$DIR/key" ]] || ssh-keygen -q -t ed25519 -N "" -f "$DIR/key"
  if [[ "${AGOS_VM_KEEP_DISK:-0}" == 1 && -f "$DIR/disk.qcow2" ]]; then
    log "Reusing the VM's disk (AGOS_VM_KEEP_DISK=1): the installer skips finished steps"
  else
    rm -f "$DIR/disk.qcow2"
    qemu-img create -q -f qcow2 -F qcow2 -b "$DIR/base.img" "$DIR/disk.qcow2" 60G
  fi
  mkdir -p "$DIR/www/seed"
  cat > "$DIR/www/seed/user-data" <<EOF
#cloud-config
hostname: agos-test
users:
  - name: tester
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: ["$(cat "$DIR/key.pub")"]
swap: {filename: /swapfile, size: 4G}
package_update: false
EOF
  [[ "${AGOS_VM_KEEP_DISK:-0}" == 1 && -f "$DIR/www/seed/meta-data" ]] ||
    printf 'instance-id: agos-test-%s\nlocal-hostname: agos-test\n' "$(date +%s)" > "$DIR/www/seed/meta-data"
  publish
  if ! [[ -f "$DIR/http.pid" ]] || ! kill -0 "$(cat "$DIR/http.pid")" 2>/dev/null; then
    (cd "$DIR/www" && exec python3 -m http.server "$HTTP_PORT" --bind 127.0.0.1 >"$DIR/http.log" 2>&1) &
    echo $! > "$DIR/http.pid"
  fi
  log "Starting the VM ($CPUS CPUs, $MEM MB)"
  qemu-system-x86_64 -enable-kvm -cpu host -smp "$CPUS" -m "$MEM" -name agos-test \
    -drive "file=$DIR/disk.qcow2,if=virtio" \
    -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22" \
    -smbios "type=1,serial=ds=nocloud;s=http://10.0.2.2:$HTTP_PORT/seed/" \
    -display none -serial "file:$DIR/console.log" -daemonize -pidfile "$DIR/qemu.pid"
  for _ in $(seq 1 90); do vm true 2>/dev/null && break; sleep 5; done
  vm 'cloud-init status --wait >/dev/null 2>&1; uname -r; free -m | head -2; cat /sys/kernel/security/lsm; echo'
}

install() { # the public one-liner, unattended, with a fake provider key
  log "install.sh through curl | bash (unattended)"
  vm "curl -fsSL http://10.0.2.2:$HTTP_PORT/install.sh | AGOS_REPO_URL=$REPO_URL AGOS_REF=$BRANCH AGOS_PROVIDER=openrouter AGOS_PROVIDER_KEY=sk-or-fake-key-for-the-test bash -s -- --yes ${*:-}"
}

check() {
  log "Checks"
  vm 'bash -s' <<'EOF'
set -uo pipefail
FAIL=0
ok() { echo "  [ok]   $*"; }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
for s in docker agos-core agos-web agos-hooks; do
  systemctl is-active --quiet "$s" && ok "$s running" || bad "$s not running"
  systemctl is-enabled --quiet "$s" && ok "$s starts at boot" || bad "$s not enabled"
done
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/); [[ "$code" == 200 ]] && ok "web 200" || bad "web answered $code"
curl -fsS http://127.0.0.1:8766/health | grep -q ok && ok "core /health ok" || bad "core /health"
home=$(curl -fsS -m 60 http://127.0.0.1:3000/)
grep -q "Create your first workspace" <<<"$home" && ok "empty home: Create your first workspace" || bad "home page without 'Create your first workspace'"
grep -q "AGOS by XAG" <<<"$home" && ok "empty home: AGOS by XAG" || bad "home page without 'AGOS by XAG'"
access=$(curl -sS -m 60 -w '\n%{http_code}' http://127.0.0.1:3000/settings/access)
[[ "${access##*$'\n'}" == 200 ]] && grep -q "Tailscale" <<<"$access" && ok "Settings -> Access loads (Tailscale card)" || bad "Settings -> Access: ${access##*$'\n'}"
# The installer set the cage up (deploy/cage-setup.sh): required by default, and it works.
doc="$(sudo agos doctor 2>&1)"
grep -e '- mode: required' <<<"$doc" >/dev/null && grep -e '- cage: ok' <<<"$doc" >/dev/null \
  && grep -e 'cage self-test (bwrap as agos): ok' <<<"$doc" >/dev/null \
  && ok "agos doctor: cage required and working (installed by cage-setup.sh)" \
  || { bad "agos doctor: no working required cage"; grep -A8 'Workspace isolation' <<<"$doc"; }
command -v bwrap >/dev/null && ok "bwrap installed" || bad "no bwrap after install"
T=$(sudo cat /home/agos/agos-data/system/internal.token)
n=$(curl -fsS -H "x-agos-internal: $T" http://127.0.0.1:8766/workspaces | jq length); [[ "$n" == 0 ]] && ok "zero workspaces" || bad "$n workspaces"
v=$(curl -fsS -H "x-agos-internal: $T" http://127.0.0.1:8766/preferences/hermes-voice | jq -r .provider); [[ "$v" == off ]] && ok "voice notes off" || bad "voice notes: $v"
sudo grep -q "sk-or-fake" /var/log/agos-install.log && bad "the provider key is in the install log" || ok "no key in the install log"
sudo grep -rq "sk-or-fake" /home/agos/.hermes/.env 2>/dev/null && bad "a refused key was kept" || ok "the refused fake key was not saved"
docker_ok=$(sudo -u agos docker image inspect agos-sandbox:desktop >/dev/null 2>&1 && echo yes || echo no)
[[ "$docker_ok" == yes ]] && ok "sandbox image built" || bad "no sandbox image"
grep -qw landlock /sys/kernel/security/lsm && ok "Landlock on" || bad "no Landlock"
command -v agos >/dev/null && ok "agos on PATH" || bad "agos missing"
echo "--- agos status"; agos status
echo "--- agos version"; agos version
grep -q "^AGOS $(sudo cat /home/agos/agos/VERSION) — commit [0-9a-f]\{12\}" <<<"$(agos version)" && ok "agos version: release + commit" || bad "agos version without the release number"
echo "--- agos stop / start"
sudo -u agos agos stop
for s in agos-core agos-web agos-hooks; do systemctl is-active --quiet "$s" && bad "$s still running after stop"; done
curl -fsS -m 3 -o /dev/null http://127.0.0.1:3000/ 2>/dev/null && bad "web still answers after stop" || ok "agos stop stopped everything"
sudo -u agos agos start && ok "agos start (as the agos user, no password)" || bad "agos start"
agos restart >/dev/null && ok "agos restart (as an admin)" || bad "agos restart"
echo "--- agos backup"
sudo -u agos env AGOS_BACKUP_PASSWORD=test-backup-password agos backup && ok "agos backup" || bad "agos backup"
ls /home/agos/agos-backups 2>/dev/null | grep -q '\.agosb$' || sudo ls /home/agos/agos-backups | grep -q '\.agosb$' && ok "backup file there" || bad "no backup file"
echo "--- agos logs core (5 s)"
timeout 5 sudo -u agos agos logs core | tail -3 || true
echo
[[ $FAIL -eq 0 ]] && echo "CHECKS-OK" || { echo "$FAIL check(s) failed"; exit 1; }
EOF
}

new_release() { # new_release "title" [break]: publish one more commit on top
  local tmp; tmp="$(mktemp -d)"
  git clone -q "$DIR/www/agos.git" "$tmp/r"
  git -C "$tmp/r" -c user.email=t@example.com -c user.name=Test commit -q --allow-empty -m "$1"
  if [[ "${2:-}" == break ]]; then
    printf 'export default function Broken() { return <div>{ }</div> \n' > "$tmp/r/apps/web/src/app/broken-test.tsx"
    printf 'const x: number = "not a number";\nexport { x };\n' > "$tmp/r/apps/web/src/broken-test.ts"
    git -C "$tmp/r" add -A
    git -C "$tmp/r" -c user.email=t@example.com -c user.name=Test commit -q -m "$1 (broken build)"
  fi
  git -C "$tmp/r" push -q origin "HEAD:$BRANCH"
  git -C "$DIR/www/agos.git" update-server-info
  git -C "$tmp/r" rev-parse HEAD
  rm -rf "$tmp"
}

update() {
  local good bad_sha web_sha
  log "agos update: a good release"
  good="$(new_release "Test release 2")"
  vm "agos update --check && agos update --yes" || { echo "UPDATE-FAILED"; return 1; }
  vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD" | grep -q "$good" && echo "  [ok] on $good" || { echo "  [FAIL] not on $good"; return 1; }
  vm "curl -s -o /dev/null -w 'web %{http_code}\n' http://127.0.0.1:3000/"

  log "agos update: a broken release must roll back"
  bad_sha="$(new_release "Test release 3" break)"
  if vm "agos update --yes"; then echo "  [FAIL] a broken release was installed"; return 1; fi
  vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD" | grep -q "$good" && echo "  [ok] rolled back to $good (not $bad_sha)" || { echo "  [FAIL] not rolled back"; return 1; }
  vm "sudo jq -c '{phase, rolled_back, error}' /home/agos/agos-data/system/agos-update.json; curl -s -o /dev/null -w 'web %{http_code}\n' http://127.0.0.1:3000/; curl -fsS http://127.0.0.1:8766/health"

  log "Settings -> Update AGOS: through the core (check, run, follow the progress file)"
  # Replace the broken commit with a good one on top of the last good release.
  local tmp; tmp="$(mktemp -d)"
  git clone -q "$DIR/www/agos.git" "$tmp/r"
  git -C "$tmp/r" reset -q --hard "$good"
  git -C "$tmp/r" -c user.email=t@example.com -c user.name=Test commit -q --allow-empty -m "Test release 4"
  git -C "$tmp/r" push -q -f origin "HEAD:$BRANCH"
  git -C "$DIR/www/agos.git" update-server-info
  web_sha="$(git -C "$tmp/r" rev-parse HEAD)"; rm -rf "$tmp"
  vm 'bash -s' <<'EOF'
set -euo pipefail
T=$(sudo cat /home/agos/agos-data/system/internal.token)
api() { curl -fsS -m 300 -X "$1" -H "x-agos-internal: $T" "http://127.0.0.1:8766$2"; }
api POST /agos-update/check | jq -c '{target, news}'
api POST /agos-update/run | jq -c '{phase}'
for i in $(seq 1 180); do
  sleep 5
  phase=$(curl -fsS -m 5 -H "x-agos-internal: $T" http://127.0.0.1:8766/agos-update 2>/dev/null | jq -r '.state.phase' || echo "(AGOS restarting)")
  [[ "$phase" != "${last:-}" ]] && echo "  $phase" && last="$phase"
  [[ "$phase" == done || "$phase" == failed ]] && break
done
api GET /agos-update | jq -c '{current: .current.sha, phase: .state.phase, error: .state.error}'
EOF
  vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD" | grep -q "$web_sha" && echo "  [ok] the button's update is on $web_sha" || { echo "  [FAIL] the button's update did not land"; return 1; }
  echo "UPDATE-OK"
}

uninstall() {
  log "agos uninstall --keep-data"
  vm 'sudo agos uninstall --keep-data --yes; echo "--- after:";
    for s in agos-core agos-web agos-hooks; do systemctl cat $s >/dev/null 2>&1 && echo "  [FAIL] $s still there"; done
    id agos >/dev/null 2>&1 && echo "  [FAIL] user agos still there" || echo "  [ok] user removed"
    command -v agos >/dev/null && echo "  [FAIL] agos still on PATH" || echo "  [ok] agos command removed"
    sudo test -f /home/agos/agos-data/system/agos.db && echo "  [ok] data kept" || echo "  [FAIL] data gone"
    sudo test -d /home/agos/agos && echo "  [FAIL] program files still there" || echo "  [ok] program files removed"
    curl -s -m 3 -o /dev/null http://127.0.0.1:3000/ && echo "  [FAIL] web still answers" || echo "  [ok] nothing on :3000"'
}

purge() { # agos uninstall --delete-data must leave nothing of AGOS behind
  log "agos uninstall --delete-data: a wrong word removes nothing"
  vm 'printf "delete\n" | script -qec "sudo agos uninstall --delete-data" /dev/null | tail -3
    systemctl is-active --quiet agos-core && sudo test -f /home/agos/agos-data/system/agos.db &&
      echo "  [ok] typing delete (not DELETE) removed nothing" || echo "  [FAIL] a wrong word removed something"'
  log "agos uninstall --delete-data --yes (no typing, still a last backup)"
  vm 'rm -f ~/agos-last-backup-*.agosb; sudo agos uninstall --delete-data --yes; echo "--- after:"; F=0
    b=$(ls ~/agos-last-backup-*.agosb 2>/dev/null | head -1)
    [[ -s "$b" && "$(stat -c %U "$b")" == "$(id -un)" ]] && echo "  [ok] last backup kept outside AGOS: $b ($(du -h "$b" | cut -f1))" || { echo "  [FAIL] no last backup in ~"; F=$((F + 1)); }
    bad() { echo "  [FAIL] $*"; F=$((F + 1)); }
    for s in agos-core agos-web agos-hooks; do systemctl cat $s >/dev/null 2>&1 && bad "$s still there"; done
    id agos >/dev/null 2>&1 && bad "user agos still there"
    [[ -e /home/agos ]] && bad "/home/agos still there: $(sudo ls -A /home/agos | head -5 | tr "\n" " ")"
    [[ -e /etc/agos ]] && bad "/etc/agos still there"
    [[ -e /usr/local/bin/agos || -e /etc/sudoers.d/agos ]] && bad "agos command or sudoers file still there"
    ls /etc/systemd/system | grep -q "^agos" && bad "systemd files: $(ls /etc/systemd/system | grep "^agos")"
    [[ -n "$(sudo docker ps -aq --filter name=agos-)" ]] && bad "agos containers left"
    [[ -n "$(sudo docker network ls -q --filter name=agos-)" ]] && bad "agos networks left"
    sudo docker image ls --format "{{.Repository}}" | grep -q "^agos-sandbox" && bad "sandbox image left"
    curl -s -m 3 -o /dev/null http://127.0.0.1:3000/ && bad "web still answers"
    curl -s -m 3 -o /dev/null http://127.0.0.1:8766/health && bad "core still answers"
    [[ $F -eq 0 ]] && echo "PURGE-OK: nothing of AGOS left" || echo "PURGE-FAILED ($F)"'
}

down() { # shut the VM down cleanly; its disk stays for the next run
  local pid=""
  [[ -f "$DIR/qemu.pid" ]] && pid="$(cat "$DIR/qemu.pid")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    vm 'sudo systemctl poweroff' 2>/dev/null || true
    for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 2; done
    kill "$pid" 2>/dev/null || true
  fi
  [[ -f "$DIR/http.pid" ]] && kill "$(cat "$DIR/http.pid")" 2>/dev/null || true
  rm -f "$DIR/qemu.pid" "$DIR/http.pid"
  echo "VM shut down; its disk stays ($DIR/disk.qcow2). Boot it again: AGOS_VM_KEEP_DISK=1 $0 up"
}

delete() { # the VM's disk too (the downloaded Ubuntu image stays)
  down
  rm -f "$DIR/disk.qcow2"
  echo "VM deleted (the base image stays in $DIR for the next run)."
}

case "${1:-all}" in
  up) up ;;
  install) shift; install "$@" ;;
  check) check ;;
  update) update ;;
  uninstall) uninstall ;;
  purge) purge ;;
  ssh) shift; vm "$@" ;;
  publish) publish ;;
  down) down ;;
  delete) delete ;;
  all)
    trap down EXIT
    up; install; check
    log "Second install (must be safe and quick; turns on Tailscale for other devices)"
    install --remote yes; vm 'tailscale debug prefs 2>/dev/null | jq -r .OperatorUser'
    check; update; uninstall
    echo "ALL-OK" ;;
  *) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 1 ;;
esac
