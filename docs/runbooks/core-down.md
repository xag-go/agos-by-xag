# Runbook: AGOS doesn't open (core or web down)

## Symptoms

- http://localhost:3000 doesn't load, or shows an error on every page.
- `agos status` says `core NOT answering`, or a service is not `active`.

## 1. Look

```bash
agos status
agos logs core        # Ctrl-C to stop following
agos logs web
```

Read the last error lines. Most problems say what they are.

## 2. Restart

```bash
agos restart
agos status
```

systemd already restarts a crashed service after 3 seconds. If `agos status`
shows the core going `activating` and back, it is crash-looping: go to step 3.

## 3. Common causes

| The log says                                  | Do this                                                                                            |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `database is newer` / refuses the database    | The code is older than the data (a rollback went wrong). See [update-failed.md](update-failed.md). |
| `No space left on device`, `disk I/O error`   | See [disk-full.md](disk-full.md).                                                                  |
| A config error naming a variable (`AGOS_…`)   | Fix that variable in `/etc/agos/agos.conf` or the unit's environment, then `agos restart`.         |
| `Address already in use` (8766, 3000 or 8767) | Another program holds the port: `sudo ss -ltnp \| grep -E ':(8766\|3000\|8767)'`. Stop it.         |
| `ModuleNotFoundError`, a missing build        | The install is incomplete. Run the installer again: finished steps are skipped.                    |
| The web log says it can't reach the core      | Fix the core first; the web follows.                                                               |

## 4. The core runs but a screen fails

Open **Settings → Errors**: the failing route's error is listed there with its
traceback. Then the workspace's **Log** tab. If both show
nothing, the error may be only in journald: `agos logs core`.

## 5. Still down

1. Make sure the machine has a working disk and memory: `df -h`, `free -h`.
2. Run the installer's checklist: `agos check`.
3. Run the installer again (`curl … | bash`, or `./install.sh` from a copy). It
   keeps your user and data and redoes only what is missing.
4. Report it with `agos version` and the last 50 lines of `agos logs core`.
