#!/usr/bin/env bash
# Hardware minimum, measured: the kept test VM (deploy/test-install-vm.sh, disk kept)
# is booted with less memory and fewer CPUs, AGOS's load test (services/core/tests/load)
# runs inside it at a small scale, and the machine's own numbers are recorded: the
# lowest free memory, the swap used, out-of-memory kills, and the test's latencies.
# The results feed docs/INSTALL.md ("Hardware") and the installer's limits
# (deploy/install-server.sh MIN_RAM_MB / WARN_RAM_MB).
#
#   deploy/test-hardware-vm.sh all [MB:CPUS ...]   each size (default 3072:2 4096:2 5120:4),
#                                                  one boot each, then the VM is shut down
#   deploy/test-hardware-vm.sh run                 one run on the VM as it is (it is up)
#
# AGOS_LOAD_WORKSPACES (3), AGOS_LOAD_CARDS (30), AGOS_LOAD_TURNS (6): the load test's scale.
# AGOS_VM_DIR: keep it on the kept disk (~/.hermes/cache/scratch/agos-vm).
# Reports: $AGOS_VM_DIR/hardware-<MB>m-<CPUS>c.{json,log}, and hardware.md (all sizes).
# shellcheck disable=SC2016
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIR="${AGOS_VM_DIR:-$HOME/.cache/agos-test-vm}"
SSH_PORT="${AGOS_VM_SSH_PORT:-2232}"
export AGOS_VM_KEEP_DISK=1
VMT() { bash "$HERE/test-install-vm.sh" "$@"; }
vm() { ssh -q -i "$DIR/key" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 -o ServerAliveInterval=30 tester@127.0.0.1 "$@"; }
log() { printf '\n##### %s\n' "$*"; }

run() { # one measured run on the booted VM; prints one JSON line
  vm "WS=${AGOS_LOAD_WORKSPACES:-3} CARDS=${AGOS_LOAD_CARDS:-30} TURNS=${AGOS_LOAD_TURNS:-6} bash -s" <<'EOF'
set -uo pipefail
sudo test -d /home/agos/agos/services/core/tests/load || {  # agos's home is 0700: sudo
  echo "the VM's AGOS has no tests/load (an older release): run deploy/test-upgrade-vm.sh first, it leaves this checkout's HEAD installed" >&2
  exit 1
}
mem_total=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
cpus=$(nproc)
# What AGOS uses doing nothing: its three services and the web, as installed.
sudo systemctl start agos-core agos-hooks agos-web
for _ in $(seq 1 60); do curl -fsS -m 3 -o /dev/null http://127.0.0.1:3000/ && break; sleep 3; done
sleep 20
idle=$(ps -u agos -o rss= | awk '{s+=$1} END {print int(s/1024)}')
avail_idle=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
# The load test runs its own core (a rig) beside the installed web: the installed
# core stops for it (two cores would count AGOS twice).
sudo systemctl stop agos-core agos-hooks
sudo dmesg -C 2>/dev/null || true
rm -f /tmp/hw-samples
( while :; do
    printf '%s %s\n' "$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)" \
      "$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {print int((t-f)/1024)}' /proc/meminfo)" >> /tmp/hw-samples
    sleep 2
  done ) &
sampler=$!
start=$(date +%s)
sudo -u agos bash -c "cd /home/agos/agos/services/core && rm -rf /home/agos/load-rig && \
  AGOS_E2E=/home/agos/load-rig AGOS_E2E_PORTS=9762,9763,9764 AGOS_LOAD_WORKSPACES=$WS AGOS_LOAD_CARDS=$CARDS \
  AGOS_LOAD_TURNS=$TURNS AGOS_LOAD_OUT=/home/agos/load-out timeout 3600 /home/agos/.local/bin/uv run --frozen \
  pytest tests/load -q -p no:cacheprovider -o addopts= --timeout=3600" > /tmp/hw-load.log 2>&1
rc=$?
secs=$(( $(date +%s) - start ))
kill "$sampler" 2>/dev/null || true
oom=$(sudo dmesg 2>/dev/null | grep -ci 'out of memory\|oom-kill' || true)
report=$(sudo cat /home/agos/load-out/report.json 2>/dev/null || echo '{}')
sudo -u agos bash -c 'rm -rf /home/agos/load-rig'
sudo systemctl start agos-core agos-hooks
tail -5 /tmp/hw-load.log >&2
jq -cn --argjson mem "$mem_total" --argjson cpus "$cpus" --argjson idle "$idle" --argjson avail_idle "$avail_idle" \
  --argjson rc "$rc" --argjson secs "$secs" --argjson oom "$oom" \
  --argjson min_avail "$(sort -n /tmp/hw-samples | head -1 | cut -d' ' -f1)" \
  --argjson max_swap "$(sort -k2 -n /tmp/hw-samples | tail -1 | cut -d' ' -f2)" \
  --argjson report "$report" \
  '{mem_mb: $mem, cpus: $cpus, agos_idle_rss_mb: $idle, avail_idle_mb: $avail_idle, load_rc: $rc,
    load_seconds: $secs, oom_kills: $oom, min_available_mb: $min_avail, max_swap_used_mb: $max_swap,
    chat_answer: ($report.chat_answer // null), page_reads: ($report.page_reads_under_load // null),
    card_create: ($report.card_create // null), rss_peak_total_mb: ($report.rss_peak_total_mb // null),
    rss_per_workspace_mb: ($report.rss_per_workspace_mb // null)}'
EOF
}

table() { # hardware.md from every hardware-*.json
  {
    echo "| RAM | CPUs | load test | OOM kills | lowest free RAM | swap used | chat answer p50 / p95 | page reads p95 | AGOS idle |"
    echo "|---|---|---|---|---|---|---|---|---|"
    for f in "$DIR"/hardware-*.json; do
      jq -r '"| \(.mem_mb) MB | \(.cpus) | \(if .load_rc == 0 then "passed" else "FAILED (rc \(.load_rc))" end) (\(.load_seconds) s) | \(.oom_kills) | \(.min_available_mb) MB | \(.max_swap_used_mb) MB | \(.chat_answer.p50_ms // "-") / \(.chat_answer.p95_ms // "-") ms | \(.page_reads.p95_ms // "-") ms | \(.agos_idle_rss_mb) MB |"' "$f"
    done
  } > "$DIR/hardware.md"
  cat "$DIR/hardware.md"
}

case "${1:-all}" in
  run) run ;;
  table) table ;;
  all)
    shift || true
    sizes=("$@"); [[ ${#sizes[@]} -gt 0 ]] || sizes=(3072:2 4096:2 5120:4)
    for s in "${sizes[@]}"; do
      mb="${s%%:*}"; cpus="${s##*:}"
      log "VM with $mb MB and $cpus CPUs"
      AGOS_VM_MEMORY="$mb" AGOS_VM_CPUS="$cpus" VMT up
      run > "$DIR/hardware-${mb}m-${cpus}c.json" 2> "$DIR/hardware-${mb}m-${cpus}c.log" || true
      cat "$DIR/hardware-${mb}m-${cpus}c.json"
      VMT down
    done
    table ;;
  *) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 1 ;;
esac
