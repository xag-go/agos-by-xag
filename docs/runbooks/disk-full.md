# Runbook: the disk is full

A full disk breaks everything at once: the database can't write, backups fail,
updates fail, agents can't save files.

## Symptoms

- Errors with `No space left on device` or `database or disk is full` in
  `agos logs core`.
- Backups or updates fail.
- **Settings → Server & backup** shows little free space.

## 1. Look

```bash
df -h /                                         # and the disk holding agos-data
sudo du -sh ~agos/agos-data ~agos/agos-backups
sudo du -sh ~agos/agos-data/* ~agos/agos-data/hermes/* 2>/dev/null | sort -h | tail
docker system df
sudo journalctl --disk-usage
```

## 2. Free space, safest first

1. **Docker build cache and unused images** (safe; the next sandbox rebuild is
   slower):
   ```bash
   docker builder prune -f
   docker image prune -f
   ```
2. **Old backups.** Lower "keep" in **Settings → Server & backup**, or copy old
   `.agosb` files to another machine and remove them from `agos-backups`.
3. **Old update copies.** `agos-data/system/update-snapshots/update-*` (AGOS
   keeps 3) and `rolled-from-*` there (one per `agos rollback`, never removed by
   AGOS). Remove all but the newest. With too little free disk, `agos rollback`
   refuses and changes nothing, so free space before rolling back.
4. **Old restore copies.** `agos-data.before-restore-*` and `agos-backups/restore-*`
   are full copies of your data. Remove them once you are sure you don't need
   them.
5. **System logs.** `sudo journalctl --vacuum-size=500M`.
6. **Trash.** Deleted workspaces stay 30 days in `.trash`. Empty them from
   **Settings → Server & backup** (Trash).
7. **Your own files.** A workspace's files may be large (downloads, videos).
   Look inside `agos-data/workspaces/<id>/`.

Don't delete anything inside `agos-data/system/` or `agos-data/hermes/`.

## 3. After freeing space

```bash
agos restart
agos status
```

Then make a backup (`agos backup`) to check that writing works again.

## Prevent it

- Keep at least 20 GB free (the installer's minimum) and room for one more
  backup than you keep.
- AGOS tells you (Settings → Errors and a notification) when the data disk
  has less than 10% free for 5 minutes. Act on it before it is full.
