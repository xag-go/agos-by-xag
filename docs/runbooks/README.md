# Runbooks

Short, step-by-step fixes for the problems an AGOS machine can have. Each one
says how to recognise the problem, what to check, and what to do.

| Problem                                       | Runbook                                          |
| --------------------------------------------- | ------------------------------------------------ |
| AGOS doesn't open, or the core doesn't answer | [core-down.md](core-down.md)                     |
| One workspace's agents don't answer           | [hermes-gateway-down.md](hermes-gateway-down.md) |
| You need your data back from a backup         | [restore-backup.md](restore-backup.md)           |
| An update failed, or you need to go back      | [update-failed.md](update-failed.md)             |
| The disk is full or nearly full               | [disk-full.md](disk-full.md)                     |
| You want to try a release on a copy first     | [staging.md](staging.md)                         |

Before you start any of them:

1. Run `agos status` and keep its output. It shows what runs and where the
   data is.
2. Don't delete folders by hand. AGOS keeps your old data aside on purpose
   (`agos-data.before-restore-*`, `agos-data/system/update-snapshots/`).
3. When you report a problem, include `agos version` and the last lines of
   the log the runbook points to. Remove keys and personal data first.

Paths use the installer's defaults: the AGOS user is `agos`, the data is
`~agos/agos-data`, backups are `~agos/agos-backups`.
