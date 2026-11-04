#!/usr/bin/env bash
# Checks that a release tag is the one the release workflow built and signed, before
# the installer or `agos update` runs any of its code (docs/releases.md, ADR 0028).
#
#   deploy/release-verify.sh <tag> <commit> [cosign-dir]
#
# The release workflow (.github/workflows/release.yml) publishes, beside each tag:
#   release.json            {"tag", "version", "commit", "tree"} of the tagged commit
#   SHA256SUMS              sha256 of release.json and of every other asset (SBOMs, archive)
#   SHA256SUMS.sigstore.json  a Sigstore bundle: SHA256SUMS signed keyless by that workflow
# Checked here: SHA256SUMS is signed by the release workflow of the official repository
# for THIS tag (cosign verify-blob, the certificate's identity and GitHub's OIDC issuer),
# release.json matches SHA256SUMS, and release.json names this tag and this commit. A
# git commit id covers every file of the code, so the checkout is the signed code.
#
# Settings (environment, or /etc/agos/agos.conf through the agos command):
#   AGOS_VERIFY            require (default) | warn | off  (off: developers' own builds only)
#   AGOS_RELEASES_URL      where the assets are (default: the official repository's releases)
#   AGOS_RELEASE_IDENTITY  the signing workflow's identity, a regular expression (default:
#                          the official release workflow on a v* tag)
#   AGOS_RELEASE_PUBKEY    a cosign public key file instead of keyless (a fork, the VM test)
# cosign: the one on PATH, else a pinned copy put in [cosign-dir] (default ~/.local/bin),
# checked against its pinned sha256 before it is used.
set -euo pipefail

TAG="${1:?usage: release-verify.sh <tag> <commit> [cosign-dir]}"
COMMIT="${2:?usage: release-verify.sh <tag> <commit> [cosign-dir]}"
BIN_DIR="${3:-$HOME/.local/bin}"
MODE="${AGOS_VERIFY:-require}"
REPO="${AGOS_GITHUB_REPO:-xag-go/agos-by-xag}"
URL="${AGOS_RELEASES_URL:-https://github.com/$REPO/releases/download}"
IDENTITY="${AGOS_RELEASE_IDENTITY:-^https://github\.com/${REPO//./\\.}/\.github/workflows/release\.yml@refs/tags/v[0-9].*$}"
ISSUER="https://token.actions.githubusercontent.com"
COSIGN_VERSION=v3.1.4
declare -A COSIGN_SHA256=(
  [amd64]=424e2c97d0b45fd7a6b608a87f090f35633f4c23ece5f092d48bba11aaf4bbfa
  [arm64]=ade83b7aac62e131cacfe96d958948b2150cc9efec46a570a2649b8e27dedad2
)

fail() {
  if [[ "$MODE" == warn ]]; then
    printf '  WARNING: release %s is NOT verified: %s\n' "$TAG" "$*" >&2; exit 0
  fi
  printf 'ERROR: release %s is not verified: %s\n' "$TAG" "$*" >&2
  printf '  Nothing was changed. If you build AGOS yourself, set AGOS_VERIFY=off (docs/releases.md).\n' >&2
  exit 1
}

case "$MODE" in
  off) echo "  release check skipped (AGOS_VERIFY=off)"; exit 0 ;;
  require|warn) ;;
  *) fail "AGOS_VERIFY is require, warn or off (got '$MODE')" ;;
esac
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-(beta|rc)\.[0-9]+)?$ ]] || fail "'$TAG' is not a release tag"
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "'$COMMIT' is not a full commit id"

cosign_bin() { # the cosign to use: on PATH, or the pinned download (sha256 checked)
  if command -v cosign >/dev/null; then command -v cosign; return 0; fi
  local arch got; arch="$(uname -m)"
  case "$arch" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) return 1 ;; esac
  if [[ -x "$BIN_DIR/cosign" ]] && [[ "$(sha256sum "$BIN_DIR/cosign" | cut -d' ' -f1)" == "${COSIGN_SHA256[$arch]}" ]]; then
    echo "$BIN_DIR/cosign"; return 0
  fi
  mkdir -p "$BIN_DIR"
  curl -fsSL --retry 3 -o "$BIN_DIR/cosign.download" \
    "https://github.com/sigstore/cosign/releases/download/$COSIGN_VERSION/cosign-linux-$arch" >&2 || return 1
  got="$(sha256sum "$BIN_DIR/cosign.download" | cut -d' ' -f1)"
  if [[ "$got" != "${COSIGN_SHA256[$arch]}" ]]; then rm -f "$BIN_DIR/cosign.download"; return 1; fi
  chmod 755 "$BIN_DIR/cosign.download" && mv -f "$BIN_DIR/cosign.download" "$BIN_DIR/cosign"
  echo "$BIN_DIR/cosign"
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
for f in release.json SHA256SUMS SHA256SUMS.sigstore.json; do
  curl -fsSL --retry 3 -m 120 -o "$work/$f" "$URL/$TAG/$f" 2>/dev/null || fail "its $f could not be downloaded from $URL/$TAG/"
done

cosign="$(cosign_bin)" || fail "cosign (the signature checker) could not be installed"
if [[ -n "${AGOS_RELEASE_PUBKEY:-}" ]]; then
  "$cosign" verify-blob --key "$AGOS_RELEASE_PUBKEY" --bundle "$work/SHA256SUMS.sigstore.json" \
    --insecure-ignore-tlog=true "$work/SHA256SUMS" >/dev/null 2>"$work/cosign.err" \
    || fail "the signature does not match the key $AGOS_RELEASE_PUBKEY ($(tail -1 "$work/cosign.err"))"
else
  "$cosign" verify-blob --bundle "$work/SHA256SUMS.sigstore.json" \
    --certificate-identity-regexp "$IDENTITY" --certificate-oidc-issuer "$ISSUER" \
    "$work/SHA256SUMS" >/dev/null 2>"$work/cosign.err" \
    || fail "SHA256SUMS is not signed by $REPO's release workflow ($(tail -1 "$work/cosign.err"))"
fi
grep -Eq '^[0-9a-f]{64}  release\.json$' "$work/SHA256SUMS" || fail "SHA256SUMS does not list release.json"
(cd "$work" && grep -E '  release\.json$' SHA256SUMS | sha256sum -c --quiet -) >/dev/null 2>&1 \
  || fail "release.json does not match its checksum"
[[ "$(jq -r .tag "$work/release.json")" == "$TAG" ]] || fail "release.json is for $(jq -r .tag "$work/release.json"), not $TAG"
[[ "$(jq -r .commit "$work/release.json")" == "$COMMIT" ]] \
  || fail "the tag points at ${COMMIT:0:12}, but the signed release is commit $(jq -r .commit "$work/release.json" | cut -c1-12)"
signer="the release workflow of $REPO"; [[ -z "${AGOS_RELEASE_PUBKEY:-}" ]] || signer="the key $AGOS_RELEASE_PUBKEY"
echo "  release $TAG verified (signed by $signer, commit ${COMMIT:0:12})"
