#!/usr/bin/env bash
# Upgrade test from every released version, on the same throwaway Ubuntu VM as
# deploy/test-install-vm.sh (its disk is always kept: AGOS_VM_KEEP_DISK=1).
#
# A "released version" is a release tag (vX.Y.Z or vX.Y.Z-beta.N, docs/releases.md).
# For each one, oldest first, the VM gets that release with fresh data, the owner's
# kind of data is added (a workspace, Kanban cards, a backup, a chat answered by the
# scripted fake model), then THAT release's own `agos update` brings this checkout's
# HEAD, the way a real install moves (its branch moved on the public repository).
# Then: the code is HEAD, the update finished without a rollback, /health?deep=1 and
# the web answer, and the workspace, its cards and its chat are all still there; a
# new chat message is answered on the new release; the new `agos update --check`
# (release channels, ADR 0028) finds nothing newer than HEAD.
#
#   deploy/test-upgrade-vm.sh all [tag...]   boot the kept disk, every tag (default:
#                                            all release tags, oldest first), shut down
#   deploy/test-upgrade-vm.sh one <tag>      one tag (the VM is up)
#
# How a release is put on the VM: the release's own installer (deploy/install-server.sh
# of that tag) runs over the machine with the data removed first, so it installs that
# release the way it did for its users, with warm caches (no 70-minute download). With
# AGOS_UPGRADE_FRESH=1 the oldest tag instead gets the full path: `agos uninstall
# --delete-data` of whatever is there, then that tag's own `curl install.sh | bash`.
#
# AGOS_VM_DIR (keep it on the kept disk: ~/.hermes/cache/scratch/agos-vm),
# AGOS_VM_SSH_PORT (2232), AGOS_VM_HTTP_PORT (8799), AGOS_UPGRADE_LLM_PORT (9761).
# shellcheck disable=SC2015,SC2016
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DIR="${AGOS_VM_DIR:-$HOME/.cache/agos-test-vm}"
SSH_PORT="${AGOS_VM_SSH_PORT:-2232}"
HTTP_PORT="${AGOS_VM_HTTP_PORT:-8799}"
LLM_PORT="${AGOS_UPGRADE_LLM_PORT:-9761}"
UP="$DIR/www/upgrade"
UP_URL="http://10.0.2.2:$HTTP_PORT/upgrade/agos.git"  # the host, as the VM sees it
export AGOS_VM_KEEP_DISK=1
VMT() { bash "$HERE/test-install-vm.sh" "$@"; }
vm() { ssh -q -i "$DIR/key" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=5 -o ServerAliveInterval=30 tester@127.0.0.1 "$@"; }
to_vm() { scp -q -i "$DIR/key" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$1" "tester@127.0.0.1:$2"; }
log() { printf '\n##### %s\n' "$*"; }
FAIL=0
ok() { echo "  [ok]   $*"; }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

release_tags() { # every release tag of this checkout, oldest first (SemVer order, betas before their release)
  git -C "$ROOT" -c versionsort.suffix=- tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=v:refname |
    grep -E '^v[0-9]+\.[0-9]+\.[0-9]+(-(beta|rc)\.[0-9]+)?$' || true
}

publish_at() { # publish_at <sha>: the "public" repository, its main branch at <sha>, with the release tags
  local sha="$1"
  mkdir -p "$UP"
  if [[ ! -d "$UP/agos.git" ]]; then git init -q --bare "$UP/agos.git"; fi
  git -C "$ROOT" push -q -f "$UP/agos.git" "$sha:refs/heads/main"
  git -C "$ROOT" push -q -f "$UP/agos.git" 'refs/tags/v*:refs/tags/v*'
  git -C "$UP/agos.git" update-server-info
}

fresh_install() { # fresh_install <tag>: no AGOS at all, then the tag's own one-liner
  local tag="$1"
  git -C "$ROOT" show "$tag:install.sh" > "$UP/install-$tag.sh"
  log "$tag: agos uninstall --delete-data of what is there, then $tag's own curl install.sh | bash"
  vm 'if command -v agos >/dev/null; then sudo env AGOS_BACKUP_PASSWORD=test-backup-password agos uninstall --delete-data --yes | tail -3; fi; rm -f ~/agos-last-backup-*.agosb'
  vm "curl -fsSL http://10.0.2.2:$HTTP_PORT/upgrade/install-$tag.sh | AGOS_REPO_URL=$UP_URL AGOS_REF=main bash -s -- --yes" > "$DIR/upgrade-$tag-install.log" 2>&1 \
    && ok "$tag installed (curl | bash)" || { bad "$tag install (log $DIR/upgrade-$tag-install.log)"; tail -20 "$DIR/upgrade-$tag-install.log"; return 1; }
}

rewind_install() { # rewind_install <tag>: data removed, the checkout at the tag, the tag's own installer
  local tag="$1" sha; sha="$(git -C "$ROOT" rev-parse "$tag^{commit}")"
  log "$tag: fresh data, the release's own installer (deploy/install-server.sh of $tag)"
  vm "SHA=$sha UP_URL=$UP_URL bash -s" > "$DIR/upgrade-$tag-install.log" 2>&1 <<'EOF' \
    && ok "$tag installed (its own installer, fresh data)" || { bad "$tag install (log $DIR/upgrade-$tag-install.log)"; tail -20 "$DIR/upgrade-$tag-install.log"; return 1; }
set -euo pipefail
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
sudo systemctl stop agos-web agos-hooks agos-core 2>/dev/null || true
# Every user service AGOS made (gateways, the sandbox broker, an update's watch): gone
# with the data they served.
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' 'agos-*' 2>/dev/null | awk '{print $1}'); do
  $U disable --now "$u" >/dev/null 2>&1 || true
  sudo rm -rf "/home/agos/.config/systemd/user/$u" "/home/agos/.config/systemd/user/$u.d"
done
$U stop 'agos-*' >/dev/null 2>&1 || true
$U daemon-reload || true
ids=$(sudo docker ps -aq --filter name=agos- || true); [[ -z "$ids" ]] || sudo docker rm -f $ids >/dev/null
# Anything the newer release left running as agos (a gateway restarted by the update's
# watch, a transient unit) still writes into the data: end the agos user's whole session.
sudo systemctl stop "user@$(id -u agos).service" || true
for _ in 1 2 3 4 5; do
  sudo rm -rf /home/agos/agos-data /home/agos/agos-backups /home/agos/agos-staging 2>/dev/null && break
  sleep 3
done
[[ ! -e /home/agos/agos-data ]] || { echo "the old data could not be removed"; exit 1; }
sudo systemctl start "user@$(id -u agos).service" || true
sudo -u agos git -C /home/agos/agos remote set-url origin "$UP_URL"
sudo -u agos git -C /home/agos/agos fetch -q --tags origin main
sudo -u agos git -C /home/agos/agos checkout -q --detach "$SHA"
sudo -u agos git -C /home/agos/agos clean -qfdx -e node_modules -e .venv -e .next
sudo env AGOS_REPO_URL="$UP_URL" AGOS_REF=main bash /home/agos/agos/deploy/install-server.sh --yes
EOF
}

add_data() { # add_data <tag>: what an owner has after a day (workspace, cards, backup, a chat answer)
  log "$1: the owner's data (workspace, cards, a backup, a chat answered by the fake model)"
  to_vm "$ROOT/services/core/tests/e2e/fake_llm.py" /tmp/fake_llm.py
  vm "LLM_PORT=$LLM_PORT bash -s" <<'EOF' | tee "$DIR/upgrade-data.log"
set -uo pipefail
ok() { echo "  [ok]   $*"; }; bad() { echo "  [FAIL] $*"; }
T=$(sudo cat /home/agos/agos-data/system/internal.token)
# A new workspace's first Hermes root syncs its dependencies: over 20 minutes on a
# small VM with a slow network (the 0.1.2 development build answers the POST only when the root is ready).
api() { curl -sS --fail-with-body -m 2700 -X "$1" -H "x-agos-internal: $T" -H "content-type: application/json" "http://127.0.0.1:8766$2" ${3:+--data "$3"}; }
U="sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user"
pkill -f '[f]ake_llm.py' || true
nohup setsid python3 /tmp/fake_llm.py "$LLM_PORT" /tmp/fake-llm.jsonl >/tmp/fake-llm.log 2>&1 &
ws=$(api POST /workspaces '{"name":"Upgrade Shop","defaultModel":{"provider":"openrouter","mode":"api","model":"x/y","effort":"medium"}}' | jq -r .id)
[[ -n "$ws" && "$ws" != null ]] && ok "workspace $ws" || { bad "no workspace"; exit 1; }
root=/home/agos/agos-data/hermes/agos-$ws
for _ in $(seq 1 120); do sudo test -f "$root/agos-bridge.json" && break; sleep 5; done
hset() { sudo -u agos env HERMES_HOME="$root" /home/agos/.local/bin/hermes config set "$1" "$2" >/dev/null; }
hset providers.fakellm.base_url "http://127.0.0.1:$LLM_PORT/v1"; hset providers.fakellm.api_key fake
hset providers.fakellm.api_mode chat_completions; hset model.provider fakellm; hset model.default fake-model
for u in $($U list-unit-files --type=service --no-legend --plain 'hermes-gateway*' | awk '{print $1}'); do
  $U cat "$u" 2>/dev/null | grep -F "HERMES_HOME=$root" >/dev/null && $U restart "$u"
done
sleep 10
for i in 1 2 3; do api POST "/workspaces/$ws/kanban" "{\"title\":\"Upgrade card $i\",\"body\":\"made on the old release\"}" >/dev/null || bad "card $i"; done
api PUT /backups/password '{"password":"test-backup-password"}' >/dev/null && api POST /backups/run | jq -c '{name}'
dm=$(api GET "/workspaces/$ws/workers" | jq -r '[.dms[] | select(.agent | not)][0].id')
api POST "/workspaces/$ws/chats/$dm/messages" '{"body":"hello before the upgrade","attachments":[]}' >/dev/null
for _ in $(seq 1 90); do
  api GET "/workspaces/$ws/chats/$dm" | jq -e '[.messages[] | select(.from == "agent" and (.body | tostring | contains("DM answer")))] | length > 0' >/dev/null && break; sleep 5
done
api GET "/workspaces/$ws/chats/$dm" | jq -e '[.messages[] | select(.from == "agent" and (.body | tostring | contains("DM answer")))] | length > 0' >/dev/null \
  && ok "the fake model answered the chat" || bad "no chat answer on the old release ($(tail -c 300 /tmp/fake-llm.log))"
printf 'WS=%s\nDM=%s\nMSGS=%s\nCARDS=%s\nUSER_VERSION=%s\n' "$ws" "$dm" \
  "$(api GET "/workspaces/$ws/chats/$dm" | jq '.messages | length')" \
  "$(api GET "/workspaces/$ws/kanban" | jq '[.cards[] | select(.title | startswith("Upgrade card"))] | length')" \
  "$(sudo sqlite3 /home/agos/agos-data/system/agos.db 'pragma user_version')" | tee $HOME/upgrade-before.env
EOF
  grep -q FAIL "$DIR/upgrade-data.log" && FAIL=$((FAIL + 1))
  return 0
}

update_and_check() { # update_and_check <tag>: the tag's own agos update to HEAD, then everything is still there
  local tag="$1" head; head="$(git -C "$ROOT" rev-parse HEAD)"
  log "$tag -> HEAD ${head:0:12}: the old release's own agos update"
  publish_at "$head"
  # The whole file, then a match (`| grep -q` under pipefail: git SIGPIPEd = "no match").
  if [[ "$(git -C "$ROOT" show "$tag:deploy/agos")" == *'| head -20'* ]]; then
    # The first two pre-public development builds: their agos update lists the new
    # commits with `git log | head -20` under pipefail and dies (SIGPIPE) on an update
    # over more than 20 commits. The bridge in docs/releases.md ("Development builds
    # before v0.1.0"): the new release's agos.
    echo "  [note] $tag's own agos update stops on a long update (docs/releases.md): the documented bridge"
    vm 'sudo -u agos git -C /home/agos/agos fetch -q origin main && sudo -u agos git -C /home/agos/agos show FETCH_HEAD:deploy/agos > /tmp/agos-new && bash /tmp/agos-new update --yes --channel main' \
      > "$DIR/upgrade-$tag-update.log" 2>&1 && ok "agos update (the bridge from $tag) finished" \
      || { bad "agos update from $tag (log $DIR/upgrade-$tag-update.log)"; tail -15 "$DIR/upgrade-$tag-update.log"; }
  else
    vm 'agos update --yes' > "$DIR/upgrade-$tag-update.log" 2>&1 && ok "agos update ($tag's own) finished" \
      || { bad "agos update from $tag (log $DIR/upgrade-$tag-update.log)"; tail -15 "$DIR/upgrade-$tag-update.log"; }
  fi
  vm "HEAD_SHA=$head bash -s" <<'EOF' | tee "$DIR/upgrade-$tag-after.log"
set -uo pipefail
ok() { echo "  [ok]   $*"; }; bad() { echo "  [FAIL] $*"; }
# shellcheck disable=SC1091
. $HOME/upgrade-before.env
T=$(sudo cat /home/agos/agos-data/system/internal.token)
api() { curl -sS --fail-with-body -m 600 -X "$1" -H "x-agos-internal: $T" -H "content-type: application/json" "http://127.0.0.1:8766$2" ${3:+--data "$3"}; }
[[ "$(sudo -u agos git -C /home/agos/agos rev-parse HEAD)" == "$HEAD_SHA" ]] && ok "the code is HEAD" || bad "the code is not HEAD"
state=$(sudo jq -c '{phase, rolled_back}' /home/agos/agos-data/system/agos-update.json)
[[ "$state" == '{"phase":"done","rolled_back":false}' ]] && ok "update state: done, no rollback" || bad "update state: $state"
curl -fsS "http://127.0.0.1:8766/health?deep=1" | jq -e .ok >/dev/null && ok "deep health ok" || bad "deep health: $(curl -sS 'http://127.0.0.1:8766/health?deep=1')"
[[ "$(curl -s -o /dev/null -m 60 -w '%{http_code}' http://127.0.0.1:3000/)" == 200 ]] && ok "web 200" || bad "web"
[[ "$(api GET /workspaces | jq -r --arg w "$WS" '.[] | select(.id == $w) | .name')" == "Upgrade Shop" ]] && ok "workspace kept" || bad "workspace lost"
[[ "$(api GET "/workspaces/$WS/kanban" | jq '[.cards[] | select(.title | startswith("Upgrade card"))] | length')" == "$CARDS" ]] && ok "the $CARDS cards kept" || bad "cards lost"
n=$(api GET "/workspaces/$WS/chats/$DM" | jq '.messages | length')
[[ "$n" -ge "$MSGS" ]] && ok "chat kept ($n messages)" || bad "chat lost messages ($n < $MSGS)"
uv=$(sudo sqlite3 /home/agos/agos-data/system/agos.db 'pragma user_version')
[[ "$uv" -ge "$USER_VERSION" ]] && ok "database migrated $USER_VERSION -> $uv" || bad "database version $uv < $USER_VERSION"
[[ "$(sudo sqlite3 /home/agos/agos-data/system/agos.db 'pragma integrity_check')" == ok ]] && ok "database integrity ok" || bad "database integrity"
# Answered = a new agent message after this one, and the model was asked with it (the
# scripted model echoes only the prompt's end, which the release's own notes may fill).
agents() { api GET "/workspaces/$WS/chats/$DM" | jq '[.messages[] | select(.from == "agent")] | length'; }
before=$(agents)
api POST "/workspaces/$WS/chats/$DM/messages" '{"body":"hello after the upgrade","attachments":[]}' >/dev/null
for _ in $(seq 1 90); do [[ "$(agents)" -gt "$before" ]] && break; sleep 5; done
[[ "$(agents)" -gt "$before" ]] && grep -F "hello after the upgrade" /tmp/fake-llm.jsonl >/dev/null \
  && ok "a new chat message is answered on the new release" || {
    bad "no answer on the new release"
    # What the next run needs to tell a rig problem from a real one.
    root=/home/agos/agos-data/hermes/agos-$WS
    sudo grep -A3 '^model:' "$root/config.yaml" | sed 's/^/    config: /'
    sudo tail -12 "$root/logs/gateway.log" 2>/dev/null | sed 's/^/    gateway: /'
    sudo grep -iE 'error|unknown provider|resolution' "$root/logs/agent.log" 2>/dev/null | tail -6 | sed 's/^/    agent: /'
    tail -3 /tmp/fake-llm.log | sed 's/^/    fake model: /'
  }
# The cage is required on the new release: the workspace's gateway runs caged (no refusal).
doc="$(sudo agos doctor 2>&1)"
grep -e '- mode: required' <<<"$doc" >/dev/null && grep -e '- cage: ok' <<<"$doc" >/dev/null \
  && grep -E -e '- gateways caged: ([1-9][0-9]*) of \1$' <<<"$doc" >/dev/null \
  && ok "agos doctor: cage required, ok, every gateway caged" \
  || { bad "agos doctor: the cage is not required/working after the upgrade"; grep -A8 'Workspace isolation' <<<"$doc"; }
if [[ "$(agos help 2>/dev/null)" == *--channel* ]]; then
  out=$(agos update --check 2>&1 || true)
  grep -qi "up to date" <<<"$out" && ok "agos update --check (stable channel): up to date" || bad "agos update --check: $out"
fi
EOF
  grep -q FAIL "$DIR/upgrade-$tag-after.log" && FAIL=$((FAIL + 1))
  return 0
}

one() { # one <tag> [fresh]
  local tag="$1" sha; sha="$(git -C "$ROOT" rev-parse "$tag^{commit}")" || { bad "no tag $tag"; return 1; }
  publish_at "$sha"
  if [[ "${2:-}" == fresh ]]; then fresh_install "$tag" || return 0; else rewind_install "$tag" || return 0; fi
  vm "sudo -u agos git -C /home/agos/agos rev-parse HEAD" | grep -qx "$sha" && ok "the VM runs $tag ($sha)" || bad "the VM is not on $tag"
  add_data "$tag"
  update_and_check "$tag"
}

case "${1:-all}" in
  one) [[ -n "${2:-}" ]] || { echo "usage: $0 one <tag>" >&2; exit 1; }; one "$2"; [[ $FAIL -eq 0 ]] && echo "UPGRADE-OK" || { echo "$FAIL upgrade check(s) failed"; exit 1; } ;;
  all)
    shift || true
    mapfile -t TAGS < <(if [[ $# -gt 0 ]]; then printf '%s\n' "$@"; else release_tags; fi)
    [[ ${#TAGS[@]} -gt 0 ]] || { echo "no release tags (docs/releases.md)" >&2; exit 1; }
    trap 'VMT down' EXIT
    VMT up
    first=1
    for t in "${TAGS[@]}"; do
      if [[ "$first" == 1 && "${AGOS_UPGRADE_FRESH:-0}" == 1 ]]; then one "$t" fresh; else one "$t"; fi
      first=0
    done
    [[ $FAIL -eq 0 ]] && echo "UPGRADE-OK (${TAGS[*]} -> HEAD)" || { echo "$FAIL upgrade check(s) failed"; exit 1; } ;;
  *) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 1 ;;
esac
