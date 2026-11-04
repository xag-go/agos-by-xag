# Operations

How to keep an AGOS installation healthy: backups, updates, logs and
monitoring. For problems, go to the [runbooks](runbooks/README.md).

Paths below use the installer's defaults: the AGOS user is `agos`, its data is
`~agos/agos-data` and its backups are `~agos/agos-backups`. `agos status` prints
the real paths of your machine.

## Backups

**What a backup holds.** One encrypted `.agosb` file with AGOS's database, every
workspace's files, and Hermes's own backup of every workspace root. It holds
**no keys**: after a restore you enter your keys again (the restore test tells
you which). It is checked against the source after it is written.

**Turn backups on.** Scheduled backups run only once a backup password is set.
A fresh install has none, so it makes no backups until you set one:

- **Settings → Server & backup**: set the password (10 characters or more),
  pick the schedule (daily, weekly or off) and how many to keep (1–60). The
  default is daily, keep 7.
- Or run `agos backup` once in a terminal: it asks for a password the first time.

Keep the password safe. Without it a backup can't be opened.

**Back up now.** `agos backup`, or **Settings → Server & backup → Back up now**.

**Test a restore.** **Settings → Server & backup → Test a restore** opens the
newest backup in a temporary folder beside the backups (on the data disk, never
`/tmp`) and checks it on its own terms, without touching your data: every file
against the backup's own list, every table there, and SQLite's own check of the
restored database. What you did since the backup (new chats, new files) is
fine. AGOS also runs this test by itself once a month (unless you ran one) and
tells you when it fails. With less free disk than about twice AGOS's data, the
test is skipped (you are told, at most once a week) and tried again the next day.

**Warnings.** With no backup password, no backup at all a day after the password
was set, or when the newest backup is older than its schedule allows (daily: 48
hours, weekly: 8 days) while the schedule is on, Settings → Server & backup shows
it at the top, and you get it in Settings → Errors and as a notification (once a
day at most). A scheduled backup that fails is an error there too.

**Old copies.** `agos restore` keeps your data as it was in
`agos-data.before-restore-<time>`. The newest of those always stays; older ones
are removed 14 days after the `<time>` in their name. A restore that crashed
half-way leaves `agos-backups/restore-<time>`; it is removed a day after its
`<time>`.

**Keep a copy elsewhere.** Backups sit next to the data, on the same disk. If
the disk dies, they die with it. Copy the newest `.agosb` to another machine or
drive regularly. On a Mac the files live inside the VM; see
[INSTALL.md](INSTALL.md#macos) for how to copy one out.

**Restore.** See [runbooks/restore-backup.md](runbooks/restore-backup.md).

## Updates

**AGOS.** `agos update` (or **Settings → General → Update AGOS → Check Update →
Update now**):

1. checks for a new release (`agos update --check` stops here);
2. backs up: the full backup when a password is set, and always a rollback
   snapshot (the database and the Hermes roots' settings) in
   `agos-data/system/update-snapshots/update-<time>/` (0700; it holds the roots'
   keys files, so it is never in the backup folder nor in a backup);
3. stops AGOS, takes the new release, moves Hermes to the commit that release
   pins, rebuilds the web and the core, rebuilds the sandbox image if it changed;
4. starts AGOS and waits until the core and the web answer.

If any step fails, it rolls back by itself to the old release, the old database
copy, the old Hermes and the Hermes roots' old settings, and says what failed.
For 10 minutes after a good update, a watch checks every minute that the core
(`/health?deep=1`), the web and every workspace gateway that ran before still
answer; three failed checks in a row roll back the same way. A full disk alone
is not a reason (it is an alert: a rollback needs room), nor a gateway of a
workspace archived since, and `agos stop`, `restart`, `restore` and `uninstall`
end the watch. The last three `update-*` snapshots are kept. AGOS is down for a
few minutes during an update.

**Go back.** `agos rollback` takes AGOS back to the release before the last
update (`--to <time>` for an older `update-<time>` snapshot): its code, its
Hermes, its database and the roots' settings. Today's database and roots'
settings are kept first in `update-snapshots/rolled-from-<now>/` (never removed
by AGOS); with too little free disk to keep them, nothing is changed. It is
refused when AGOS no longer runs the release that update made (rolled back
already, or updated since); `--force` goes back anyway. Cron jobs keep their
run state (a job that ran since does not run again). See
[runbooks/update-failed.md](runbooks/update-failed.md).

**Try it first.** `agos staging up --ref <commit>` runs that release beside
yours on a copy of your data ([runbooks/staging.md](runbooks/staging.md)).

**Hermes.** **Settings → General → Hermes update** moves Hermes to a newer
release that passed AGOS's contract check, without changing AGOS. The manual
procedure is [hermes-upgrade.md](hermes-upgrade.md). Never run a plain
`hermes update` on an AGOS machine.

**The system.** Keep Ubuntu up to date. The installer's `--server` option turns
on automatic security updates.

## Logs

| What                       | Where                                        | How to read it                         |
| -------------------------- | -------------------------------------------- | -------------------------------------- |
| The core                   | journald, unit `agos-core`                   | `agos logs core`                       |
| The web                    | journald, unit `agos-web`                    | `agos logs web`                        |
| The webhook relay          | journald, unit `agos-hooks`                  | `agos logs hooks`                      |
| A workspace's Hermes       | `<data>/hermes/agos-<workspace>/logs/*.log`  | `agos logs <workspace id>`             |
| AGOS's warnings and errors | the database (`system_log`, the newest 5000) | the workspace's **Log** tab            |
| An update                  | `<data>/system/agos-update.json`             | `agos status`, or the card in Settings |
| The installer              | `/var/log/agos-install.log` (root only)      | `sudo less /var/log/agos-install.log`  |

journald keeps logs within the system's own limits (on Ubuntu, 10% of the disk
by default, at most 4 GB). Hermes rotates its own log files.

## Retention

Once a day the core's job `retention.daily` deletes AGOS's own old machine
records ([ADR 0026](adr/0026-job-queue-and-retention.md),
`services/core/src/agos_core/background/retention.py`):

| Records                                       | Kept for |
| --------------------------------------------- | -------- |
| `system_log` (AGOS's warning and error lines) | 90 days  |
| `op_runs` (finished operation runs and keys)  | 180 days |
| delivered `outbox` rows (failed ones stay)    | 30 days  |
| finished `jobs` (done and dead letters)       | 30 days  |
| journals of completed sagas                   | 90 days  |
| `slo_samples` (measured SLIs)                 | 400 days |

Your content is never deleted by it: chats, cards, the Inbox, activity, files,
settings and everything Hermes keeps stay until you delete them. These are the
default periods; Settings has no switch for them. A failed run is retried three
times, then it is an error in **Settings → Errors**.

## Schema changes

Database migrations follow **expand, then contract**, so the previous release
still runs on the new schema and a rollback is safe:

1. **Expand**: a migration only adds tables, columns and indexes. A table rebuild
   (SQLite's recipe: create `x_new`, copy, drop `x`, rename) keeps every column.
2. Ship the release that stops reading the old table or column.
3. **Contract**: a later migration removes it, and names each removal on a line of
   its own: `-- agos: contract <table>` or `-- agos: contract <table>.<column>`.
   A rename is a new column added in step 1, then a contract of the old one.

`services/core/scripts/migration_check.py` applies every migration since 140
on top of the ones before it and fails CI when one removes a table or column
that no contract line names. Never edit a shipped migration; add a new one.

## Monitoring

What to look at, from quickest to deepest:

1. `agos status`: each service, whether the core and the web answer, the number
   of workspaces and running gateways, versions, paths.
2. **Settings → Server & backup**: last backup, free disk space.
3. **Settings → Health**: Hermes's own `status` and `doctor` for every workspace.
4. **Settings → Errors**: AGOS's own errors (core and web) and each
   workspace's Hermes errors, grouped into issues with a count, the version and
   the traceback ([error-monitoring.md](error-monitoring.md)).
5. Each workspace's **Log** tab: AGOS's warnings and errors, and Hermes's.

Health endpoints, for your own checks:

- core: `curl -fsS http://127.0.0.1:8766/health` returns `{"ok": true}`;
  `/health?deep=1` also checks the database, the disk and the background loops
  (HTTP 503 when one fails);
- web: `curl -fsS http://localhost:3000/api/health` (it asks the core too).

What AGOS does by itself:

- systemd restarts a crashed core, web or relay after 3 seconds.
- A broken Hermes contract is reported in the Log, in the Co-Founder's chat and
  on your phone.
- Usage limits (Settings → Usage & limits) warn and then pause work.
- A new error, an error marked fixed that comes back, or a burst of the same
  error is told to you (event `agos.error` in Settings → Notifications) and
  listed in **Settings → Errors**. Unhandled route errors answer with a
  reference (`ref <id>`) that is on the issue too.
- Free disk (on the data folder) or free memory under 10% for 5 minutes is an
  error in Settings → Errors and a notification; again only after it was fine.
- Every week SQLite checks AGOS's database (`PRAGMA integrity_check` and the
  foreign keys); a problem is an error in Settings → Errors.
- The dead-man: `agos-deadman.timer`, outside the core, checks the core's
  `/health` every minute. Down for 3 minutes, it sends you one Telegram message
  straight from the Bot API, and one more when the core is back up. Details:
  [error-monitoring.md](error-monitoring.md#dead-man-the-core-itself-is-down).

What it does **not** do yet:

- The dead-man runs on the same machine: if the whole machine is down, nobody is
  told. If you depend on AGOS, add an outside check too, for example a cron job
  on another machine that runs `curl` against the health endpoint over
  Tailscale and alerts you.
- Backups stay on this machine. Copy one elsewhere yourself (see above).

## Asking for help

`agos doctor --bundle` writes a report for a GitHub issue (versions, health,
the newest errors, backup and update state, Labs switches, AGOS's settings
without keys). It holds no workspace, chat or person names and no keys; read it
before you attach it. **Settings → Errors → Copy diagnostics** copies the same
report.

## Labs

**Settings → General → Labs** lists new things that are still being tried, each
with a switch (the Co-Founder can flip them too, with Undo). Off is the kill
switch. On the machine, `AGOS_FLAG_<NAME>=1` or `=0` in the core's environment
forces one (the switch then shows it can't be changed).

## Resources

- Memory: about 0.7 GB with no workspace, 1.5–2 GB with one, 4–5 GB with six.
  Building the web during an update needs 2–3 GB more for a few minutes.
- Disk: the install itself takes about 12 GB. Each backup of a fresh AGOS is
  about 180 MB; yours grow with your files and chats.
- AGOS's services and the sandboxes have no memory or CPU caps of their own.
  On a small machine, keep an eye on `free -h` and `docker stats`.
- `docker builder prune` frees the Docker build cache (the next sandbox rebuild
  is then slower).

## Access and safety

- AGOS listens on 127.0.0.1 only. Other devices reach it only through your
  Tailscale (**Settings → Access**).
- On an always-on machine, install with `--server`: no sleep, a firewall that
  lets in only Tailscale, automatic security updates.
- Use a dedicated machine user (the installer's default `agos` user), disk
  encryption, and backups copied off the machine.
