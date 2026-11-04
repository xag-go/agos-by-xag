# Troubleshooting

The problems people hit most, each with what you see, why it happens and the
commands that fix it. Commands run on the machine where AGOS is installed (on a
Mac: `limactl shell agos`; on Windows: the Ubuntu terminal). Every error AGOS
shows has a code; [errors.md](errors.md) lists them all.

Still stuck? See [Asking for help](#asking-for-help) at the end.

- [The install stopped](#the-install-stopped)
- [The cage refused to start](#the-cage-refused-to-start)
- [The web page won't open](#the-web-page-wont-open)
- [The model doesn't answer](#the-model-doesnt-answer)
- [Hermes says "Still waiting" or the model is unreachable](#hermes-says-still-waiting-or-the-model-is-unreachable)
- [An update failed](#an-update-failed)
- [Backup and restore](#backup-and-restore)
- [Where the logs are](#where-the-logs-are)
- [Asking for help](#asking-for-help)

## The install stopped

The installer prints `ERROR: ...` and the line it stopped at. Fix what it says
and run **the same command again**: finished steps are skipped. The full log is
`/var/log/agos-install.log` (root only: `sudo less /var/log/agos-install.log`).

### No network, or a download was refused

**You see:** `Could not resolve host`, `Failed to connect`, `Hermes did not install
(network?)`, `Could not download AGOS`, or GitHub's `429 Too Many Requests`.

**Why:** the machine can't reach GitHub, a package mirror, Docker's or Node's
repository, or GitHub limited downloads for a moment.

**Fix:**

```bash
curl -sI https://github.com | head -1        # expect HTTP/2 200
curl -sI https://download.docker.com | head -1
getent hosts github.com || cat /etc/resolv.conf   # DNS
```

Behind a company proxy, export `https_proxy` / `http_proxy` before you run the
installer. For a 429, wait 10 minutes and run it again.

### apt is busy or broken

**You see:** `Could not get lock /var/lib/dpkg/lock-frontend`, `dpkg was
interrupted`, or `Unable to locate package`.

**Why:** Ubuntu's automatic updates run right after a fresh boot and hold apt's
lock; a cut install left dpkg half done; the package lists are old.

**Fix:**

```bash
ps aux | grep -E '[a]pt|[d]pkg'     # wait until these end (often a few minutes)
sudo dpkg --configure -a            # finish a cut install
sudo apt-get update                 # fresh package lists
```

### Not enough memory (below 4 GB) or CPUs

**You see:** `This machine has N MB of memory and N CPU(s). AGOS needs at least 4
GB of memory and 2 CPUs ... Nothing was installed.`

**Why:** the measured minimum ([INSTALL.md, Minimum hardware](INSTALL.md#minimum-hardware)):
AGOS with two workspaces uses up to 1.7 GB, and installing or updating also builds
the web app.

**Fix:** use a bigger machine or VM (8 GB is comfortable). To install anyway,
knowing it will be slow or fail: `AGOS_SKIP_HARDWARE_CHECK=1`. Check what you have:

```bash
free -h && nproc
```

### Not enough disk

**You see:** `Only N GB free on /: AGOS needs 20 GB`.

**Fix:**

```bash
df -h /
sudo docker system prune      # unused Docker images and containers
sudo journalctl --vacuum-size=500M
```

Or install on a bigger disk. After the install, see
[runbooks/disk-full.md](runbooks/disk-full.md).

### AppArmor or bubblewrap

**You see:** `ERROR cage_refused: Workspace isolation (the bwrap cage ...) can't run
on this machine`, with `What to do:` under it.

**Why and fix:** the next section. The installer stops before Hermes and the build,
so nothing else changed.

## The cage refused to start

Code: [`cage_refused`](errors.md#cage_refused).

**You see:** the installer stops with `ERROR cage_refused`; or, after an install
or an update, a workspace's agents don't start, Settings → Errors and Settings →
Server & backup show `cage_refused`, and `agos doctor` shows `- cage: REFUSED`.

**Why:** AGOS runs each workspace's agents inside a cage (bubblewrap, `bwrap`) so
they can't reach this machine's Docker or another workspace's
([ADR 0025](adr/0025-workspace-isolation.md)). The cage is required: when it can't
be built, AGOS starts no agents rather than start them without it. The usual
causes, and what the installer's message then tells you to run:

| Cause                                                                     | Fix                                                                                                                         |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| bubblewrap is not installed                                               | `sudo apt-get install -y bubblewrap` (dnf, zypper, pacman, apk: the installer prints your system's command)                 |
| Ubuntu 24.04 restricts user namespaces and bwrap has no AppArmor profile  | `sudo bash ~agos/agos/deploy/bwrap-apparmor.sh`                                                                             |
| bwrap's AppArmor profile is there but not loaded                          | `sudo apparmor_parser -r -W /etc/apparmor.d/bwrap-userns-restrict` (it prints why when it can't)                            |
| the admin disabled that profile                                           | `sudo rm /etc/apparmor.d/disable/bwrap-userns-restrict && sudo apparmor_parser -r -W /etc/apparmor.d/bwrap-userns-restrict` |
| the kernel has user namespaces off (Debian, some hardened kernels)        | `echo 'kernel.unprivileged_userns_clone = 1' \| sudo tee /etc/sysctl.d/60-agos-userns.conf && sudo sysctl --system`         |
| `user.max_user_namespaces` is 0                                           | `echo 'user.max_user_namespaces = 15000' \| sudo tee /etc/sysctl.d/60-agos-userns.conf && sudo sysctl --system`             |
| AGOS runs inside a container or a locked-down VPS without user namespaces | install AGOS on a virtual machine or a server you control                                                                   |

Check it yourself, as the AGOS user (prints the cause and the fix when it fails):

```bash
sudo bash ~agos/agos/deploy/cage-setup.sh self-test agos
```

Then run the installer again, or, on an installed AGOS, `agos restart`: the
agents start inside the cage.

**Running without the cage** is possible only on purpose, for a machine that can't
run it: install with `--no-cage` (or set `AGOS_SANDBOXD=off` in the `agos-core`
service). Every workspace's agents can then reach this machine's Docker, which is
as good as full control of the server. Settings → Server & backup and `agos doctor`
say so for as long as it lasts. To turn the cage back on: remove
`AGOS_SANDBOXD=off` (`sudo systemctl edit agos-core`, or the unit file), then
`sudo systemctl daemon-reload && agos restart`.

## The web page won't open

**You see:** `http://localhost:3000` doesn't load, or another device shows "AGOS
opens only on this machine or over the owner's Tailscale."

**Why:** a service is down, another program uses the port, or the address you
used is not one AGOS allows.

**Fix:**

```bash
agos status                         # which service isn't running
agos logs web                       # or: agos logs core
agos restart
sudo ss -ltnp | grep -E ':(3000|8766) '   # who listens on AGOS's ports
```

AGOS listens on 127.0.0.1 only: web on port 3000, core on 8766. If another program
holds one of them, stop that program; AGOS's own ports are fixed.

- **On the machine itself**: use `http://localhost:3000` (or `agos open`), not
  the machine's LAN address: anything but localhost is refused.
- **On a Mac**: after a restart start the VM first: `agos vm-start`
  (`limactl list` shows it).
- **From your phone or another computer**: only through Tailscale. Turn it on in
  **Settings → Access** (on the machine itself), sign in to Tailscale, and use the
  address that card shows. A tailnet address that is still refused is not in the
  allowed list: turn the card off and on again, or add it by hand:
  ```bash
  sudo systemctl edit agos-web
  # [Service]
  # Environment=AGOS_ALLOWED_HOSTS=<machine>.<tailnet>.ts.net
  # Environment=AGOS_TAILSCALE_USERS=<your Tailscale login>
  agos restart
  ```
  Check Tailscale itself with `tailscale status` and `tailscale serve status`.

More in [runbooks/core-down.md](runbooks/core-down.md).

## The model doesn't answer

**You see:** agents never reply, reply "couldn't connect to the AI model", or a
chat shows `service_failed`.

**Why:** no model provider yet, a wrong or expired key, no credit left at the
provider, or a model name the provider doesn't have.

**Fix:**

1. **Settings → Models**: add a provider or test its key again (AGOS asks Hermes,
   which tries the key with the provider). A fresh install has no provider.
2. Check that the workspace's default model is one that provider offers.
3. Look at what Hermes said:
   ```bash
   agos logs <workspace id>      # agos status lists the ids
   ```
   `401`/`invalid api key` = the key; `402`/`insufficient credit` = the account;
   `404`/`model not found` = the model name; `429` = the provider's rate limit
   (wait a minute).
4. Signed in with a provider account (Claude, OpenAI) instead of a key: sign in
   again in Settings → Models when it says the sign-in expired.

## Hermes says "Still waiting" or the model is unreachable

**You see:** a chat fills with `⏳ Still waiting for the other Hermes process on
this session (Ns)...` after a restart; or one answer shows "Thinking…" for many
minutes while the provider is down.

**Why:** both come from Hermes, the engine behind the agents, not from AGOS's own
code. After a gateway restart, Hermes waits up to ~5 minutes for the old process's
claim on the conversation; with the provider down, Hermes retries for a long time
before it gives up. AGOS has proposed both fixes to Hermes:
[dead-session-lease-on-restart.md](hermes-proposals/dead-session-lease-on-restart.md)
and [model-unreachable-retry-budget.md](hermes-proposals/model-unreachable-retry-budget.md).

**Fix:** for "Still waiting", wait: the answer resumes by itself within about 5
minutes. For an unreachable model, check the provider's status page and Settings
→ Models; a fallback model (Settings → General) lets agents go on while one is
down. If a workspace stays stuck, `agos logs <workspace id>` and
[runbooks/hermes-gateway-down.md](runbooks/hermes-gateway-down.md).

## An update failed

**You see:** `agos update` or the Settings button ends with an error, or AGOS goes
back to the release it was on.

**Why:** usually the network (the repository, a package download), memory during
the build, or a full disk. A failed update rolls back by itself: the old release,
the old database copy and the old Hermes.

**Fix:**

```bash
agos status                                         # the release you run now
sudo cat ~agos/agos-data/system/agos-update.json    # what failed, rolled_back
agos update                                         # try again later
agos rollback --yes                                 # go back to before the last update by hand
```

Step by step: [runbooks/update-failed.md](runbooks/update-failed.md).

## Backup and restore

**You see:** Settings → Server & backup says "No backup password is set" or "the
newest backup is N hours old"; or you need your data back.

**Fix:**

- Set a backup password in **Settings → Server & backup** (or run `agos backup`
  once, which asks for one). Without it AGOS makes no backups.
- Make one now: `agos backup`. Files land in `~agos/agos-backups/*.agosb`; copy
  them off the machine too.
- Test that a backup restores: **Settings → Server & backup → Test a restore**.
- Put one back: `agos restore ~agos/agos-backups/<file>.agosb` (asks for its
  password; your current data is kept aside, never overwritten). Keys are not in
  backups: enter them again in Settings → Models.

Step by step: [runbooks/restore-backup.md](runbooks/restore-backup.md). Backups
failing because the disk is full: [runbooks/disk-full.md](runbooks/disk-full.md).

## Where the logs are

| What                          | Command                                                           |
| ----------------------------- | ----------------------------------------------------------------- |
| The core                      | `agos logs core`                                                  |
| The web                       | `agos logs web`                                                   |
| A workspace's Hermes (agents) | `agos logs <workspace id>`                                        |
| AGOS's warnings and errors    | Settings → Errors, and the workspace's **Log** tab                |
| An update                     | `agos status`, `sudo cat ~agos/agos-data/system/agos-update.json` |
| The installer                 | `sudo less /var/log/agos-install.log`                             |

The full table: [operations.md, Logs](operations.md#logs).

## Asking for help

1. Run `agos doctor`: it reports versions, health, workspace isolation (the
   cage), backups, updates and the newest errors.
2. Make the file for an issue:
   ```bash
   agos doctor --bundle
   ```
   It writes `agos-diagnostics-<time>.md` in your home folder. It holds no keys
   and none of your workspaces' content; read it before you share it.
3. Open a **Bug report** on GitHub, paste the file and the error code you saw
   ([errors.md](errors.md)). Security problems: never in a public issue, see
   [SECURITY.md](../SECURITY.md).
