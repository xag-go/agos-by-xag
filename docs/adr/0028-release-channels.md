# ADR 0028: Release channels, signed releases, and how a release is cut

Date: 2026-11-03. Status: accepted (built on `eng/m7-release`; nothing is published
until the owner pushes a release tag).

## The problem

Until 0.1.2, "a release" was whatever the `main` branch held: the installer cloned
`main`, `agos update` and Settings → Update AGOS pulled `main`, and the `VERSION`
file stayed at 0.1.0 through three live ships. For a public install that means:

1. **Every push to `main` reaches every user** on their next update, tested or not.
2. **Nothing proves the code is ours.** A changed tag, a hijacked mirror or a
   man-in-the-middle on a self-hosted mirror would be installed and run as root.
3. **No version to name in an issue**, no upgrade test from "the version users
   have", no release notes.

## Decision

### Versions and tags

- **SemVer, starting at 0.x** (0.x = beta: anything may still change between minor
  versions). A release is an annotated git tag `vX.Y.Z`; a beta or release
  candidate is `vX.Y.Z-beta.N` / `vX.Y.Z-rc.N`, which sorts before `vX.Y.Z`.
- `VERSION`, the README badge and CHANGELOG's `## [X.Y.Z] - <date>` section agree
  with the tag. `scripts/release.py prepare X.Y.Z` makes them agree (one commit, one
  tag, locally, nothing pushed); the release workflow refuses a tag that disagrees
  (`scripts/release.py check`).
- The three live ships before this ADR are tagged after the fact (local annotated
  tags, not pushed): **v0.1.0** = `33e135a1` (main at PR #35; live ran `ae0a7aa4`,
  same tree), **v0.1.1** = `5502ddd2` (security hotfix, PR #37), **v0.1.2** =
  `4061b5e7` (wave 6, PR #38). Their `VERSION` files still read 0.1.0; their
  CHANGELOG sections were written afterwards.

### Channels

| Channel            | Follows                                                      | For                                |
| ------------------ | ------------------------------------------------------------ | ---------------------------------- |
| `stable` (default) | the newest `vX.Y.Z` tag                                      | everyone                           |
| `beta`             | the newest tag, betas and release candidates included        | people who try a release first     |
| `main`             | the `main` branch (or `AGOS_REF`), every commit, not checked | developers; the owner's own server |

- The installer installs the channel's newest release (`AGOS_CHANNEL`, `AGOS_REF`
  by hand) and writes `AGOS_CHANNEL` into `/etc/agos/agos.conf`. When no release of
  the channel exists yet, it installs `main` but keeps the channel, so the first
  release past that code is the next update.
- `agos update`, `agos update --check` and Settings → Update AGOS follow the
  install's channel. `agos channel [stable|beta|main]` shows or changes it;
  `agos update --channel <c>` uses another one once. An install made before
  channels has no `AGOS_CHANNEL`: it follows `stable`.
- **Updates only move forward.** A channel's newest release that this code
  already contains (an install on `main` past the last release) is "up to date",
  never a step back. Going back is `agos rollback` (the release before the last
  update) or a restore — never an update.
- A release tag is fetched without `--force`: a tag that changed on the server is
  refused (the update stops with a message), never taken.

### Signed releases

The release workflow (`.github/workflows/release.yml`, on a pushed release tag)
publishes, beside the GitHub release: the code archive, a CycloneDX SBOM,
`release.json` (`tag`, `version`, `commit`, `tree`), `SHA256SUMS` of all of them,
`SHA256SUMS.sigstore.json` (SHA256SUMS signed **keyless** with Sigstore by that
workflow's GitHub identity; no key exists to leak or lose), and SLSA build
provenance for every file (GitHub's attest action).

Before the installer or `agos update` runs any of a release's code,
`deploy/release-verify.sh` checks: the signature was made by the official
repository's `release.yml` on a `v*` tag (cosign `verify-blob`, certificate
identity + GitHub's OIDC issuer, Rekor transparency log); `release.json` matches
`SHA256SUMS`; `release.json` names this tag **and the commit the tag points at**.
A git commit id covers every file of the code, so a checkout of that commit is the
signed code. On any failure nothing changes, and the message says why.
`AGOS_VERIFY=warn|off` exists for developers' own builds; `AGOS_RELEASE_PUBKEY`
lets a fork (and the VM test) sign with its own cosign key. cosign itself is the one
on PATH, else a pinned version downloaded and checked against its pinned sha256.

The `main` channel is not checked: a branch has no release to compare with.

### Base images

The sandbox image's base (`docker/sandbox/Dockerfile`) is pinned by digest;
Dependabot proposes the next digest as a PR, which CI builds like any change.

## What needs the owner

- **Pushing a release tag** (`git push origin main vX.Y.Z`): the only step that
  publishes. Nothing in this branch pushes.
- GitHub settings on the public repository: Actions may create releases (default),
  and — recommended — a tag protection rule for `v*` so only he can push release
  tags. Keyless signing needs no secret and no key.
- Optional: a git signing key (`git config user.signingkey`), then
  `scripts/release.py prepare` signs the tag too (`git tag -s`). Not required: the
  Sigstore signature is what installs check.
- His own server: it ships from branches, ahead of every release. Set
  `agos channel main` there if `agos update` should keep following `main`; on
  `stable` it reports "this code is newer than the newest release" and does nothing.

## Alternatives considered

- **Git tag signatures only** (GPG/SSH): needs a key on his machine, a keyring on
  every install, and says nothing about what the workflow built. Kept as an extra.
- **A long-lived cosign key in GitHub secrets**: a key to rotate and to leak.
  Keyless binds the signature to the workflow file and the tag instead.
- **Following `main` with a "stable" branch**: a branch moves; a tag + signature
  names one exact commit, and the upgrade test can install each one.

## Consequences

- An issue names a version; the upgrade test (`deploy/test-upgrade-vm.sh`) installs
  every release tag, adds data, updates it to the new code and checks the data.
- Until the first tag is pushed, public installs keep getting `main` (with a
  warning), and their channel is `stable`: the first published release reaches them
  as an ordinary update.
- 0.1.0 and 0.1.1's own `agos update` die on an update over more than 20 commits
  (`git log | head -20` under `pipefail`); the bridge is in docs/releases.md.
