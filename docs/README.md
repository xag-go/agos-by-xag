# AGOS documentation

Start with the [README](../README.md) for what AGOS is and how to install it.

## Using AGOS

- [User guide](user-guide.md): every screen, in a few lines each.
- [Glossary](glossary.md): the words AGOS uses.
- [Install](INSTALL.md): every installer question, flag and platform.
- [Instant automations](guides/instant-automations.md): start work from a
  webhook.

## Running AGOS

- [Operations](operations.md): backups, updates, logs, monitoring.
- [Error messages](errors.md): every error code, what it means and what to do.
- [Triage](triage.md): how issues are sorted, priorities and labels.
- [Releases](releases.md): versions, channels (stable, beta, main), signed
  releases, cutting a release.
- [Error monitoring](error-monitoring.md): Settings → Errors, error alerts and
  the dead-man that tells you when the core is down.
- [Runbooks](runbooks/README.md): core down, Hermes gateway down, restore a
  backup, update failed or rollback, disk full.
- [Hermes upgrades](hermes-upgrade.md): moving to a newer Hermes Agent.

## Building AGOS

- [Getting started](guides/getting-started.md): from a clone to a running AGOS.
- [How to add a feature](guides/how-to-add-a-feature.md): the step-by-step,
  with the Definition of Done.
- [Testing](guides/testing.md): checks, CI, guard tests, e2e, the install test.
- [Architecture](../ARCHITECTURE.md): how it is built, and the target design.
- [Who owns what: AGOS and Hermes](hermes-ownership.md): what AGOS may store.
- [Decision records (ADRs)](adr/README.md): why things are the way they are.
- Upstream proposals, changes we suggest to Hermes Agent:
  [one subscription login for several homes](upstream/shared-subscription-login.md),
  [a minimal Docker capability set](upstream/terminal-docker-cap-minimize.md).
- [Contributing](../CONTRIBUTING.md) · [Security](../SECURITY.md) ·
  [Code of Conduct](../CODE_OF_CONDUCT.md) · [Changelog](../CHANGELOG.md)

Docs are checked by `python3 scripts/check-docs.py` (relative links and the
repository paths they name).
