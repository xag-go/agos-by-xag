#!/usr/bin/env bash
# Proves the isolation story on a real install (the server or the test VM), as the
# AGOS user, no sudo. Read-only except throwaway probe files it removes.
#
#   scripts/check-isolation.sh            all workspaces
#
# What it proves (docs/adr/0025-workspace-isolation.md):
#   inside each SANDBOX: no Docker socket, non-root terminal, only this
#     workspace's folders, /workspace writable and scripts run (the owner's rule:
#     agents keep their powers);
#   behind each GATEWAY's wall (the real drop-in's own --rw/--ro flags): another
#     workspace's root and files are closed, its own stay open, /proc is read-only;
#   inside each gateway's CAGE (ADR 0025 step 4, when AGOS_SANDBOXD is on): the
#     real Docker socket is dead, DOCKER_HOST is this workspace's filtered socket,
#     sibling workspaces' sockets are invisible, and agos-sandboxd answers 403 to
#     anything beyond running this workspace's own sandbox.
# ok/bad always succeed, so "A && ok || bad" is a plain if/else here.
# shellcheck disable=SC2015
set -uo pipefail
DATA="${AGOS_DATA_DIR:-$HOME/agos-data}"
FAIL=0
ok() { printf '  [ok]   %s\n' "$*"; }
bad() { printf '  [FAIL] %s\n' "$*"; FAIL=$((FAIL + 1)); }
gap() { printf '  [gap]  %s\n' "$*"; }

echo "Sandboxes"
SANDBOXES=$(docker ps --filter label=hermes-agent=1 --format '{{.ID}} {{.Label "hermes-profile"}}')
[[ -z "$SANDBOXES" ]] && echo "  (none running: send one agent turn first for the sandbox checks)"
while read -r c profile; do
  [[ -n "$c" ]] || continue
  u=$(docker exec "$c" id -u 2>/dev/null)
  [[ -n "$u" && "$u" != 0 ]] && ok "$profile: terminal is non-root (uid $u)" || bad "$profile: terminal uid '${u:-?}'"
  docker exec "$c" sh -c 'test -S /var/run/docker.sock -o -S /run/docker.sock' 2>/dev/null \
    && bad "$profile: Docker socket inside the sandbox" || ok "$profile: no Docker socket inside"
  # Only this workspace is mounted: every bind source must be its files folder,
  # its own Hermes home folders, or a folder the owner granted — never another
  # workspace's or AGOS's system folder.
  others=$(docker inspect "$c" --format '{{range .Mounts}}{{if eq .Type "bind"}}{{.Source}}{{"\n"}}{{end}}{{end}}' \
    | grep -E "^$DATA/(system|hermes/)" | grep -v "hermes/${profile%%--*}" || true)
  [[ -z "$others" ]] && ok "$profile: no other workspace mounted" || bad "$profile: foreign mounts: $others"
  # The owner's rule: the agent still writes and runs its own scripts in /workspace.
  ran=$(docker exec "$c" sh -c 'printf "print(\"POWERS-OK\")" > /workspace/.agos-iso-probe.py \
    && python3 /workspace/.agos-iso-probe.py && rm /workspace/.agos-iso-probe.py' 2>&1)
  [[ "$ran" == "POWERS-OK" ]] && ok "$profile: writes and runs scripts in /workspace" || bad "$profile: /workspace powers broken: $ran"
done <<< "$SANDBOXES"

echo "Gateway walls"
shopt -s nullglob
for conf in "$HOME/.config/systemd/user"/*.service.d/agos-runtime.conf; do
  unit=$(basename "$(dirname "$conf")" .d)
  grep -q "wall.py" "$conf" || { bad "$unit: not walled"; continue; }
  grep -q "^MemoryMax=" "$conf" && ok "$unit: MemoryMax set" || bad "$unit: no MemoryMax"
  caged=0
  grep -q '"bwrap"' "$conf" && caged=1
  if [[ $caged == 1 ]]; then
    grep -q "^KillMode=control-group" "$conf" && ok "$unit: caged (bwrap + KillMode=control-group)" \
      || bad "$unit: caged but no KillMode=control-group (bwrap drops SIGTERM: the drain breaks)"
  fi
  # Rebuild this unit's exact cage+wall from its own drop-in and probe behind it.
  launcher=$(grep '^ExecStart=.*wall\.py' "$conf" | sed 's/^ExecStart=//')
  prefix=$(python3 - "$launcher" <<'PY'
import shlex, sys
argv = shlex.split(sys.argv[1])
last = len(argv) - 1 - argv[::-1].index("--")  # cage AND wall end with "--"
print("\n".join(a.replace("$$", "$").replace("%%", "%") for a in argv[: last + 1]))
PY
)
  mapfile -t WALL <<< "$prefix"
  own_root=$(printf '%s\n' "${WALL[@]}" | grep -A1 -x -- --rw | sed -n 2p)
  other=""
  for d in "$DATA"/hermes/agos-*/; do
    [[ -d "$d" && "$d" != "$own_root"* && "$own_root" != "${d%/}"* ]] && { other="${d%/}"; break; }
  done
  probe="
import os, pathlib, socket
def tried(fn):
    try: fn(); return 'open'
    except PermissionError: return 'denied'
own = tried(lambda: list(pathlib.Path('$own_root').iterdir()))
other = tried(lambda: list(pathlib.Path('${other:-/nonexistent}').iterdir())) if '$other' else 'denied'
proc = tried(lambda: open('/proc/1/comm', 'w'))
sock = 'reachable'
try:
    s = socket.socket(socket.AF_UNIX); s.connect('/run/docker.sock')
except OSError: sock = 'blocked'  # masked (/dev/null) or Landlock: either way no Docker
host = os.environ.get('DOCKER_HOST', '')
own_sock = 'down'
if host.startswith('unix://'):
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(host[7:]); own_sock = 'up'
    except OSError: pass
    siblings = [p.name for p in pathlib.Path(host[7:]).parent.parent.iterdir()]
    own_sock += '/alone' if len(siblings) == 1 else '/sees-siblings'
print(own, other, proc, sock, own_sock)
"
  read -r own other_got proc sock own_sock <<< "$("${WALL[@]}" python3 -I -c "$probe" 2>/dev/null)"
  [[ "$own" == open ]] && ok "$unit: its own root open" || bad "$unit: its own root closed ($own)"
  [[ "$other_got" == denied ]] && ok "$unit: other workspaces closed" || bad "$unit: another workspace is OPEN"
  [[ "$proc" == denied ]] && ok "$unit: /proc writes closed" || bad "$unit: /proc is writable"
  if [[ $caged == 1 ]]; then
    [[ "$sock" == blocked ]] && ok "$unit: real Docker socket blocked" || bad "$unit: real Docker socket REACHABLE in the cage"
    [[ "$own_sock" == up/alone ]] && ok "$unit: its own filtered socket up, siblings hidden" \
      || bad "$unit: filtered socket wrong ($own_sock)"
  else
    [[ "$sock" == blocked ]] && ok "$unit: Docker socket blocked" \
      || gap "$unit: Docker socket reachable (cage off: AGOS_SANDBOXD=off or bwrap missing)"
  fi
done

echo "Sandbox broker"
if XDG_RUNTIME_DIR="/run/user/$(id -u)" systemctl --user is-active -q agos-sandboxd.service 2>/dev/null; then
  ok "agos-sandboxd is active"
  for s in /run/user/"$(id -u)"/agos-sandboxd/*/docker.sock; do
    [[ -S "$s" ]] || continue
    got=$(python3 - "$s" <<'PY'
import http.client, socket, sys
class C(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.connect(sys.argv[1])
c = C("docker")
c.request("POST", "/v1.51/networks/create", b"{}", {"Content-Type": "application/json"})
print(c.getresponse().status)
PY
)
    [[ "$got" == 403 ]] && ok "$(basename "$(dirname "$s")"): forbidden Docker call refused (403)" \
      || bad "$(basename "$(dirname "$s")"): networks/create answered $got, not 403"
  done
  grep -qs '"denied"' "$DATA"/sandboxd/events.jsonl && ok "refusals land in the security log" \
    || gap "no denied event logged yet (nothing refused so far)"
else
  gap "agos-sandboxd not active (cage off, or no caged gateway started yet)"
fi

echo
[[ $FAIL -eq 0 ]] && { echo "All isolation checks passed."; exit 0; } || { echo "$FAIL check(s) failed."; exit 1; }
