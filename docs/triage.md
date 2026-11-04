# Triage: what happens to an issue

How the maintainers sort new issues and pull requests, so a report gets an answer
and the right fix gets done first. The labels live in
[`.github/labels.json`](../.github/labels.json); `scripts/sync-labels.sh --apply`
creates them on GitHub (it only creates or updates, never deletes).

## The path of an issue

1. **New**: the issue forms add `bug` or `enhancement` and `needs-triage`.
2. **First look** (aim: within a week): a maintainer reads it and either
   - asks for what is missing and sets `needs-info` (the AGOS version from
     `agos version`, the steps, the error code, the diagnostics from Settings →
     Errors → Copy diagnostics). An issue in `needs-info` with no answer for 30
     days is closed; it can be reopened any time;
   - closes it as `duplicate` (linking the first one), `wontfix` (saying why), or
     moves a question to Discussions;
   - or confirms it: `confirmed`, one **priority**, at least one **area**, and the
     **os/** label when it is about one system. `needs-triage` comes off.
3. **Work**: `confirmed` issues are taken by priority. `good first issue` marks
   small, well-described ones; `help wanted` ones a maintainer will review a PR for.
4. **Done**: the PR that fixes it says `Fixes #N` and adds a CHANGELOG line; the
   issue closes when it merges and ships in the next release
   ([releases.md](releases.md)).

Security problems never go through public issues: [SECURITY.md](../SECURITY.md).
One posted by mistake is hidden at once and handled privately.

## Priorities

| Label | Means                                                               | When it is fixed                                |
| ----- | ------------------------------------------------------------------- | ----------------------------------------------- |
| `P0`  | data loss, a security hole, or AGOS down for every install          | now: a patch release as soon as it is fixed     |
| `P1`  | a main flow broken (install, update, chat, cards, backups) for many | in the next release                             |
| `P2`  | broken with a workaround, or only some installs                     | when its turn comes                             |
| `P3`  | cosmetic, rare, or nice to have                                     | when someone has time; often `good first issue` |

## Labels

| Group    | Labels                                                                                                                |
| -------- | --------------------------------------------------------------------------------------------------------------------- |
| Kind     | `bug`, `enhancement`, `documentation`, `question`, `dependencies`                                                     |
| State    | `needs-triage`, `needs-info`, `confirmed`, `duplicate`, `wontfix`                                                     |
| Help     | `good first issue`, `help wanted`                                                                                     |
| Priority | `P0`, `P1`, `P2`, `P3`                                                                                                |
| Area     | `area/install`, `area/update`, `area/web`, `area/core`, `area/hermes`, `area/sandbox`, `area/channels`, `area/backup` |
| System   | `os/linux`, `os/macos`, `os/windows`                                                                                  |
| PR gates | `skip-changelog`, `coverage-exempt`, `api-breaking` (CI reads these, see [CI.md](CI.md))                              |

## What makes a report easy to act on

- `agos version` (the version and the commit) and the release channel (`agos channel`).
- The steps, the error message and its **code** ([errors.md](errors.md)).
- The diagnostics (Settings → Errors → Copy diagnostics, or `agos doctor --bundle`):
  versions, health and recent errors, with keys and personal content removed. Read
  it before posting.
