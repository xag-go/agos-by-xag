#!/usr/bin/env bash
# Checks a server after install/restore (or after a reboot with nobody logged in).
# Exits non-zero if anything is wrong. Read-only except for one real agent run per
# workspace (a tiny chat message in a temporary chat, removed afterwards).
#
#   deploy/verify-server.sh [--no-agent-run]
# ok/bad always succeed, so "A && ok || bad" is a plain if/else here.
# shellcheck disable=SC2015
set -uo pipefail
DATA="${AGOS_DATA_DIR:-$HOME/agos-data}"
ROOTS="${AGOS_HERMES_ROOTS:-$DATA/hermes}"
CORE="${AGOS_CORE_URL:-http://127.0.0.1:8766}"
RUN_AGENT=1
[[ "${1:-}" == "--no-agent-run" ]] && RUN_AGENT=0
FAIL=0
ok() { printf '  [ok]   %s\n' "$*"; }
bad() { printf '  [FAIL] %s\n' "$*"; FAIL=$((FAIL + 1)); }
TOKEN="$(cat "$DATA/system/internal.token" 2>/dev/null)"
# The token reaches curl through a pipe, never its argv (readable by any user in ps).
api() { curl -fsS -m 30 -H @<(printf 'x-agos-internal: %s\n' "$TOKEN") -H "content-type: application/json" "$@"; }

echo "Services"
for s in docker agos-core agos-web agos-hooks tailscaled; do
  systemctl is-active --quiet "$s" && ok "$s running" || bad "$s not running"
  systemctl is-enabled --quiet "$s" && ok "$s starts at boot" || bad "$s not enabled at boot"
done
loginctl show-user "$(id -un)" 2>/dev/null | grep -q "Linger=yes" && ok "runs with nobody logged in" || bad "linger off"
[[ "$(systemctl is-enabled sleep.target 2>/dev/null)" == masked ]] && ok "never sleeps" || bad "sleep not disabled"

echo "AGOS"
api "$CORE/health" >/dev/null && ok "core answers" || bad "core down"
curl -fsS -m 10 -o /dev/null http://127.0.0.1:3000/ && ok "web answers on 127.0.0.1" || bad "web down"
WS=$(api "$CORE/workspaces" | jq -r '.[].id')
for ws in $WS; do
  n_tasks=$(api "$CORE/workspaces/$ws/tasks" | jq length)
  n_chats=$(api "$CORE/workspaces/$ws/chats" | jq length)
  soul="$ROOTS/agos-$ws/SOUL.md"  # the workspace's own Hermes root (ADR 0020)
  [[ -s "$soul" ]] && ok "$ws: SOUL present, $n_tasks tasks, $n_chats chats" || bad "$ws: SOUL missing"
  [[ -d "$DATA/workspaces/$ws/files" ]] && ok "$ws: files folder" || bad "$ws: files folder missing"
  docker network inspect "agos-net-agos-$ws" >/dev/null 2>&1 && ok "$ws: isolated network" || bad "$ws: network missing"
done
while IFS=$'\t' read -r name status reason; do
  [[ "$status" == "connected" ]] && ok "channel $name connected" || bad "channel $name: $status $reason"
done < <(api "$CORE/channels" | jq -r '.[] | [.name, .status, (.statusReason // "")] | @tsv')
api "$CORE/models/catalog" | jq -e 'length > 0' >/dev/null && ok "core runs Hermes (models list)" \
  || bad "no models: log in to a provider once (hermes auth add anthropic --type oauth --no-browser), or core can't run Hermes"
curl -fsS -m 5 http://127.0.0.1:8767/health >/dev/null && ok "webhook relay answers" || bad "webhook relay down"
docker ps --filter name=agos-egress --format '{{.Status}}' | grep -q Up && ok "egress proxy up" || bad "egress proxy down"

echo "Isolation (docs/adr/0025)"
# Every running hermes sandbox: non-root, caps dropped, no-new-privileges, limits.
SANDBOXES=$(docker ps --filter label=hermes-agent=1 --format '{{.ID}}')
[[ -z "$SANDBOXES" ]] && ok "no sandbox running (nothing to check; start one with an agent turn)"
for c in $SANDBOXES; do
  name=$(docker inspect "$c" --format '{{.Name}}')
  u=$(docker exec "$c" id -u 2>/dev/null)
  [[ -n "$u" && "$u" != 0 ]] && ok "$name: terminal is non-root (uid $u)" || bad "$name: terminal runs as uid '${u:-?}'"
  docker inspect "$c" --format '{{.HostConfig.CapDrop}}' | grep -qw ALL && ok "$name: capabilities dropped" || bad "$name: CapDrop misses ALL"
  docker inspect "$c" --format '{{.HostConfig.SecurityOpt}}' | grep -q no-new-privileges && ok "$name: no-new-privileges" || bad "$name: no-new-privileges missing"
  [[ "$(docker inspect "$c" --format '{{.HostConfig.PidsLimit}}')" -gt 0 ]] && ok "$name: pids limited" || bad "$name: no pids limit"
  [[ "$(docker inspect "$c" --format '{{.HostConfig.Memory}}')" -gt 0 ]] && ok "$name: memory limited" || bad "$name: no memory limit"
  docker exec "$c" sh -c 'test -S /var/run/docker.sock -o -S /run/docker.sock' 2>/dev/null \
    && bad "$name: the Docker socket is INSIDE the sandbox" || ok "$name: no Docker socket inside"
done
# Every installed gateway: walled (ExecStart wraps wall.py), limited and caged. Only
# the owner's AGOS_SANDBOXD=off (agos-core's environment) makes an uncaged one ok:
# otherwise it holds the real Docker socket (host root).
CORE_ENV="$(systemctl show -p Environment --value agos-core 2>/dev/null || true)"
for conf in "$HOME/.config/systemd/user"/*.service.d/agos-runtime.conf; do
  [[ -e "$conf" ]] || continue
  unit=$(basename "$(dirname "$conf")" .d)
  grep -q "wall.py" "$conf" && ok "$unit: Landlock wall in place" || bad "$unit: no wall in its drop-in"
  grep -q "^MemoryMax=" "$conf" && ok "$unit: memory limited" || bad "$unit: no MemoryMax in its drop-in"
  grep -q "^TasksMax=" "$conf" && ok "$unit: tasks limited" || bad "$unit: no TasksMax in its drop-in"
  if grep -q '"bwrap"' "$conf"; then
    grep -q "^KillMode=control-group" "$conf" && ok "$unit: caged (bwrap, KillMode=control-group)" \
      || bad "$unit: caged without KillMode=control-group (its stop would hang)"
  elif [[ " ${CORE_ENV,,} " == *" agos_sandboxd=off "* ]]; then
    ok "$unit: not caged (AGOS_SANDBOXD=off, the owner's choice) — the wall still stands"
  else
    bad "$unit: NOT caged, its gateway holds the real Docker socket (fix bwrap: re-run the installer for its AppArmor profile; or set AGOS_SANDBOXD=off on purpose)"
  fi
done
grep -qs "SystemMaxUse" /etc/systemd/journald.conf.d/agos.conf && ok "journal size capped" || bad "no journald cap (re-run the installer)"

if [[ "$RUN_AGENT" == 1 ]]; then
  echo "One real agent run per workspace"
  for ws in $WS; do
    chat=$(api -X POST "$CORE/workspaces/$ws/chats" -d '{"title":"move check"}' | jq -r .id)
    api -X POST "$CORE/workspaces/$ws/chats/$chat/messages" -d '{"body":"Reply with exactly: MOVE-OK"}' >/dev/null
    reply=""
    for i in $(seq 1 60); do
      sleep 3
      view=$(api "$CORE/workspaces/$ws/chats/$chat")
      # Only the agent's own reply counts: the owner's message above contains
      # the expected text too, so "the last message" would always match.
      reply=$(echo "$view" | jq -r '[.messages[] | select(.from == "agent")] | last | .body // ""')
      [[ -n "$reply" ]] && break
      [[ "$i" -gt 5 && "$(echo "$view" | jq -r '.working or .pending')" == "false" ]] && break
    done
    [[ "$reply" == *MOVE-OK* ]] && ok "$ws: agent answered" || bad "$ws: agent didn't answer (log in to the provider?) — got: ${reply:0:120}"
    api -X DELETE "$CORE/workspaces/$ws/chats/$chat" >/dev/null || true
  done
fi

echo "Private access"
sudo -n ufw status 2>/dev/null | grep -q "Status: active" && ok "firewall on" || bad "firewall off"
if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.0\.0\.1|\[::1\]|100\.)' | grep -qE ':(3000|8766)$'; then
  bad "AGOS listens on a public interface"
else
  ok "AGOS listens only on loopback / Tailscale"
fi
echo
[[ $FAIL -eq 0 ]] && { echo "All checks passed."; exit 0; } || { echo "$FAIL check(s) failed."; exit 1; }
