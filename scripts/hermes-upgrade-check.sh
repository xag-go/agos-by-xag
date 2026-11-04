#!/usr/bin/env bash
# The first step of every Hermes upgrade (docs/hermes-upgrade.md): does the target
# Hermes still have every internal AGOS uses, as AGOS uses it?
#
#   scripts/hermes-upgrade-check.sh <tag|sha> [hermes-agent repo]
#
# Checks the target out into a temporary git worktree of the installed hermes-agent
# repo (default $HERMES_AGENT_SRC, else ~/.hermes/hermes-agent), runs AGOS's
# contract checker on it (services/core/src/agos_core/engine/hermes_contract.py:
# reads the source with ast, imports and runs nothing of Hermes), prints its report
# and removes the worktree. The installed Hermes is never switched: its checkout,
# branch and files stay as they are (only git's worktree list changes, for the
# duration of the check). Nothing is fetched unless HERMES_FETCH=1.
#
# Exit: 0 = AGOS fits the target, 1 = something AGOS uses broke (stop the upgrade),
# 2 = bad arguments / target not found.
set -euo pipefail

target="${1:-}"
repo="${2:-${HERMES_AGENT_SRC:-$HOME/.hermes/hermes-agent}}"
here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/services/core/src"

if [ -z "$target" ]; then
  echo "usage: $0 <tag|sha> [hermes-agent repo]" >&2
  exit 2
fi
if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
  echo "not a git checkout of Hermes: $repo" >&2
  exit 2
fi
if [ "${HERMES_FETCH:-}" = "1" ]; then
  git -C "$repo" fetch --quiet origin --tags
fi
sha="$(git -C "$repo" rev-parse --verify --quiet "${target}^{commit}" || true)"
if [ -z "$sha" ]; then
  echo "no such Hermes commit or tag in $repo: $target (HERMES_FETCH=1 fetches first)" >&2
  exit 2
fi

before="$(git -C "$repo" rev-parse HEAD)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/hermes-upgrade-check.XXXXXX")"
tree="$tmp/hermes"
# shellcheck disable=SC2317  # run by the EXIT trap
cleanup() {
  git -C "$repo" worktree remove --force "$tree" >/dev/null 2>&1 || true
  git -C "$repo" worktree prune >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

git -C "$repo" worktree add --quiet --detach "$tree" "$sha"
echo "Hermes target: $target ($sha)"
echo "installed Hermes (untouched): $repo at $before"
echo

python="$here/services/core/.venv/bin/python"
[ -x "$python" ] || python="$(command -v python3)"
status=0
env -u PYTHONPATH PYTHONPATH="$src" "$python" -m agos_core.engine.hermes_contract "$tree" || status=$?

after="$(git -C "$repo" rev-parse HEAD)"
if [ "$after" != "$before" ]; then
  echo "the installed Hermes moved during the check ($before -> $after)" >&2
  exit 2
fi
if [ "$status" -ne 0 ]; then
  echo
  echo "STOP: AGOS doesn't fit Hermes $target yet. Change AGOS (and the contract) first."
fi
exit "$status"
