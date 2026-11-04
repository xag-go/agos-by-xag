#!/usr/bin/env bash
# The public repository's issue and PR labels, from .github/labels.json (docs/triage.md).
#
#   scripts/sync-labels.sh [--repo owner/name]           show what would be created or changed
#   scripts/sync-labels.sh --apply [--repo owner/name]   create or update them (gh, logged in)
#
# Labels that exist on GitHub but not in the file are listed, never deleted.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="xag-go/agos-by-xag"
APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --repo) REPO="${2:?--repo needs owner/name}"; shift 2 ;;
    *) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
  esac
done
command -v jq >/dev/null || { echo "jq is needed" >&2; exit 1; }
FILE="$ROOT/.github/labels.json"
have="$(gh label list --repo "$REPO" --limit 500 --json name,color,description 2>/dev/null || echo '[]')"
jq -c '.[]' "$FILE" | while read -r label; do
  name="$(jq -r .name <<<"$label")"; color="$(jq -r .color <<<"$label")"; desc="$(jq -r .description <<<"$label")"
  now="$(jq -c --arg n "$name" '.[] | select(.name == $n) | {color: (.color | ascii_downcase), description}' <<<"$have")"
  want="$(jq -c '{color: (.color | ascii_downcase), description}' <<<"$label")"
  [[ "$now" == "$want" ]] && continue
  if [[ "$APPLY" == 1 ]]; then
    gh label create "$name" --repo "$REPO" --color "$color" --description "$desc" --force >/dev/null
    echo "set     $name"
  else
    echo "would set  $name ($( [[ -z "$now" ]] && echo new || echo changed ))"
  fi
done
jq -r --slurpfile want "$FILE" '.[] | select([.name] | inside([$want[0][].name]) | not) | "not in the file (kept): \(.name)"' <<<"$have"
