#!/usr/bin/env bash
# Puts a verified restore in place on the server (after restore_and_verify.py):
# agos-data → ~/agos-data; every workspace's own Hermes root through Hermes's own
# `hermes import` (hermes/roots/<name>.zip → <roots>/<name>, deploy/import-roots.sh);
# the shared home's backup too (hermes/hermes-backup.zip: General Settings' keys;
# older backups: hermes/profiles/agos-*), then restarts AGOS, which re-syncs every
# workspace's sandbox.
#
#   deploy/place-restore.sh <restored-dir>
set -euo pipefail
SRC="$1"
DATA="${AGOS_DATA_DIR:-$HOME/agos-data}"
ROOTS="${AGOS_HERMES_ROOTS:-$DATA/hermes}"
HERE="$(cd "$(dirname "$0")" && pwd)"
[[ -d "$SRC/agos-data" ]] || { echo "$SRC is not a restored backup" >&2; exit 1; }
if [[ -e "$DATA/system/agos.db" ]]; then
  echo "$DATA already holds AGOS data; refusing to overwrite it." >&2
  exit 1
fi
sudo systemctl stop agos-web agos-core || true
mkdir -p "$DATA" "$HOME/.hermes/profiles"
cp -a "$SRC/agos-data/." "$DATA/"
# Each workspace's root (ADR 0020): Hermes's own import, one root at a time.
"$HERE/import-roots.sh" "$SRC" "$ROOTS"
if [[ -f "$SRC/hermes/hermes-backup.zip" ]]; then
  # Hermes restores its own backup (profiles, sessions, memory, skills, cron, logins).
  for name in $(unzip -Z1 "$SRC/hermes/hermes-backup.zip" | sed -n 's#^profiles/\(agos-[^/]*\)/.*#\1#p' | sort -u); do
    [[ -e "$HOME/.hermes/profiles/$name" ]] && { echo "profile $name exists; refusing" >&2; exit 1; }
  done
  "$HOME/.local/bin/hermes" import --force "$SRC/hermes/hermes-backup.zip"
else
  for p in "$SRC"/hermes/profiles/*; do
    name="$(basename "$p")"
    [[ -e "$HOME/.hermes/profiles/$name" ]] && { echo "profile $name exists; refusing" >&2; exit 1; }
    cp -a "$p" "$HOME/.hermes/profiles/$name"
  done
fi
chmod 600 "$DATA/system/master.key" "$DATA/system/agos.db"

if [[ -n "$(sqlite3 "$DATA/system/agos.db" "SELECT name FROM sqlite_master WHERE name='workspace_folders'")" ]]; then
  echo "Folders the workspaces use from this machine (copy them here first):"
  sqlite3 "$DATA/system/agos.db" "SELECT workspace_id, name, host_path FROM workspace_folders" |
  while IFS='|' read -r ws name old; do
    read -r -p "  $ws /shared/$name was $old — path on this server (empty = remove the folder): " new </dev/tty
    if [[ -z "$new" ]]; then
      sqlite3 "$DATA/system/agos.db" "DELETE FROM workspace_folders WHERE workspace_id='$ws' AND name='$name'"
    elif [[ -d "$new" ]]; then
      new_escaped="${new//\'/\'\'}"
      sqlite3 "$DATA/system/agos.db" "UPDATE workspace_folders SET host_path='$new_escaped' WHERE workspace_id='$ws' AND name='$name'"
    else
      echo "    $new doesn't exist; keeping it off (removed from the workspace)."
      sqlite3 "$DATA/system/agos.db" "DELETE FROM workspace_folders WHERE workspace_id='$ws' AND name='$name'"
    fi
  done
else
  # Since the folders moved into Hermes (each root's terminal.docker_volumes), a
  # folder the owner added is re-pointed in the workspace's Folders card.
  echo "Folders you added on the old machine: copy them here, then re-point each in its workspace's Folders card."
fi
sudo systemctl start agos-core agos-web agos-hooks
echo "AGOS started; at startup it re-syncs every workspace (profile config, network, sandbox)."
