#!/usr/bin/env bash
# Puts every workspace's Hermes root of a restored backup in place with Hermes's own
# `hermes import` (ADR 0020: each root is Hermes's own `hermes backup`, stored as
# hermes/roots/<name>.zip). Each zip goes into <roots>/<name>, run with that root as
# HERMES_HOME (and the install's runtime, as AGOS runs every root). Refuses a root
# that is already there; never overwrites one.
#
#   deploy/import-roots.sh <restored-dir> <roots-dir>
#
# HERMES_BIN (default ~/.local/bin/hermes) and HERMES_RUNTIME_DIR (default
# ~/.hermes/tools) can be set. AGOS_ROOT_RENAME=<from>:<to> puts a root named
# <from><id> at <roots>/<to><id> (a staging copy's own profile prefix).
set -euo pipefail
SRC="$1"
ROOTS="$2"
HERMES_BIN="${HERMES_BIN:-$HOME/.local/bin/hermes}"
RUNTIME="${HERMES_RUNTIME_DIR:-$HOME/.hermes/tools}"
RENAME="${AGOS_ROOT_RENAME:-}"
target_name() { # the root's folder name in <roots-dir>
  local name="$1" from="${RENAME%%:*}" to="${RENAME#*:}"
  if [[ -n "$RENAME" && "$name" == "$from"* ]]; then name="$to${name#"$from"}"; fi
  printf '%s\n' "$name"
}
shopt -s nullglob
zips=("$SRC"/hermes/roots/*.zip)
if [[ ${#zips[@]} -eq 0 ]]; then
  echo "no workspace roots in this backup (hermes/roots/*.zip)"
  exit 0
fi
for zip in "${zips[@]}"; do
  name="$(basename "$zip" .zip)"
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "odd root name $name; refusing" >&2; exit 1; }
  name="$(target_name "$name")"
  [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "odd root name $name; refusing" >&2; exit 1; }
  if [[ -e "$ROOTS/$name/config.yaml" ]]; then
    echo "root $name already exists in $ROOTS; refusing" >&2
    exit 1
  fi
done
mkdir -p "$ROOTS"
for zip in "${zips[@]}"; do
  name="$(target_name "$(basename "$zip" .zip)")"
  mkdir -p "$ROOTS/$name"
  HERMES_HOME="$ROOTS/$name" HERMES_RUNTIME_DIR="$RUNTIME" "$HERMES_BIN" import --force "$zip"
  [[ -f "$ROOTS/$name/config.yaml" ]] || { echo "root $name: hermes import left no config.yaml" >&2; exit 1; }
  echo "root $name restored by Hermes into $ROOTS/$name"
done
