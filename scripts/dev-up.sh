#!/usr/bin/env bash
# Starts (or restarts) the AGOS dev stack under launchd, outside any agent's
# process registry: core on 127.0.0.1:8766, web on 127.0.0.1:3001, and the webhook
# relay on 127.0.0.1:8767 (it passes ONLY "POST /hooks/<token>" to the core:
# the one port a public tunnel may point at). Logs go to
# $AGOS_DEV_LOGS (default ~/Library/Logs/agos-dev).
#
#   scripts/dev-up.sh          start / restart both
#   scripts/dev-up.sh down     stop both
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="${AGOS_DEV_LOGS:-$HOME/Library/Logs/agos-dev}"
DATA="${AGOS_DATA_DIR:-$ROOT/agos-data}"
UV="${UV:-$HOME/.hermes/bin/uv}"
PNPM="$(command -v pnpm || echo /opt/homebrew/bin/pnpm)"
BASE_PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin"
mkdir -p "$LOGS"

stop() {
  launchctl remove com.agos.dev.core 2>/dev/null || true
  launchctl remove com.agos.dev.web 2>/dev/null || true
  launchctl remove com.agos.dev.hooks 2>/dev/null || true
  for port in 8766 3001 8767; do
    lsof -ti "tcp:$port" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  done
  # launchd removes jobs asynchronously: submitting again before the old job
  # is gone silently does nothing (the core then never comes back). Wait.
  for _ in $(seq 1 30); do
    if ! launchctl list com.agos.dev.core >/dev/null 2>&1 \
      && ! launchctl list com.agos.dev.web >/dev/null 2>&1 \
      && ! lsof -ti tcp:8766 -sTCP:LISTEN >/dev/null 2>&1 \
      && ! launchctl list com.agos.dev.hooks >/dev/null 2>&1 \
      && ! lsof -ti tcp:3001 -sTCP:LISTEN >/dev/null 2>&1 \
      && ! lsof -ti tcp:8767 -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
}

if [[ "${1:-}" == "down" ]]; then
  stop
  echo "AGOS dev stack stopped"
  exit 0
fi

stop
sleep 1
rm -f "$ROOT/apps/web/.next/dev/lock"

launchctl submit -l com.agos.dev.core -o "$LOGS/core.log" -e "$LOGS/core.log" -- \
  /usr/bin/env -i HOME="$HOME" PATH="$BASE_PATH" LANG=C.UTF-8 \
  AGOS_ENGINE=hermes AGOS_DATA_DIR="$DATA" \
  /bin/sh -c "cd '$ROOT/services/core' && exec '$UV' run uvicorn agos_core.api.app:create_app --factory --host 127.0.0.1 --port 8766"

launchctl submit -l com.agos.dev.hooks -o "$LOGS/hooks.log" -e "$LOGS/hooks.log" -- \
  /usr/bin/env -i HOME="$HOME" PATH="$BASE_PATH" LANG=C.UTF-8 \
  /bin/sh -c "cd '$ROOT/services/core' && exec '$UV' run python -m agos_core.hook_relay"

launchctl submit -l com.agos.dev.web -o "$LOGS/web.log" -e "$LOGS/web.log" -- \
  /usr/bin/env -i HOME="$HOME" PATH="$BASE_PATH" LANG=C.UTF-8 \
  /bin/sh -c "cd '$ROOT/apps/web' && exec '$PNPM' exec next dev -H 127.0.0.1 -p 3001"

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://127.0.0.1:8766/health 2>/dev/null; then break; fi
  sleep 1
done
curl -fsS -o /dev/null -w "core %{http_code}\n" http://127.0.0.1:8766/health || echo "core not up (see $LOGS/core.log)"
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://127.0.0.1:3001/ 2>/dev/null; then break; fi
  sleep 1
done
curl -s -o /dev/null -w "web %{http_code}\n" http://127.0.0.1:3001/ || echo "web not up (see $LOGS/web.log)"
curl -fsS -o /dev/null -w "hooks %{http_code}\n" http://127.0.0.1:8767/health || echo "hooks relay not up (see $LOGS/hooks.log)"
