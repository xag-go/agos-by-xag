# SLSA: current level and the path to Build L2/L3 for public releases

Assessed commit `33e135a1` (2026-11-02). SLSA v1.0 Build track. Lane codes: [README.md](README.md).

## Update 2026-11-03 (`eng/m7-release`): Build L2 from the first published release

Built, not yet run on GitHub (it runs when the owner pushes the first release tag;
[ADR 0028](../adr/0028-release-channels.md), [releases.md](../releases.md)):

| Step above                  | State                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1-3 release artifact + L1   | `.github/workflows/release.yml` on `v*` tags: `git archive` tarball, `release.json` (tag, commit, tree), `SHA256SUMS`, GitHub release. The first public release is v0.1.0; the earlier development tags exist locally only (after the fact, unsigned, never published).                                                                                                                                                                            |
| 4 hosted build + provenance | `actions/attest-build-provenance` (pinned by SHA) over `SHA256SUMS` on a GitHub-hosted runner; permissions `contents: write, id-token: write, attestations: write` on the one job.                                                                                                                                                                                                                                                                 |
| 5 SBOM                      | One CycloneDX SBOM of the whole tree (`anchore/sbom-action`, Syft) attached and covered by `SHA256SUMS` + provenance. Not done: `attest-sbom`.                                                                                                                                                                                                                                                                                                     |
| 6 signed tags               | `scripts/release.py prepare` signs the tag when the owner has a git signing key; the gate is the **Sigstore keyless signature** of `SHA256SUMS` (cosign `sign-blob`, verified in the workflow before publishing), not `git tag -v`.                                                                                                                                                                                                                |
| 7 actions pinned, zizmor    | Done (every action by full SHA; zizmor and actionlint clean on `release.yml`).                                                                                                                                                                                                                                                                                                                                                                     |
| 8 installer verifies        | Done: `deploy/release-verify.sh` (cosign `verify-blob`, identity = this repository's `release.yml` on a `v*` tag, GitHub OIDC issuer, Rekor) before any of a release runs, in `install.sh`, `deploy/install-server.sh` and `agos update`; default = newest stable tag, not `main`. Proved with a real cosign v3.1.4 (key-signed bundle: accepted; wrong commit, changed `release.json`, other key, keyless check of a key-signed bundle: refused). |
| 11 base image by digest     | Done for the sandbox (`debian:bookworm-slim@sha256:…`, Dependabot docker ecosystem). Not done: publishing the sandbox image to GHCR.                                                                                                                                                                                                                                                                                                               |
| 9-10, 12 (L3)               | Not done: provenance from a reusable workflow, checksummed third-party installers in `install-server.sh`.                                                                                                                                                                                                                                                                                                                                          |

## Before (2026-11-02): Build L0

| SLSA requirement                                      | State (evidence)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A release artifact exists                             | No. `git tag \| wc -l` = 0; no GitHub release. Users run `install.sh`, which clones the repo at `AGOS_REF` (default `main`, `install.sh:18,124`; `deploy/install-server.sh:341`) and builds web + core **on their own host** (`deploy/install-server.sh`; sec §10.3).                                                                                                                                                                                                                                                                                                             |
| Provenance exists (L1)                                | No. Nothing records which commit, workflow and inputs produced what the user runs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Hosted build platform, signed provenance (L2)         | No. The only "build" is on the target host.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Hardened, isolated build; unforgeable provenance (L3) | No.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Supporting controls                                   | Lockfiles committed (`pnpm-lock.yaml`, `services/core/uv.lock`), `.npmrc` `save-exact=true`, uv `exclude-newer` (`services/core/pyproject.toml:33`), Hermes pinned by commit (`deploy/hermes.pin`), gitleaks binary checked by SHA256 (`.github/workflows/ci.yml:76,85`), sandbox `uv` pinned by version (`docker/sandbox/Dockerfile:15`). Not pinned: actions by tag (`@v4`, `@v6` in `ci.yml`; SHA pins in flight on `eng/ci`), base image `debian:bookworm-slim` by tag (`Dockerfile:12`), NodeSource/uv/tailscale `curl \| bash` and Caddy without checksum (sec §10.2-10.3). |

Public-repo note: GitHub refuses branch protection on this private repo with the current plan (HTTP 403, quality audit
§6), but the public `xag-go/agos-by-xag` gets it free. Protect its `main` and require CI from day one.

## Steps

### To L1 (provenance exists) — one PR

1. Release workflow on `v*` tags in the **public** repo (the private repo is squashed into it by
   `scripts/publish-public.sh`, so releases must be built there).
2. Artifact = `agos-<version>.tar.gz` from `git archive` (what the installer would clone), plus `SHA256SUMS`.
3. Generate provenance for it (step 4 below already gives L2, so do both at once).

### To L2 (hosted build, signed provenance)

4. Build on a GitHub-hosted runner (ephemeral) and attest:
   `actions/attest-build-provenance` (Sigstore-signed, stored in GitHub's attestation store). Permissions only
   `contents: write, id-token: write, attestations: write`.
5. SBOM per release: CycloneDX for npm (`@cyclonedx/cyclonedx-npm --omit dev`) and Python
   (`uv export --frozen --no-dev | cyclonedx-py requirements -`), attached to the release and attested with
   `actions/attest-sbom`.
6. Signed tags: `git tag -s vX.Y.Z` with an SSH or GPG key registered on GitHub (or `gitsign`); the release workflow
   fails unless `git tag -v` passes.
7. All actions pinned by full SHA with a version comment; Dependabot `github-actions` ecosystem (in flight on
   `eng/ci`); `zizmor` on workflows (sec F15).
8. Installer verifies before it runs anything: download tarball + `SHA256SUMS`, `sha256sum -c`, and when `gh` is
   present `gh attestation verify agos-<v>.tar.gz --repo xag-go/agos-by-xag`; default `AGOS_REF` = latest release tag,
   not `main` (`install.sh`, `install.ps1`, `deploy/agos update`).

### To L3 (hardened build)

9. Move provenance generation into a reusable workflow the build steps cannot influence:
   `slsa-framework/slsa-github-generator` generic generator (`generator_generic_slsa3.yml`), or GitHub artifact
   attestations called from a reusable workflow pinned by SHA. The build job only outputs artifact digests.
10. No secrets in the build job; no self-hosted runner for releases (the `fix/ci-runner` work targets GitHub
    runners — keep it that way); `concurrency` per tag; no `pull_request_target`.
11. Pin base images by digest (`debian:bookworm-slim@sha256:…`, the Hermes sandbox image) and publish the sandbox
    image to GHCR from the same workflow with its own provenance, instead of every user building it
    (`scripts/build-sandbox.sh`).
12. Pinned, checksummed third-party installers in `install-server.sh` (signed apt repos where available — already
    done for Docker; uv by version + SHA256; Caddy by version + SHA256 or drop it, sec F7).

## Proposed release workflow (sketch, not yet run)

```yaml
name: Release
on: { push: { tags: ["v*"] } }
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-24.04
    permissions: { contents: write, id-token: write, attestations: write }
    steps:
      - uses: actions/checkout@<sha> # v4
        with: { fetch-depth: 0 }
      - run: git tag -v "$GITHUB_REF_NAME" # signed tag required
      - run: |
          v="${GITHUB_REF_NAME#v}"
          test "$v" = "$(cat VERSION)"
          git archive --prefix="agos-$v/" -o "agos-$v.tar.gz" "$GITHUB_REF_NAME"
          sha256sum "agos-$v.tar.gz" > SHA256SUMS
      - run: <generate sbom-npm.cdx.json and sbom-python.cdx.json>
      - uses: actions/attest-build-provenance@<sha>
        with: { subject-path: "agos-*.tar.gz" }
      - uses: actions/attest-sbom@<sha>
        with: { subject-path: "agos-*.tar.gz", sbom-path: sbom-npm.cdx.json }
      - run: gh release create "$GITHUB_REF_NAME" agos-*.tar.gz SHA256SUMS sbom-*.cdx.json --verify-tag
        env: { GH_TOKEN: "${{ github.token }}" }
```

## Status

| Item                                                           | Status                                                                                                                | Covered by                              |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Release artifact + checksums                                   | FAIL                                                                                                                  | ADD (signed releases for public builds) |
| Signed provenance (L2)                                         | FAIL                                                                                                                  | ADD                                     |
| SBOM                                                           | PARTIAL (in flight `eng/m4-security`: CycloneDX per CI run, `security.yml` job `sbom`; not yet attached to a release) | ADD                                     |
| Signed tags                                                    | FAIL                                                                                                                  | NEW (not in plan text)                  |
| Actions pinned by SHA                                          | FAIL at commit, in flight `eng/ci`                                                                                    | W1-B                                    |
| Installer verifies release, defaults to tag                    | FAIL                                                                                                                  | NEW (sec §10.3 has no fix item)         |
| Base images by digest, sandbox image published with provenance | FAIL                                                                                                                  | NEW                                     |
| Pinned third-party installers (uv, Caddy, NodeSource)          | PARTIAL (Docker apt repo signed)                                                                                      | P4 (sec §10.2-10.3, F7)                 |
| Public `main` protected, CI required                           | FAIL (impossible on private plan)                                                                                     | owner decision + public repo step       |
| L3 isolated provenance                                         | FAIL                                                                                                                  | NEW                                     |

**Current: Build L0. 0 PASS / 10.** L2 needs items 1-8 (about two PRs); L3 adds 9-12.
