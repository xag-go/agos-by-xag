# Installing AGOS

AGOS runs on **Linux**. On a Mac it runs inside a small Ubuntu virtual machine,
on Windows inside WSL 2 (Windows's own built-in Linux). There is one installer
underneath for all three (`deploy/install-server.sh`), so AGOS behaves the same
everywhere, and you always open it at **http://localhost:3000**.

**Tested:** Linux, Ubuntu 24.04 server on x86, in a VM: a fresh install, update
and uninstall (`deploy/test-install-vm.sh`), and AGOS running a small load with
4 GB and 2 CPUs ([Minimum hardware](#minimum-hardware)). **Preview, not yet tested:** macOS (Lima) and
Windows (WSL 2): their installers exist but have not been run on a real Mac or
Windows PC yet. Ubuntu 22.04 and ARM are accepted by the installer but not tested
yet either.

- [Minimum hardware](#minimum-hardware)
- [Linux](#linux) · [macOS](#macos) · [Windows](#windows)
- [The questions the installer asks](#the-questions)
- [Unattended install (no questions)](#unattended-install)
- [The `agos` command](#the-agos-command)
- [Updating](#updating) · [Backups](#backups-and-restore) · [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)
- [Why a VM on the Mac and WSL on Windows](#why-a-vm-on-the-mac-and-wsl-on-windows)
- After the install: [user guide](user-guide.md), [operations](operations.md), [runbooks](runbooks/README.md)

## Minimum hardware

|           | Minimum                                                                                            | Recommended                       |
| --------- | -------------------------------------------------------------------------------------------------- | --------------------------------- |
| Memory    | 4 GB (the installer stops below that, and warns under 8 GB)                                        | 16 GB for several busy workspaces |
| Free disk | 20 GB (the installer stops below that)                                                             | 50 GB+ (your files, backups)      |
| CPU       | 64-bit x86 or ARM, 2 cores (the installer stops below that)                                        | 4 cores or more                   |
| System    | Ubuntu 24.04 LTS (tested) or 22.04 LTS; macOS 13+ / Windows 10 21H2+, 11 (preview, not yet tested) | Ubuntu 24.04 LTS                  |

Check a machine before installing: `deploy/install-server.sh --check-machine` (no
sudo, changes nothing). `AGOS_SKIP_HARDWARE_CHECK=1` installs below the minimum
anyway (it will be slow, or fail while building).

What these numbers are based on:

- **The minimum, measured** (`deploy/test-hardware-vm.sh`, 2026-11-03): AGOS
  v0.1.0 on an Ubuntu 24.04 VM with 2 CPUs, running the load test at a small scale
  (2 workspaces, each with its own Hermes engine, 20 cards created, 4 chat
  answers at the same time, ~600 page reads):

  | VM memory | load test | out-of-memory kills | lowest free memory | swap used | chat answer | page read p95 | AGOS at rest |
  | --------- | --------- | ------------------- | ------------------ | --------- | ----------- | ------------- | ------------ |
  | 3 GB      | passed    | 0                   | 1.4 GB             | 0.35 GB   | ~9 s        | 41 ms         | 0.85 GB      |
  | 4 GB      | passed    | 0                   | 2.0 GB             | 0.28 GB   | ~9 s        | 38 ms         | 1.2 GB       |

  Two workspaces used 1.2–1.7 GB at their peak (about 0.8–0.9 GB each with its
  engine). The answers' time is the scripted test model's, not a real model's.
  Running fits in 3 GB; installing and every update also build the web app
  (measured on 4 and 5 GB VMs), so **4 GB is the minimum** the installer accepts.
  Each more workspace adds about 0.5–1 GB once busy: 8 GB is comfortable for a
  handful.

- **Memory, measured** on a running AGOS with 6 workspaces (`ps`, read-only):
  the core uses about 330 MB, the web about 250 MB, each active workspace's
  Hermes engine 250–400 MB, and the workspaces' sandbox containers (tools, MCP
  servers) about 1.1 GB together. That is about **4–5 GB in use for 6
  workspaces**, about **1.5–2 GB for one**. Building the web app during install
  and update needs about 2–3 GB more for a few minutes.
- **Disk, measured** in the test install (a fresh Ubuntu 24.04 VM, zero
  workspaces): the install takes about **12 GB** — the workspace sandbox
  images 3.5 GB plus 3.5 GB of Docker build cache (`docker builder prune`
  frees it; the next sandbox rebuild is then slower), Hermes with its own
  Python and tools 2.9 GB, AGOS's program and build 1.1 GB, AGOS's starting
  data 1.1 GB, the system packages the rest. One backup of a fresh AGOS is
  about 180 MB. Your data grows with your files, chats and backups.
- **Memory at rest, measured** in the same VM: about 0.7 GB for AGOS with no
  workspace (the whole VM used 1 GB).
- On a Mac, the VM gets 4 CPUs, 8 GB of memory and a 60 GB disk by default
  (`AGOS_VM_CPUS`, `AGOS_VM_MEMORY`, `AGOS_VM_DISK` change that): a Mac with
  16 GB is comfortable, 8 GB works for one or two workspaces with the VM set to
  `AGOS_VM_MEMORY=5`.

## Linux

```bash
curl -fsSL https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.sh | bash
```

It asks for your admin (sudo) password once, asks the [questions](#the-questions),
then installs everything (15–30 minutes, mostly downloads and the build):
system packages, Docker, Node.js 24 + pnpm, uv, Hermes (the agent engine, with
Hermes's own installer, at the exact commit AGOS is tested with:
`deploy/hermes.pin`), AGOS's core and web app (a production build), the
workspaces' sandbox image, and three systemd services (`agos-core`,
`agos-web`, `agos-hooks`) that start when the machine starts, with nobody
logged in. Then open http://localhost:3000.

From a copy of the repository: `./install.sh` (same thing). On an always-on
machine (a server or a desktop that never sleeps), add `--server`: no sleep or
suspend (the screen still locks), a firewall (ufw: nothing comes in except over
Tailscale), automatic security updates.

Nothing is opened to the internet: AGOS listens on 127.0.0.1 only.

## macOS

> **Preview, not yet tested.** This installer has not been run on a real Mac yet.

```bash
curl -fsSL https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.sh | bash
```

The same command. On a Mac it:

1. installs Homebrew if you don't have it (it asks first), then
   [Lima](https://lima-vm.io) (`brew install lima`);
2. makes a small Ubuntu 24.04 virtual machine named `agos` (no Mac folders are
   shared into it);
3. runs the Linux installer inside it — the same questions;
4. puts an `agos` command on the Mac that forwards to the one in the VM, and
   sets the VM to start when you log in.

Lima forwards the VM's ports to the Mac, so http://localhost:3000 on the Mac is
AGOS. Your AGOS data lives inside the VM, backups too. To copy a backup to the
Mac: `limactl shell agos -- sudo install -m 644 /home/agos/agos-backups/<file> /tmp/`
then `limactl copy agos:/tmp/<file> .`

Extra Mac commands: `agos vm-stop`, `agos vm-start` (the whole VM),
`agos uninstall` (asks, then deletes the whole VM with its data).

## Windows

> **Preview, not yet tested.** This installer has not been run on a real Windows PC yet.

In PowerShell:

```powershell
irm https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.ps1 | iex
```

It:

1. asks Windows for Administrator rights once (WSL is a Windows feature);
2. turns on WSL 2 if it is off — **then you restart Windows and run the same
   command again**;
3. installs Ubuntu 24.04 in WSL, switches systemd on in it
   (`[boot] systemd=true` in `/etc/wsl.conf`);
4. runs the Linux installer inside Ubuntu — the same questions;
5. adds a task that keeps Ubuntu (and so AGOS) running after you log in, and
   an `agos` command for Windows (in a new terminal) that forwards into Ubuntu.

WSL forwards Ubuntu's ports to Windows, so http://localhost:3000 in your
Windows browser is AGOS. `agos uninstall --everything` on Windows removes the
Ubuntu distribution with all its data; `agos uninstall` removes only AGOS.

## The questions

Each has a default (just press Enter) and a flag or variable for
[unattended installs](#unattended-install).

1. **Which Linux user runs AGOS?** A new user named `agos` just for AGOS
   (recommended: AGOS and its agents are kept apart from your own files; that
   is why the admin password is asked once), or you. On Windows the new user
   is always used.
   `--user agos` / `--current-user` · `AGOS_USER_MODE=new|current`
2. **Data folder** — where AGOS keeps everything (workspaces, files, settings,
   the engine's memory). Default `~/agos-data` of that user; backups go next to
   it in `agos-backups`.
   `--data-dir /path` · `AGOS_DATA_DIR`
3. **Model provider** — your agents need one (OpenRouter, Anthropic, OpenAI,
   Gemini, …). "Yes" runs Hermes's own `hermes model` setup, which asks for the
   provider and its key (or sign-in) and keeps them in Hermes; "no" (default)
   means you add it later in **Settings → Models**, which is also where
   subscriptions (Claude, ChatGPT) are signed in per workspace. Keys are never
   shown or written into the install log.
   `--provider openrouter` + key in `AGOS_PROVIDER_KEY` (Hermes tests the key
   first, exactly like Settings → Models) · `--skip-provider`
4. **Voice notes** — who turns your voice messages into text: `off`
   (default), `gemini` (your Gemini key), `openai` (your OpenAI key) or `local`
   (Whisper on this machine, no key). The same setting as **Settings → General
   → Voice notes**, written the same way.
   `--voice off|gemini|openai|local` · `AGOS_VOICE`
5. **Use AGOS from other devices (phone, another computer)?** No (default) /
   yes. Yes installs [Tailscale](https://tailscale.com) (a private network
   only your own devices join) and lets AGOS manage it without sudo
   (`tailscale set --operator=<agos user>`). Then finish in AGOS:
   **Settings → Access → Activate** (sign in, scan the code with your phone).
   `--remote yes|no` · `AGOS_REMOTE`

## Unattended install

`--yes` (or `AGOS_YES=1`, or no keyboard at all) takes every default, plus
whatever flags or variables you give:

```bash
curl -fsSL https://raw.githubusercontent.com/xag-go/agos-by-xag/main/install.sh \
  | AGOS_PROVIDER=openrouter AGOS_PROVIDER_KEY="$MY_KEY" bash -s -- --yes --voice gemini
```

The key is handed over in a private file (mode 600), never on a command line,
and deleted after use. Other options: `--server`, `--no-start` (set up but
don't start, before a restore), `--hermes-commit <sha>`, `--repo <folder>`
(developers: install from a local folder instead of git; such an install is
updated by running the installer again), `--check` (only report what is set
up). `deploy/install-server.sh --help` lists them all. `AGOS_REPO_URL` and
`AGOS_REF` choose where AGOS is downloaded from (default: this repository's
`main`).

**Workspace isolation (the cage)** needs no question: the installer installs
bubblewrap, turns on what the kernel needs for it (on Ubuntu 24.04, bwrap's
AppArmor profile), and checks it as the AGOS user. When that check fails it stops
with `ERROR cage_refused` and the fix for this machine
([troubleshooting](troubleshooting.md#the-cage-refused-to-start)); nothing heavy
was installed yet. `--no-cage` (or `AGOS_SANDBOXD=off`) runs every workspace's
agents without the cage, on purpose only: they can then reach this machine's
Docker, and Settings and `agos doctor` say so.

Running the installer again is safe: finished steps are skipped, the build is
redone only when the code changed, your user and data folder are kept.

## The `agos` command

| Command                                     | What it does                                                                             |
| ------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `agos start` / `stop` / `restart`           | The three AGOS services (the AGOS user may do this without a password).                  |
| `agos status`                               | What runs, whether the core and the web answer, workspaces, versions, where the data is. |
| `agos logs [core\|web\|hooks\|<workspace>]` | Follow a log (default: the core). A workspace id shows that workspace's Hermes logs.     |
| `agos open`                                 | Opens (or prints) http://localhost:3000.                                                 |
| `agos update [--check] [--yes]`             | See [Updating](#updating).                                                               |
| `agos backup`                               | A password-protected backup file now (asks for a backup password the first time).        |
| `agos restore <file.agosb>`                 | Puts a backup back; your current data is kept aside first.                               |
| `agos uninstall [--delete-data] [--yes]`    | See [Uninstalling](#uninstalling).                                                       |
| `agos version`                              | AGOS's release and Hermes's version.                                                     |
| `agos check`                                | The installer's checklist.                                                               |

Run it as yourself (it asks for sudo when it needs to) or as the AGOS user. On
a Mac and on Windows the same command exists on the host and runs inside the
VM / Ubuntu.

## Updating

`agos update` (or **Settings → General → Update AGOS → Check Update → Update
now**, which runs the same thing):

1. looks for a newer release on the install's channel (`stable` by default: the
   newest release tag; `beta`; or `main`, every commit; `agos channel` shows and
   changes it, [releases.md](releases.md)) and checks its signature before
   anything stops (`agos update --check` stops here);
2. backs up: the full encrypted backup when a backup password is set
   (Settings → Server & backup), and always a rollback copy of the database;
3. stops AGOS (and the workspaces' engines when Hermes or AGOS's plugin inside
   them changes too);
4. takes the new release, moves Hermes to the commit that release pins
   (Hermes's own installer), rebuilds the web app and the core, rebuilds the
   sandbox image if it changed;
5. starts AGOS and checks it answers.

AGOS is down for a few minutes. If any step fails, it rolls back by itself:
the old release, the old database copy, the old Hermes, rebuilt and started
again — and says what failed (`agos status`, and the card in Settings). The
last three rollback snapshots are kept in `agos-data/system/update-snapshots/`
(they hold the roots' keys files, so never in `agos-backups`).

The **Hermes update** card (Settings → General) is separate: it moves Hermes
to a newer stable release that AGOS has checked it fits, without changing
AGOS.

## Backups and restore

- `agos backup` (or Settings → Server & backup → Back up now): one encrypted
  file with AGOS's data and Hermes's own backup of every workspace, in
  `agos-backups`. Scheduled daily/weekly backups are set in Settings.
- `agos restore <file.agosb>` asks the backup's password, checks the file is
  complete, stops AGOS, moves the current data aside
  (`agos-data.before-restore-<time>`, kept 14 days; the newest such copy always
  stays), puts the backup in place and starts AGOS. Nothing is overwritten.
- Moving to another machine: install AGOS there, copy the backup file over,
  `agos restore <file>`.

## Uninstalling

`agos uninstall` asks whether to keep your data (default: keep), then removes
the services, the AGOS program files, the `agos` command, AGOS's containers,
networks and sandbox images, and — when the installer made it — the `agos`
user with its Hermes. Your own user and its Hermes are never removed. With
`--keep-data` (or `--yes` alone), `agos-data` and `agos-backups` stay where
they were. Docker, Node.js and Tailscale stay installed (other programs may use
them).

Deleting the data too (answer `n`, or `--delete-data`) asks you to type
`DELETE`; any other answer removes nothing. AGOS first makes one last backup and
copies it out of its own folders, into the home of the user who ran the
command: `~/agos-last-backup-<date>.agosb` (its path is printed; open it with
`agos restore` and your backup password). If that backup can't be made, nothing
is removed. `agos uninstall --delete-data --yes` skips the typing but still
makes the backup.

Mac: `agos uninstall` on the Mac deletes the whole VM (after asking);
`limactl shell agos -- agos uninstall` removes only AGOS inside it. Windows:
`agos uninstall` removes AGOS from Ubuntu; `agos uninstall --everything`
removes the Ubuntu distribution too.

## Troubleshooting

The full guide, with the cause and the fix commands for each problem, is
[troubleshooting.md](troubleshooting.md). The short list:

- **`ERROR cage_refused`** — the cage around each workspace's agents (bubblewrap)
  can't run here. The message names the fix for this machine (install
  bubblewrap, load its AppArmor profile, turn user namespaces on); see
  [The cage refused to start](troubleshooting.md#the-cage-refused-to-start).
- **The install stopped.** Read the last lines; fix what they say (often the
  network: GitHub or a package mirror refused for a moment) and run the same
  command again — finished steps are skipped. The full log is
  `/var/log/agos-install.log` (readable by root only).
- **"Only N GB free"** — free some disk space (`docker system prune` removes
  unused Docker data), or install on a bigger disk.
- **http://localhost:3000 doesn't open** — `agos status`. If a service isn't
  running, `agos logs core` (or `web`) says why; `agos restart`.
- **Agents don't answer** — no model provider yet: Settings → Models.
- **"systemd is not running"** (WSL) — `/etc/wsl.conf` needs `[boot]` /
  `systemd=true`; then `wsl --shutdown` in Windows and open Ubuntu again
  (install.ps1 does this).
- **Mac: nothing on localhost:3000 after a restart** — `agos vm-start`, or
  `limactl list` to see the VM.
- **"this kernel has no Landlock"** — AGOS still runs, but the walls that keep
  one workspace's engine out of the others' files are off. Ubuntu's own
  kernels have Landlock; custom kernels may not.
- **An update failed** — it rolled back by itself; `agos status` shows the
  release you are on, `cat ~agos/agos-data/system/agos-update.json` (as root)
  what failed. Try again later, or report it.
- **Hermes downloads refused (GitHub 429)** — wait a few minutes and run again.

Problems after the install (AGOS down, a workspace that doesn't answer, a full
disk, a failed update) have step-by-step [runbooks](runbooks/README.md).

## Why a VM on the Mac and WSL on Windows

AGOS needs three Linux things: **systemd** (its services and each workspace's
Hermes engine run as services), **Docker** (every agent tool runs in a
sandbox container) and **Landlock** (the walls between workspaces). macOS and
Windows have none of them natively. Rather than a second and third way of
running AGOS, the installer gives each a real Ubuntu and runs the one Linux
installer in it:

- **Mac: Lima.** One `brew install`, a real Ubuntu 24.04 VM (Apple's
  virtualization), systemd and Ubuntu's kernel with Landlock, Docker installed
  inside like on any Linux, and automatic port forwarding so localhost:3000
  works on the Mac. Docker Desktop or Colima would give Docker but run AGOS's
  services in containers without systemd — a different AGOS to test and
  maintain.
- **Windows: WSL 2.** Built into Windows, a real Linux kernel with systemd,
  localhost forwarding to Windows.

The cost is a VM's memory on the Mac (8 GB given to it by default) and the
Linux file system: your AGOS files live inside the VM / Ubuntu, not in your
Mac or Windows folders.

## Testing the installer

How the installer is tested in a throwaway VM, and what that test covers, is in
[guides/testing.md](guides/testing.md#6-the-install-test-vm).
