# ADR 0012 — Backup, restore and the move to a server

- Status: accepted (backup/restore); server kit rehearsed, move not done
- Date: 2026-09-25
- Builds on: ADR 0010 (Hermes engine)

> **Since then:** the guided move script described below (`deploy/move.sh`) was
> never shipped. Moving AGOS today is: install on the new machine, copy a backup
> file over, `agos restore <file>`
> ([runbooks/restore-backup.md](../runbooks/restore-backup.md)). The restore check
> is `services/core/scripts/restore_and_verify.py`. The installer is for Ubuntu
> LTS, macOS (Lima) and Windows (WSL 2).

## Backup format

- One file `agos-backup-<utc>.agosb` = gzip tar of:
  - `agos-data/` (workspaces and their files, the database copied with SQLite's online
    backup API, encrypted secrets, master key, global library, automations files);
  - `hermes/profiles/agos-*` for every workspace AGOS knows (SOUL, memory, sessions,
    skills, cron jobs, config, `.env` with the API key and MCP credentials).
- Left out: caches, sockets, locks, logs, sandboxes, `node_modules`, and **every
  `auth.json`** (subscription logins never travel; they are redone once on a new
  machine so one grant is never active on two machines).
- Encrypted with AES-256-GCM in 4 MB chunks under a key from scrypt(backup password)
  (n=2^15, r=8, p=1). Each chunk's associated data binds its index and a last-chunk
  flag, so chunks can't be reordered, dropped or cut off. A `manifest.json` inside holds
  the SHA-256 of every file.
- The password is stored encrypted with AGOS's master key so scheduled backups can run.
  Without the password a backup can't be opened (the owner is told to keep it in a
  password manager).

## Restore

- Only into an **empty** folder (refuses anything else), with no absolute paths,
  `..`, symlinks or hard links (Python's `data` tar filter), and every file checked
  against the manifest hash.
- "Test a restore" (Settings → Server & backup) restores the newest backup into an
  empty temporary folder, compares table row counts with the live database and checks
  every live file is in the backup, then deletes the temp folder. The live data is only
  read.

## Settings → Server & backup

Disk free/total (red above 90% used), AGOS data size, backups folder (outside
`agos-data`, default `../agos-backups`, `AGOS_BACKUP_DIR` to change), password, schedule
(daily / weekly / off), keep N, Back up now, Test a restore, file list, last backup and
last restore test.

## Server kit (step 11) — built and rehearsed, move NOT done

- `deploy/install-server.sh` (Ubuntu Desktop LTS): Docker Engine (official repo), Node 22,
  user `agos` with linger, Hermes pinned (git tag), AGOS core + web built, sandbox image
  built, **systemd services** `agos-core` / `agos-web` (`Restart=always`, enabled at boot,
  run with nobody logged in), sleep/suspend/hibernate masked, lid/idle ignored, GNOME locks
  after 5 min, Tailscale, **ufw: deny all inbound except tailscale0**, unattended
  security upgrades, and a `--check` mode. Web and core listen on 127.0.0.1 only.
- `deploy/https-setup.sh`: Caddy with the Cloudflare DNS module, **bound to the Tailscale IP
  only**, DNS-challenge certificate for `agos.<domain>` (no public port).
- `deploy/move.sh`: lists workspaces and added folders → owner types MOVE → stop AGOS +
  Hermes on the PC → password-protected backup + restore test → copy → restore into an
  empty folder and verify on the server (`services/core/scripts/restore_and_verify.py`) → put in place
  and rewrite added-folder paths after asking (`deploy/place-restore.sh`) →
  `deploy/verify-server.sh` (services, linger, sleep, workspaces, SOUL, files, isolated
  networks, egress proxy, channel lamps, one real agent reply per workspace, firewall,
  nothing listening publicly) → exact provider login command if needed → owner types
  YES → only then offers to delete PC data (types DELETE). Rollback = start the PC again.
- Rehearsal (`deploy/rehearse-in-container.sh`, Ubuntu 24.04 container): Hermes 0.21.4
  installed from the pinned commit, a **copy** of a real backup restored ("Everything
  identical", 65 files), core started on the restored data and served workspace demo (7
  tasks, 1 chat, SOUL, memory). The installer ran end to end in dry-run in the same
  image. A container can't prove systemd at boot, reboot with nobody logged in, Docker
  sandboxes on the server, Tailscale/DNS/HTTPS/ufw, or GNOME lock. These are listed in
  the move checklist and checked by `verify-server.sh` on the real machine.
- Settings → Server & backup shows **Server readiness**: backup password, recent backup that
  restores, last server rehearsal, and what only the owner can do (buy the server,
  Tailscale + DNS, real reboot test).
