#!/usr/bin/env bash
# Sets the safety settings of the PUBLIC repository (the one-commit export made by
# scripts/publish-public.sh) through GitHub's API (gh api). Dry run by default: it
# prints every call and its body and changes nothing; --apply makes the calls.
#
#   scripts/public-repo-settings.sh [--repo OWNER/NAME] [--discussions] [--apply]
#
#   --repo OWNER/NAME  the public repository (default: $AGOS_PUBLIC_REPO or xag-go/agos-by-xag)
#   --discussions      turn GitHub Discussions on (default: off)
#   --apply            make the changes (needs `gh auth login` as a repository admin)
#
# What it sets (docs/releases.md, "The public repository's settings"):
#   - issues on, wiki off, discussions off unless --discussions, merged branches deleted;
#   - secret scanning + push protection, Dependabot alerts and security-update PRs
#     (version-update PRs come from .github/dependabot.yml), private vulnerability
#     reporting;
#   - branch protection on main: changes through a pull request (1 approval, stale
#     approvals dismissed, conversations resolved), every CI and Security job below
#     green on the PR's newest commit (reported by GitHub Actions only), no force-push, no deletion;
#     admins may bypass, so the owner's `publish-public.sh --push` still lands;
#   - a tag ruleset on v*: only admins create, move or delete release tags.
# Branch protection and rulesets are free on a public repository (no paid plan).
# Running it again changes nothing that is already set.
set -euo pipefail

usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; }
die() {
  echo "public-repo-settings: $*" >&2
  exit 1
}

REPO="${AGOS_PUBLIC_REPO:-xag-go/agos-by-xag}"
APPLY=0
DISCUSSIONS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs OWNER/NAME}"; shift 2 ;;
    --discussions) DISCUSSIONS=true; shift ;;
    --apply) APPLY=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
done
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "--repo must be OWNER/NAME, not $REPO"
command -v jq >/dev/null || die "jq is needed to write the request bodies"

# The `name:` of every job in .github/workflows/ci.yml and security.yml (both run on
# every pull request), exactly: GitHub names a required check by it
# (tests/test_public_repo_settings.py keeps this list in step).
CHECKS=(
  "Web (format, lint, typecheck, tests, API types drift)"
  "Web production build (next build)"
  "Web page bundle sizes (budget ratchet)"
  "Core static (ruff, mypy, layer rules, function complexity)"
  'Core tests (pytest -m "not hermes", parallel, diff coverage)'
  "API contract (openapi.json fresh, no breaking change)"
  "Repo hygiene (file size, docs, changelog, shellcheck)"
  "Workflow lint (actionlint, zizmor)"
  "Browser (Playwright clicks + screenshots on the web build)"
  "Python dependencies (pip-audit)"
  "Node dependencies (pnpm audit --prod, high+)"
  "SBOM (CycloneDX, Python + pnpm)"
  "SAST (Semgrep, new findings fail)"
  "Secrets (gitleaks)"
)
GITHUB_ACTIONS_APP=15368 # the GitHub Actions app: no other app or token can fake a check
ADMIN_ROLE=5             # the repository role "admin" in rulesets' bypass lists
TAG_RULESET="Release tags (v*)"

# call METHOD PATH [JSON body]
call() {
  local method="$1" path="$2" body="${3:-}"
  echo "gh api -X $method repos/$REPO$path"
  [[ -z "$body" ]] || jq . <<<"$body" | sed 's/^/    /'
  [[ "$APPLY" == 1 ]] || return 0
  if [[ -n "$body" ]]; then
    gh api -X "$method" "repos/$REPO$path" -H "Accept: application/vnd.github+json" \
      --input - <<<"$body" >/dev/null
  else
    gh api -X "$method" "repos/$REPO$path" -H "Accept: application/vnd.github+json" >/dev/null
  fi
}

if [[ "$APPLY" == 1 ]]; then
  command -v gh >/dev/null || die "gh (GitHub CLI) is needed for --apply"
  visibility="$(gh api "repos/$REPO" --jq .visibility)" || die "can't read $REPO (gh auth login? does it exist?)"
  [[ "$visibility" == public ]] ||
    die "$REPO is $visibility: this script is for the public repository (protection on a private one needs a paid plan)"
  echo "applying to $REPO"
else
  echo "dry run for $REPO: nothing is changed (add --apply)"
fi

# 1. Features and security switches.
call PATCH "" "$(jq -n --argjson discussions "$DISCUSSIONS" '{
  has_issues: true, has_wiki: false, has_projects: false, has_discussions: $discussions,
  delete_branch_on_merge: true,
  security_and_analysis: {
    secret_scanning: {status: "enabled"},
    secret_scanning_push_protection: {status: "enabled"},
    dependabot_security_updates: {status: "enabled"}
  }
}')"
call PUT /vulnerability-alerts             # Dependabot alerts
call PUT /automated-security-fixes         # Dependabot security-update PRs
call PUT /private-vulnerability-reporting  # SECURITY.md's "report privately" button

# 2. main: pull requests only, CI green, no force-push, no deletion.
call PUT /branches/main/protection "$(jq -n --argjson app "$GITHUB_ACTIONS_APP" '{
  required_status_checks: {
    strict: true,
    checks: [$ARGS.positional[] | {context: ., app_id: $app}]
  },
  enforce_admins: false,
  required_pull_request_reviews: {
    required_approving_review_count: 1,
    dismiss_stale_reviews: true,
    require_code_owner_reviews: false
  },
  restrictions: null,
  required_conversation_resolution: true,
  allow_force_pushes: false,
  allow_deletions: false
}' --args "${CHECKS[@]}")"

# 3. Release tags: only admins create, move or delete v* tags.
ruleset="$(jq -n --arg name "$TAG_RULESET" --argjson admin "$ADMIN_ROLE" '{
  name: $name, target: "tag", enforcement: "active",
  conditions: {ref_name: {include: ["refs/tags/v*"], exclude: []}},
  rules: [{type: "creation"}, {type: "update"}, {type: "deletion"}, {type: "non_fast_forward"}],
  bypass_actors: [{actor_id: $admin, actor_type: "RepositoryRole", bypass_mode: "always"}]
}')"
existing=""
if [[ "$APPLY" == 1 ]]; then
  existing="$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$TAG_RULESET\") | .id")"
fi
if [[ -n "$existing" ]]; then
  call PUT "/rulesets/$existing" "$ruleset"
else
  call POST /rulesets "$ruleset"
fi

if [[ "$APPLY" == 1 ]]; then
  echo "done: check Settings -> Branches, Rules and Code security on GitHub"
else
  echo "dry run: nothing changed"
fi
