# Runbook: try a release on a staging copy

A staging copy is a second AGOS on the same machine, on a copy of your newest
backup. You use it to try a release (or a risky change) before it reaches your
real AGOS. It is quiet: its scheduled jobs are paused, no agent picks up its
copied Kanban cards by itself (Hermes's dispatcher is off in every staging
root), its automations and channels are off, it sends nothing to your phone,
and it has no keys (a backup holds none), so no Telegram bot runs in it. Every
staging root's settings, member profiles, cron jobs and Kanban board are
rewritten to staging's own folders, and the refresh stops if any still names
your real data.

It needs about as much disk as your data and 2–3 GB more memory while it runs.

## Start it

```bash
agos backup                        # staging is a copy of the newest backup
agos staging up                    # the release you run now
agos staging up --ref <commit>     # or another release (a commit or branch)
```

The first `up` makes a checkout in `~agos/agos-staging/app`, builds it, asks
the backup's password and restores the backup into `~agos/agos-staging/data`.
Open it at `http://localhost:3100` on the machine (over SSH:
`ssh -L 3100:127.0.0.1:3100 <machine>`).

- Its workspaces' Hermes roots are named `stg-<workspace>`, its sandboxes use
  their own networks and egress proxy (`agos-stg-egress`): nothing of your real
  AGOS is touched.
- To try agents, enter a test key in the staging copy's Settings → Keys. The
  copy shares Hermes's install and shared home (provider logins) with your
  real AGOS: change logins in your real AGOS only.
- Its Update button refuses: move it with `agos staging refresh --ref`.

## Look at it

```bash
agos staging status
journalctl -u agos-staging-core -n 100
```

## Fresh data or another release

```bash
agos staging refresh               # the newest backup again (staging's data is replaced)
agos staging refresh --ref <commit>
```

## Promote

When the release works on staging, update your real AGOS to it: `agos update`
(the release branch), and `agos rollback` if it goes wrong after all.

## Stop it

```bash
agos staging down                  # stops it (its gateways no longer start at boot); its data stays
agos staging down --purge          # removes the copy, its units, gateways and sandboxes
```

A scripted refresh can pass the backup's password as `AGOS_BACKUP_PASSWORD`
(`sudo` keeps that one variable). A refresh that fails leaves no decrypted
copy behind.
