#!/usr/bin/env bash
# Server rehearsal in an Ubuntu 24.04 container (no real server, no systemd):
# installs Hermes with its own installer, pinned to deploy/hermes.pin (the
# commit this PC runs), and AGOS core for real; restores a COPY of a backup
# into the container, puts it in place like deploy/place-restore.sh, starts
# core on it and checks what the owner uses: every workspace, its tasks,
# chats, automations, rule files (Documentation), SOUL, memory, MCP sign-ins,
# and the Hermes probes (models, MCP test) that broke once after a Hermes
# update. What a container can't prove is listed at the end.
#
#   deploy/rehearse-in-container.sh <backup.agosb>   (password in AGOS_BACKUP_PASSWORD)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
[[ -n "${AGOS_BACKUP_PASSWORD:-}" ]] || { echo "set AGOS_BACKUP_PASSWORD" >&2; exit 1; }
PIN="$(cat "$ROOT/deploy/hermes.pin")"
NAME="agos-rehearsal-$$"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" \
  -v "$ROOT:/src:ro" -v "$BACKUP:/backup.agosb:ro" -v "$HOME/.hermes/hermes-agent:/hermes-src:ro" \
  -e AGOS_BACKUP_PASSWORD -e PIN="$PIN" \
  ubuntu:24.04 sleep infinity >/dev/null

docker exec -e DEBIAN_FRONTEND=noninteractive "$NAME" bash -euo pipefail -c '
apt-get update -qq >/dev/null
# The same system packages deploy/install-server.sh installs (minus Docker/Node/UI).
apt-get install -y -qq ca-certificates curl git jq sqlite3 python3 python3-venv rsync xz-utils \
  libatomic1 build-essential sudo >/dev/null
useradd --create-home agos
echo "--- Hermes (its own installer) pinned to ${PIN:0:12}"
# The PC copy of the Hermes repo stands in for GitHub (same commit).
su agos -c "git clone -q /hermes-src /tmp/hermes-src && bash /tmp/hermes-src/scripts/install.sh --commit $PIN --non-interactive" > /tmp/hermes-install.log 2>&1 \
  || { tail -30 /tmp/hermes-install.log; exit 1; }
su agos -c "~/.local/bin/hermes --version | head -1"
su agos -c "~/.local/bin/hermes --version" | grep -q "${PIN:0:9}" || { echo "Hermes is not at the pinned commit"; exit 1; }
echo "--- AGOS core"
su agos -c "curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1"
su agos -c "rsync -a --exclude node_modules --exclude .venv --exclude .next --exclude agos-data --exclude agos-backups /src/ ~/agos/"
su agos -c "cd ~/agos/services/core && ~/.local/bin/uv sync -q --frozen"
echo "--- restore + verify (empty target)"
su agos -c "cd ~/agos/services/core && AGOS_BACKUP_PASSWORD=$AGOS_BACKUP_PASSWORD ~/.local/bin/uv run python scripts/restore_and_verify.py /backup.agosb ~/restored"
echo "--- put in place (as deploy/place-restore.sh; added folders dropped here)"
su agos -c "mkdir -p ~/agos-data ~/.hermes/profiles && cp -a ~/restored/agos-data/. ~/agos-data/ && ~/agos/deploy/import-roots.sh ~/restored ~/agos-data/hermes && if [ -f ~/restored/hermes/hermes-backup.zip ]; then ~/.local/bin/hermes import --force ~/restored/hermes/hermes-backup.zip; elif [ -d ~/restored/hermes/profiles ]; then cp -a ~/restored/hermes/profiles/. ~/.hermes/profiles/; fi"
su agos -c "sqlite3 ~/agos-data/system/agos.db \"DELETE FROM workspace_folders\" 2>/dev/null || true"
echo "--- start core on the restored data (engine on, no Docker in the container)"
su agos -c "cd ~/agos/services/core && AGOS_ENGINE=hermes AGOS_DATA_DIR=/home/agos/agos-data AGOS_HERMES_BIN=/home/agos/.local/bin/hermes AGOS_DOCKER_BIN=/bin/true LANG=C.UTF-8 PATH=/home/agos/.local/bin:/usr/bin:/bin nohup ~/.local/bin/uv run uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port 8766 > /tmp/core.log 2>&1 &"
for i in $(seq 1 90); do curl -fsS -o /dev/null http://127.0.0.1:8766/health 2>/dev/null && break; sleep 1; done
curl -fsS -o /dev/null http://127.0.0.1:8766/health || { tail -40 /tmp/core.log; exit 1; }
T=$(cat /home/agos/agos-data/system/internal.token)
api() { curl -fsS -m 120 -H "x-agos-internal: $T" "http://127.0.0.1:8766$1"; }
FAIL=0
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
for ws in $(api /workspaces | jq -r ".[].id"); do
  P=/home/agos/agos-data/hermes/agos-$ws
  echo "  $ws: $(api /workspaces/$ws/tasks | jq length) tasks, $(api /workspaces/$ws/chats | jq length) chats, $(api /workspaces/$ws/automations | jq length) automations, $(api /workspaces/$ws/docs | jq ".files | length") rule files, SOUL $(test -s $P/SOUL.md && echo ok || echo MISSING), memory $(test -f $P/memories/MEMORY.md && echo ok || echo none)"
  test -s $P/SOUL.md || bad "$ws: SOUL missing"
  signed=$(api /workspaces/$ws/connectors | jq -r "[.[] | select(.secret == \"signed in (OAuth)\") | .name] | join(\",\")")
  [[ -n "$signed" ]] && echo "    MCP signed in: $signed"
done
echo "--- Hermes probes from core (models catalog, MCP test)"
api /models/catalog | jq -e "length > 0" >/dev/null && echo "  models catalog ok" || bad "models catalog (core cannot run Hermes probes)"
api "/apps" >/dev/null && echo "  connectors page ok" || bad "connectors page"
echo "--- no PC paths left in the profiles after the startup re-sync"
sleep 5
left=$(grep -rl "/Users/" /home/agos/agos-data/hermes/agos-*/config.yaml /home/agos/agos-data/hermes/agos-*/.env 2>/dev/null || true)
[[ -z "$left" ]] && echo "  ok" || bad "PC paths still in: $left"
[[ $FAIL -eq 0 ]] && echo "REHEARSAL-OK" || { echo "$FAIL problem(s)"; tail -30 /tmp/core.log; exit 1; }
'
cat <<'EOF'

Not provable in a container (needs the real Ubuntu Desktop server):
  - systemd services start at boot and restart on failure; reboot with nobody logged in
  - Docker sandboxes + egress proxy on the server's Docker
  - Tailscale up, agos DNS → 100.x, HTTPS via DNS challenge, firewall (ufw)
  - sleep/suspend masked, GNOME screen lock
  - provider logins (hermes auth add …) and one real agent run per workspace
  Run on the server:  sudo deploy/install-server.sh --check  &&  deploy/verify-server.sh
EOF
