# Runbook: restore a backup

Use this when data was lost or broken, or to move AGOS to another machine.

## Before you start

- You need the `.agosb` file and its backup password.
- A restore replaces the whole AGOS data (every workspace). Your current data
  is **kept aside**, never overwritten.
- Keys are not in a backup. Keep your provider keys at hand to enter them again.

## 1. Pick the backup

```bash
ls -lt ~agos/agos-backups/*.agosb | head
```

Not sure a file is good? Test it first in **Settings → Server & backup → Test a
restore** (it checks the newest backup without touching your data).

## 2. Restore

In a terminal (it asks for the backup's password):

```bash
agos restore ~agos/agos-backups/<file>.agosb
```

What it does:

1. opens and checks the backup in a temporary folder; if it is incomplete,
   nothing changes;
2. stops AGOS and every workspace gateway;
3. moves your current data to `agos-data.before-restore-<time>`;
4. puts the backup in place and starts AGOS;
5. if placing fails, it puts your old data back and starts AGOS again.

## 3. After the restore

1. Open AGOS. Check that your workspaces are there.
2. Enter your keys again: **Settings → Models**, and each workspace's
   **Settings → Keys** and **Connections**.
3. Send a message in one chat and check the agent answers.
4. When everything is right, you may remove the old copy
   (`agos-data.before-restore-<time>`). It is a full copy of your data and
   takes disk space. AGOS removes it by itself 14 days after the `<time>` in its
   name, unless it is the newest such copy. Copy it elsewhere if you need it
   longer.

## Moving to another machine

1. Install AGOS on the new machine (one command, see [INSTALL.md](../INSTALL.md)).
   Add `--no-start` if you want to restore before first use.
2. Copy the `.agosb` file over (for example with `scp`).
3. `agos restore <file>` on the new machine.
4. Stop AGOS on the old machine (`agos stop`), so the same Telegram bots and
   automations don't run twice.

## If the restore fails

- **Wrong password**: nothing changed. Try again.
- **"could not be opened or is incomplete"**: nothing changed. Try an older
  backup.
- **"Restored, but AGOS is not answering"**: see [core-down.md](core-down.md).
  Your previous data is still in `agos-data.before-restore-<time>`. To go back
  to it: `agos stop`, move the restored `agos-data` aside, rename the
  `before-restore` folder to `agos-data`, `agos start`.
