#!/usr/bin/env bash
# Publishes a commit of this development repository to the public checkout as
# ONE new commit: the tracked files at that commit, without the development
# history (work-in-progress branches and commits stay here).
#
#   scripts/publish-public.sh [options] <public checkout folder>
#
#   --commit <rev>     what to publish (default: HEAD)
#   -m, --message <m>  the public commit's message (default: "AGOS <date>")
#   --push             push the public checkout's branch to its remote afterwards
#   --remote <name>    the remote to push to (default: origin)
#   --words <file>     the personal words list (default: $AGOS_PRIVATE_WORDS or
#                      ~/agos-private/private-words.txt, kept outside the repo)
#
# Before anything is committed, the exported files must pass three checks:
#   1. gitleaks on the exported files; only findings listed in .gitleaksignore
#      (known test fakes) are allowed;
#   2. no personal word (one per line, '#' comments, case-sensitive, plain text:
#      names, hosts, accounts that must never be published) in any file, file
#      name or in the public commit's author. Without the list, a generic check
#      runs instead (this machine's user name, host name and home folder, this
#      repository's git author);
#   3. no private development path in the docs (scripts/release-private-paths.py:
#      ~/agos-wt, ~/wiki, ~/agos-tools, a personal /home folder).
# Nothing is pushed unless --push is given. Files marked `export-ignore` in
# .gitattributes are left out (git archive).
set -euo pipefail

usage() { sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; }
die() {
  echo "publish-public: $*" >&2
  exit 1
}

REV=HEAD
MESSAGE=""
PUSH=0
REMOTE=origin
WORDS="${AGOS_PRIVATE_WORDS:-$HOME/agos-private/private-words.txt}"
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) REV="${2:?--commit needs a revision}"; shift 2 ;;
    -m | --message) MESSAGE="${2:?--message needs a text}"; shift 2 ;;
    --push) PUSH=1; shift ;;
    --remote) REMOTE="${2:?--remote needs a name}"; shift 2 ;;
    --words) WORDS="${2:?--words needs a file}"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) [[ -z "$TARGET" ]] || die "only one public checkout folder"; TARGET="$1"; shift ;;
  esac
done
[[ -n "$TARGET" ]] || { usage >&2; exit 2; }

SRC="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
GITLEAKS="${GITLEAKS:-$(command -v gitleaks || echo "$HOME/.local/bin/gitleaks")}"
[[ -x "$GITLEAKS" ]] || die "gitleaks not found (install it, or set GITLEAKS=/path/to/gitleaks)"
SHA="$(git -C "$SRC" rev-parse --verify "$REV^{commit}")" || die "no commit $REV"

[[ -d "$TARGET/.git" ]] || die "$TARGET is not a git checkout (git clone the public repository there, or git init it)"
TARGET="$(cd "$TARGET" && pwd)"
[[ "$(git -C "$TARGET" rev-parse --show-toplevel)" == "$TARGET" ]] || die "$TARGET is inside another checkout"
[[ "$TARGET" != "$SRC" ]] || die "the public checkout can't be this repository"
if [[ "$(git -C "$TARGET" rev-parse --path-format=absolute --git-common-dir)" -ef \
  "$(git -C "$SRC" rev-parse --path-format=absolute --git-common-dir)" ]]; then
  die "$TARGET shares this repository's history (a worktree of it?)"
fi
[[ -z "$(git -C "$TARGET" status --porcelain)" ]] || die "$TARGET has uncommitted changes"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
TREE="$WORK/tree"
mkdir -p "$TREE"
git -C "$SRC" archive --format=tar "$SHA" | tar -x -C "$TREE"
echo "exported $(find "$TREE" -type f | wc -l) files of ${SHA:0:12}"

# 1. Secrets. Scanned from inside the tree: .gitleaksignore names files by their
# path in the repository.
if ! (cd "$TREE" && "$GITLEAKS" dir . --no-banner --redact --exit-code 1 \
  --gitleaks-ignore-path .gitleaksignore) > "$WORK/gitleaks.log" 2>&1; then
  cat "$WORK/gitleaks.log" >&2
  die "gitleaks found secrets that are not in .gitleaksignore: nothing published"
fi
echo "gitleaks: no secrets"

# 2. Personal words.
AUTHOR="$(git -C "$TARGET" var GIT_AUTHOR_IDENT 2>/dev/null)" ||
  die "the public checkout has no git author (git -C $TARGET config user.name / user.email)"
LIST="$WORK/words"
if [[ -f "$WORDS" ]]; then
  grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$WORDS" > "$LIST" || true
  echo "personal words: $(wc -l < "$LIST") from $WORDS"
else
  # Generic: what names this machine and its user.
  {
    id -un
    hostname -s 2>/dev/null || true
    echo "$HOME/"
    git -C "$SRC" config user.name || true
    git -C "$SRC" config user.email || true
  } | awk 'length($0) >= 4' | sort -u > "$LIST"
  echo "personal words: $WORDS missing, generic check ($(wc -l < "$LIST") words of this machine)"
fi
[[ -s "$LIST" ]] || die "the personal words list is empty"
found="$(
  cd "$TREE" || exit 1
  grep -r -l -F -f "$LIST" . || true
)"
named="$(
  cd "$TREE" || exit 1
  find . | grep -F -f "$LIST" || true
)"
author_hit="$(printf '%s\n' "$AUTHOR" | grep -o -F -f "$LIST" || true)"
if [[ -n "$found$named$author_hit" ]]; then
  [[ -z "$found" ]] || { echo "files with a personal word:"; printf '%s\n' "$found" | sed 's/^/  /'; } >&2
  [[ -z "$named" ]] || { echo "file names with a personal word:"; printf '%s\n' "$named" | sed 's/^/  /'; } >&2
  [[ -z "$author_hit" ]] || echo "the public commit's author has a personal word" >&2
  die "personal words found: nothing published"
fi
echo "personal words: none"

# 2b. No private development path in the published docs (~/agos-wt, ~/wiki, a home).
python3 "$SRC/scripts/release-private-paths.py" --tree "$TREE" ||
  die "private paths in the docs: nothing published"

# 3. One commit with exactly the exported files.
find "$TARGET" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a "$TREE/." "$TARGET/"
git -C "$TARGET" add -A
if git -C "$TARGET" diff --cached --quiet; then
  echo "nothing changed since the last publish"
else
  git -C "$TARGET" commit -q -m "${MESSAGE:-AGOS $(date -u +%Y-%m-%d)}"
  echo "public commit: $(git -C "$TARGET" log -1 --format='%h %s')"
fi

if [[ "$PUSH" == 1 ]]; then
  branch="$(git -C "$TARGET" symbolic-ref --short HEAD)"
  git -C "$TARGET" push "$REMOTE" "$branch"
  echo "pushed $branch to $REMOTE"
else
  echo "not pushed (use --push)"
fi
