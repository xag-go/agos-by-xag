# Runbook: an update failed, or you need to go back

## An AGOS update failed

`agos update` (and the Settings button) roll back by themselves: the old
release, the old database copy, the old Hermes and the Hermes roots' old
settings (`roots.tar`), rebuilt and started. For 10 minutes after a good
update, a watch rolls back the same way when the core (its database or a
background loop), the web or a gateway of a still-active workspace stops
answering (`agos-update.json`: `watch` is `rolled-back`). A full disk alone is
an alert, never a rollback; `agos stop`, `restart` and `restore` end the watch
(`watch` is `stopped`).

1. See where you are:
   ```bash
   agos status                                   # the release you run now
   sudo cat ~agos/agos-data/system/agos-update.json   # what failed, rolled_back
   ```
2. If `rolled_back` is `true` and AGOS answers, you are safe on the old
   release. Read `error` for the step that failed:
   - **the backup failed**: nothing was changed. Fix the backup first (often
     disk space, see [disk-full.md](disk-full.md)).
   - **the build** or **the sandbox image**: often a network or memory problem.
     Free memory and try again later.
   - **could not reach the repository**: a network problem. Try again later.
   - **the rollback did not start**: there was not enough free disk to keep
     today's database first, so nothing of the data was changed. Free some space
     ([disk-full.md](disk-full.md)), then `agos rollback`.
3. Try again with `agos update`. If it fails the same way twice, report it with
   the `agos-update.json` content.

## The rollback itself didn't bring AGOS back

`agos-update.json` says `AGOS did not come back by itself`.

1. Follow [core-down.md](core-down.md) first.
2. Try `agos rollback --yes` once more. If the core still refuses the database
   ("newer database"), put the rollback copy back by hand. The snapshots are in
   `~agos/agos-data/system/update-snapshots/update-<time>/` (`agos.db` and
   `agos.sha`, the release they belong to):
   ```bash
   agos stop
   sudo -iu agos
   snap=$(ls -d ~/agos-data/system/update-snapshots/update-* | tail -1)
   git -C ~/agos checkout --detach "$(cat "$snap/agos.sha")"   # the app folder; agos status shows it
   cp "$snap/agos.db" ~/agos-data/system/agos.db
   rm -f ~/agos-data/system/agos.db-wal ~/agos-data/system/agos.db-shm
   exit
   agos start
   ```
   Check the app folder's path in `/etc/agos/agos.conf` (`AGOS_APP`) before
   running `git checkout`.
3. Still down: restore the backup made at the start of the update
   ([restore-backup.md](restore-backup.md)).

## A release came up, but something is wrong after it

```bash
agos backup          # optional: one more backup of today's data
agos rollback        # back to the release before the last update
agos status
```

`agos rollback` lists what it will do and asks first (`--yes` skips the
question; `--to <time>` picks an older `update-<time>` snapshot). It puts back
that snapshot's code, Hermes, database and the roots' settings; cron jobs keep
their run state, so none runs twice. What changed since the update is not lost:
it is kept first in `~agos/agos-data/system/update-snapshots/rolled-from-<now>/`
(`agos.db`, `roots.tar`, `agos.sha`), one folder per rollback, never removed by
AGOS (delete old ones by hand when you no longer need them). If there is not
enough free disk for that copy, nothing is changed.

A second `agos rollback` is refused: AGOS already runs the older release, and
putting that update's database back again would replace today's. Likewise after
a later update (`--to` an older snapshot). `--force` goes back anyway (today's
data is still kept aside first). Report what went wrong, so the next release
fixes it.

## A Hermes update failed

The Hermes update button rolls the Hermes code back by itself when it fails
before a gateway ran the new code. Otherwise, follow
[hermes-upgrade.md, section 3](../hermes-upgrade.md#3-rollback) (code and data
together). If this AGOS release needs the newer Hermes, roll AGOS back too.
