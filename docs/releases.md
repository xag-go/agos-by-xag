# Releases

How AGOS is versioned, released, checked and updated. The decision and its
reasons: [ADR 0028](adr/0028-release-channels.md).

## Versions

- [Semantic Versioning](https://semver.org/), starting at **0.x** (beta: things may
  still change between minor versions). `X.Y.Z`: Z = fixes only, Y = new features
  or changes, X = 1 once AGOS is stable.
- A release is an annotated git tag `vX.Y.Z`. A beta is `vX.Y.Z-beta.N`, a release
  candidate `vX.Y.Z-rc.N`; both come before `vX.Y.Z` (`v0.2.0-beta.1` <
  `v0.2.0-rc.1` < `v0.2.0`).
- The `VERSION` file, the README badge and the CHANGELOG section `## [X.Y.Z] -
<date>` name the same version as the tag. `agos version` and Settings → General
  show it.

Released so far:

| Tag    | Date       | What                            |
| ------ | ---------- | ------------------------------- |
| v0.1.0 | 2026-11-04 | the first public release (beta) |

## Channels

| Channel            | Gets                                                     |
| ------------------ | -------------------------------------------------------- |
| `stable` (default) | the newest `vX.Y.Z` release                              |
| `beta`             | the newest release, betas and release candidates as well |
| `main`             | every commit on the `main` branch (developers)           |

```bash
agos channel              # which channel, and its newest release
sudo agos channel beta    # follow betas from now on (nothing is updated yet)
agos update --check       # is there a newer release on my channel?
agos update --channel main --yes   # once, from main, without changing the channel
```

The installer takes the newest stable release; `AGOS_CHANNEL=beta` or
`AGOS_CHANNEL=main` change that, `AGOS_REF=v0.2.0` installs one release by hand.
An update only moves forward: if your code is already past the newest release (you
followed `main`), `agos update` says so and changes nothing. Going back is
`agos rollback` or a restore.

## Every update: backup first, rollback if needed

`agos update` (and Settings → Update AGOS) always:

1. checks the release (below) before anything stops;
2. makes a backup: the full encrypted backup when a backup password is set, and
   always a rollback copy of the database and of the Hermes roots' settings;
3. stops AGOS, takes the release, moves Hermes to the commit it pins, rebuilds;
4. starts AGOS and checks it answers; for 10 minutes a watch keeps checking.

If a step fails, or the watch sees AGOS fail, it rolls back by itself (the old
code, database, Hermes and settings). `agos rollback` does the same by hand, once
(`--force` for a second time). Details: [INSTALL.md](INSTALL.md#updating) and
[operations.md](operations.md).

## Is this release the real one? (signatures)

Each release on GitHub carries:

| File                       | What                                                      |
| -------------------------- | --------------------------------------------------------- |
| `agos-X.Y.Z.tar.gz`        | the code at the tag                                       |
| `agos-X.Y.Z.cdx.json`      | the software bill of materials (CycloneDX, every library) |
| `release.json`             | the tag, the version, the commit and the tree it names    |
| `SHA256SUMS`               | the sha256 of each file above                             |
| `SHA256SUMS.sigstore.json` | the signature of `SHA256SUMS` (Sigstore, keyless)         |

plus SLSA build provenance (GitHub's "attestations"), which says which workflow run
built each file.

The installer and `agos update` check, before running anything of a release
(`deploy/release-verify.sh`): `SHA256SUMS` was signed by this repository's release
workflow for a `v*` tag; `release.json` matches it; and `release.json` names the
tag and the exact commit the tag points at. If anything differs, nothing is
installed or changed and the message says what failed.

Check a release by hand:

```bash
cosign verify-blob --bundle SHA256SUMS.sigstore.json \
  --certificate-identity-regexp '^https://github\.com/xag-go/agos-by-xag/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com SHA256SUMS
sha256sum -c SHA256SUMS
gh attestation verify agos-X.Y.Z.tar.gz --repo xag-go/agos-by-xag
```

Settings (environment, or `/etc/agos/agos.conf`):

- `AGOS_VERIFY=require` (default), `warn` (installs and says it is not verified),
  `off` (your own builds only).
- `AGOS_RELEASE_PUBKEY=<cosign.pub>`: a fork signs with its own cosign key instead.
- `AGOS_RELEASES_URL`: where the release files are (a mirror).

The `main` channel is never checked: a branch has no signed release.

## Cutting a release (the owner)

1. `CHANGELOG.md`: every change since the last release is under `## [Unreleased]`
   (the PR gate already asks for a line per product change).
2. On an up-to-date `main` with nothing uncommitted:

   ```bash
   python3 scripts/release.py prepare 0.2.0        # or 0.2.0-beta.1
   ```

   It writes `VERSION` and the README badge, turns `[Unreleased]` into
   `## [0.2.0] - <today>` under a new empty `[Unreleased]`, commits "Release 0.2.0"
   and makes the annotated tag `v0.2.0` (signed with your git key if
   `user.signingkey` is set). Nothing is pushed.

3. Run the upgrade test from every release (below) on the tagged commit.
4. Publish: `git push origin main v0.2.0`. That push is the only step that publishes.
5. The **Release** workflow checks the tag (`scripts/release.py check`), builds the
   files, signs, adds provenance and creates the GitHub release with the CHANGELOG
   section as its notes (betas and release candidates as "pre-release"). Installs
   on its channel get it on their next `agos update`.

A bad release is never changed or re-tagged (installs refuse a tag that moved):
release the fix as the next patch version.

What needs the owner once, on GitHub: allow Actions to create releases (default), and
protect `v*` tags (Settings → Rules → tag rule) so only he can push one. Keyless
signing needs no secret.

## Publishing the code

The public repository is an export of the development one
(`scripts/publish-public.sh`): one commit with the tracked files, after gitleaks,
the personal-words check and `scripts/release-private-paths.py`, which refuses
private development paths in the docs (a builder's worktree, the maintainer's
notes, helper scripts, ssh host or home folder). Run it alone any time:

```bash
python3 scripts/release-private-paths.py          # docs/ and the top-level *.md at HEAD
python3 scripts/release-private-paths.py --all    # every exported text file
```

### The public repository's settings

`scripts/public-repo-settings.sh` sets the public repository's safety settings
through GitHub's API. It is a dry run by default: it prints every call and its
body and changes nothing. `--apply` makes the calls (a repository admin logged in
with `gh auth login`); running it again changes nothing that is already set.

```bash
scripts/public-repo-settings.sh                  # dry run: what it would set
scripts/public-repo-settings.sh --apply          # set it
scripts/public-repo-settings.sh --discussions --apply   # and turn Discussions on
```

| Setting                       | Value                                                                                                                                                                                                                  |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Branch protection on `main`   | changes through a pull request (1 approval, stale approvals dismissed, conversations resolved); every job of `.github/workflows/ci.yml` and `security.yml` green on the newest commit, reported by GitHub Actions only |
| Force-push / delete `main`    | refused                                                                                                                                                                                                                |
| Admins                        | may bypass, so `scripts/publish-public.sh --push` (one commit straight to `main`) still lands                                                                                                                          |
| Release tags `v*` (a ruleset) | only admins create, move or delete them                                                                                                                                                                                |
| Secret scanning               | on, with push protection (a push holding a key is refused)                                                                                                                                                             |
| Dependabot                    | alerts and security updates on                                                                                                                                                                                         |
| Private vulnerability reports | on (the "Report a vulnerability" button that `SECURITY.md` points to)                                                                                                                                                  |
| Issues / wiki / discussions   | on / off / off unless `--discussions`                                                                                                                                                                                  |

Branch protection and rulesets cost nothing on a public repository; on a
private repository of a free organisation they need a paid plan, so the script
refuses a private one. The required checks are named by each CI job's `name:`:
renaming a job means updating the list in the script (a test compares the two)
and running it again with `--apply`.

## Development builds before v0.1.0

Before the first public release, three development builds were tagged in the
private development repository for the upgrade tests only (0.1.0, 0.1.1 and 0.1.2;
their `VERSION` file read 0.1.0, they were never signed or published, and their
notes are part of v0.1.0's CHANGELOG section). No public install runs them. What
`deploy/test-upgrade-vm.sh` still knows about them when it upgrades from one:

- The `agos` of the first two lists the new commits with `git log | head -20`
  under `set -o pipefail`, so an update over more than 20 commits ends there
  without a message. The test updates once with the new `agos` instead:

  ```bash
  sudo -u agos git -C ~agos/agos fetch -q origin main
  sudo -u agos git -C ~agos/agos show FETCH_HEAD:deploy/agos > /tmp/agos-new
  bash /tmp/agos-new update --yes
  ```

- An update decides with the `agos` of the release it starts from. Up to the
  third build, that `agos` restarted the workspaces' engines only when Hermes
  itself changed, so they kept the older AGOS plugin until their next restart
  (`sudo -u agos XDG_RUNTIME_DIR=/run/user/$(id -u agos) systemctl --user restart 'hermes-gateway*'`
  loads the new one). v0.1.0 restarts them whenever the plugin changes.

## Base images

`docker/sandbox/Dockerfile` names its base image by digest (`FROM
debian:bookworm-slim@sha256:...`), so a rebuild uses the same bytes. Dependabot proposes a
new digest as a PR every week; CI builds it like any change.

## Tests a release passes

- **Upgrade from every release** (`deploy/test-upgrade-vm.sh all`, on the kept test
  VM): for each release tag, oldest first, a fresh install of that release with
  its own installer, a workspace with cards, a backup and a chat answered by a
  scripted model, then that release's own `agos update` to the new code; checked:
  the code moved, the update finished without a rollback, deep health, the web,
  the workspace, cards and chat, the database migrated and intact, a new chat
  message is answered, and `agos update --check` finds nothing newer.
- **Hardware minimum** (`deploy/test-hardware-vm.sh all`): the load test on smaller
  VMs; the numbers are in [INSTALL.md](INSTALL.md#minimum-hardware).
- The release check itself, with a real cosign: `tests/test_agos_release_channels.py`
  (a fake machine) and, by hand, a key-signed release served from a folder
  (`AGOS_RELEASES_URL=file://...`, `AGOS_RELEASE_PUBKEY=cosign.pub`): accepted;
  a wrong commit, a changed `release.json`, another key and a keyless check of a
  key-signed bundle are each refused with their own message.
