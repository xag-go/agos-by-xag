# Changelog

Every notable change to AGOS is written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- AGOS works on a phone: the side menu opens as a drawer, chats show the list
  then the conversation full screen, the board, its toolbar and card windows fit
  a small screen, buttons are big enough to tap, and the dashboard banner, Office
  and org chart are readable at phone width. Nothing changes on a computer.

- `agos uninstall` now also removes the sandbox containers Hermes started for your
  workspaces (named `hermes-…`). They kept running after the uninstall with the
  workspace files mounted, and the workspace network could not be removed.

## [0.1.0] - 2026-11-04

The first public release (beta).

In short, for people running AGOS:

- **What it is.** Workspaces, one per project, each with a Co-Founder agent and a
  team of agents built on Hermes Agent: a board of task cards, chats on the web
  and on Telegram (with voice notes), automations, skills, MCP servers and app
  connectors, with any model provider and your own keys or subscriptions.
- **Private by default.** No login and no tracking: AGOS listens on 127.0.0.1
  only, and you reach it from your phone over Tailscale (Settings → Access).
- **Safe updates.** Releases are signed. The installer and `agos update` only
  take a release whose signature checks out (nothing changes when it doesn't),
  and only move forward. Every update makes a backup first, and a failed one
  rolls back by itself (`agos rollback` does it by hand). You choose how new you
  want to be: `stable` (the default), `beta`, or every change (`main`).
- **A clear check before installing.** The installer looks at your machine
  first: under 4 GB of memory or 2 CPUs it stops and says why, and under 8 GB
  it warns you.
- **Errors you can act on.** When something goes wrong, AGOS tells you what
  happened and what to do next, in plain words, and `agos doctor --bundle` makes
  a report without keys or personal content for a GitHub issue.
- **Nothing done twice, nothing lost.** A double click or a retry never creates
  a workspace, hires an agent or runs an automation twice. Phone notifications
  go out once, and only after the change is saved. A workspace whose setup was
  cut off finishes it the next time AGOS starts. Old machine logs are cleaned
  up on their own; your content never is. Encrypted backups, with alerts when
  they are missing or old.
- **Workspaces stay walled off.** Each workspace's agents run inside their own
  cage, and AGOS refuses to start them on a machine where that cage can't run
  (the installer sets it up and tells you the fix). Risky actions wait for your
  approval. MCP servers pointing at your own computer or local network are
  refused every time AGOS connects to them.
- **Honest platform support.** Linux (Ubuntu 24.04) is tested. macOS and
  Windows installers are a preview and have not been tested on real machines
  yet.

The details:

### Added

- Workspaces, one per project, each with a Co-Founder agent and a team of
  agents, built on Hermes Agent.
- A board of task cards that agents pick up, move and ask about.
- Chats with the Co-Founder and the agents, on the web and on Telegram, with
  voice notes.
- Automations: schedules and webhooks.
- Skills, MCP servers and app connectors.
- Any model provider (OpenRouter, Anthropic, OpenAI, Gemini and more) with your
  own keys or subscriptions.
- Sandboxes for the agents' tools, and approvals for risky actions.
- Encrypted backups and restore.
- A one-command installer for Linux (Ubuntu 24.04 tested; macOS in a Lima VM
  and Windows in WSL 2 are a preview, not yet tested), and the `agos` command
  (start, stop, status, logs, update, backup, restore, uninstall, version,
  check).
- Update AGOS from Settings (Settings → Update AGOS).
- Access from your phone and other devices over Tailscale (Settings → Access).
- No login: AGOS listens on 127.0.0.1 only.
- No tracking or analytics.
- Catch-up for missed automation runs: a scheduled run missed while the server
  was off runs once when AGOS is back, or is skipped, as you choose per
  automation. A run that caught up shows "Caught up" in its list.
- Folders on the Automations, Skills and Projects lists: create, rename and
  delete them (what is inside goes back to "No folder"), move items with
  "Move" or by dragging, fold them shut (remembered), with counts and a search
  that looks inside them. The Co-Founder can do the same from chat, with Undo,
  and a workspace's export carries them. Folders only organize what you see:
  Hermes runs everything the same and no file moves.
- Suggest kit for members hired before kits (or with a kit missing a part):
  their box shows "No kit yet" or "Kit incomplete", and Suggest kit asks the
  Co-Founder for a whole kit that waits in the Inbox as "Kit for @member"
  (Edit kit, Approve / Reject, Undo). Suggest kits for all asks one member at
  a time, and the Co-Founder can do the same from a chat.
- Releases: versions are signed `vX.Y.Z` tags, and AGOS follows a release
  channel (`stable`, the default: the newest release; `beta`; or `main`, every
  commit). The installer installs the newest stable release, and `agos update` and
  Settings → Update AGOS take the newest release of the install's channel, only
  forward, after checking its Sigstore signature (nothing changes when it does not
  match). `agos channel` shows or changes the channel
  ([docs/releases.md](docs/releases.md)).
- The installer checks the machine first: below 4 GB of memory or 2 CPUs it
  stops with a plain message (`AGOS_SKIP_HARDWARE_CHECK=1` installs anyway), under
  8 GB it warns.
- Every error the core answers with has a code and a "what to do" line in plain
  words (`help` in the API's error answer; the list: [docs/errors.md](docs/errors.md)).
- Browser tests in CI (Playwright): the owner's main flows clicked on the web
  build and 39 screens compared with stored screenshots; failure tests (gateway
  killed mid-answer, model unreachable, core restarts, disk full, database
  busy) and a load test on the real rig
  ([docs/guides/resilience-tests.md](docs/guides/resilience-tests.md)).
- Reliability (ADR 0026): AGOS's own background work (the idle round, the
  trash, the probes) runs on a durable job queue (retried with backoff; a last
  failure is an error in Settings → Errors); every phone push goes out through
  the outbox, only after its change is saved and once; Create workspace, a new
  agent and Run now are never done twice by a retry or a double send; a
  half-made workspace finishes its setup when the core starts; old machine
  records are deleted daily (logs 90 days, runs 180, delivered pushes and
  finished jobs 30; never your content, [docs/operations.md](docs/operations.md#retention));
  the SLOs are measured (`scripts/slo.py` prints the month); and CI checks that
  every migration only adds (expand, then contract).
- Staging: `agos staging up|refresh|status|down` runs a second, quiet AGOS on
  the same machine, on a copy of the newest backup (its own ports, units, data,
  Hermes roots and egress proxy; cron jobs paused, no Kanban dispatcher, no
  automations, no Telegram, no phone push), to try a release before it reaches
  the real one.
- `agos rollback [--to <stamp>]`: back to the release before the last update
  (code, Hermes, database and the Hermes roots' settings; today's are kept
  aside in their own `rolled-from-<time>` copy, and nothing changes when there
  is no room for it). A second rollback, or one after a later update, is
  refused (`--force` to override). Every update now also snapshots the roots'
  settings (in `agos-data/system/update-snapshots`, never with the backups: they
  hold keys), its automatic rollback restores them (cron jobs keep their run
  state), and for 10 minutes after a good update a watch checks the core, the
  web and the gateways and rolls back by itself if they fail (not for a full
  disk, a hand stop or an archived workspace).
- Labs (Settings → General): feature flags with a switch each, also for the
  Co-Founder (`set_flag`, with Undo). Turning one off is the kill switch.
- Warnings and alerts: no backup password, no backup a day after the password
  was set, a newest backup older than its schedule allows (daily 48 hours,
  weekly 8 days), a failed scheduled backup, free disk or memory under 10% for 5
  minutes, a failed monthly restore test or weekly database check reach
  Settings → Errors and your notifications; the backup ones also show on
  Settings → Server & backup. The restore test checks the backup on its own
  terms, on the data disk. Old restore side folders are cleaned up 14 days
  after the time in their name.
- `agos doctor --bundle` and Settings → Errors → Copy diagnostics: a redacted
  report (versions, health, errors, no keys, no personal content) for a GitHub
  issue. `/health?deep=1` checks the database, the disk and the background
  loops.

### Changed

- Service layer (Settings, Automation, Library, Vision, Team, Hire, Connector,
  Co-Founder): the Settings routes are one router per Settings area
  (`api/settings_*.py`, `api/preferences.py` wires them), their rules live in
  `actions/services/settings/`; these services' tables each have one repository
  in `db/` (goals, key results, Co-Founder cards, skill requests and candidates,
  capability requests, app logins, readiness choices, ...). No visible change.
- Core layers: the core no longer imports the agos-guard plugin (the names both
  share live in `agos_core/shared/`, copied byte for byte into the plugin by
  `scripts/sync_shared.py`), the engine no longer imports actions, the guard's
  `__init__.py` is split by responsibility, the core's start sequence, the
  workspace Log and the Dashboard moved from the API into a System service, and
  the catch-up, watchdog, push, System Log and documents tables have their own
  repositories. No visible change.
- Core layers, part B: the Team, Library, Automations, Co-Founder, Vision,
  Settings, Connector and Portability services hold no SQL of their own (their
  tables' repositories, and Hermes's board and session reads, do), Settings →
  Models and the workspace icon moved from the API into their services, and the
  Co-Founder's automation, team, skill, vision, settings, connector and
  portability actions are declared operations: each run of one is checked and
  recorded like the owner's own, and its Undo takes back that run. No visible
  change.
- README and the install guide now say exactly what is tested: Ubuntu 24.04 in
  a VM (install, update, uninstall; a small load at 4 GB and 2 CPUs). macOS
  (Lima) and Windows (WSL 2) are marked "preview, not yet tested". The README's
  memory minimum now matches the installer's (4 GB, a warning under 8 GB).
- CI checks every dependency's licence: a package under a licence an MIT
  project can't ship with (GPL/AGPL, SSPL/BUSL/FSL, or none) fails the build
  unless it was reviewed (`scripts/ci/licenses-allowed.json`).
- CI: a function-complexity ratchet (`scripts/ci/complexity.py`): no new core function
  over ruff's C901 / PLR0912 / PLR0915 limits or 80 lines, no new web function over
  ESLint's complexity 10 or 80 lines; today's may only get simpler. The split
  services' modules now sit in their service packages (`actions/services/...`).
- Documentation rewritten for the public release: a user guide, a glossary,
  operations and runbooks, developer guides (getting started, how to add a
  feature, testing), an architecture document that matches the code (with C4
  diagrams and the target service layer), a Code of Conduct, and a docs link
  check (`scripts/check-docs.py`).

### Security

- Workspace isolation is required by default (audit F9): on a machine where the
  cage (bubblewrap) can't run, workspaces' agents no longer start without it;
  they refuse with the code `cage_refused` (Settings → Errors, Settings → Server
  & backup, `agos doctor`). The installer installs bubblewrap, sets up what the
  kernel needs (AppArmor profile, user namespaces) and stops with the exact fix
  when its cage self-test fails. `--no-cage` / `AGOS_SANDBOXD=off` turns the cage
  off on purpose, and Settings and `agos doctor` then say so. A machine where the
  cage already works sees no change. New: `docs/troubleshooting.md`.
- Workspace scope (audit F12-F17): an MCP server's sign-in state and sign-out,
  marking an error fixed or open (and its Undo), Full access on a chat, a chat's
  turns and an answer's phone push, and an automation's delete now read and change
  only the workspace's own rows; the workspace-scope scan follows callers and
  leaves no high or medium finding unexplained (LOW items: `docs/tech-debt.md`).
- MCP servers are checked for addresses on this computer or the local network
  where Hermes connects, not only when you add one: when AGOS writes a
  workspace's servers, when its gateway starts (a refused one is switched off,
  still shown), and before "Test" connects.
- Staging's sandbox broker sockets now sit inside live's
  `/run/user/<uid>/agos-sandboxd` folder, and every gateway's cage hides that
  whole folder except its own socket: a staging gateway can no longer reach
  live's broker, nor the reverse.
- `AGOS_SANDBOXD=auto` never runs gateways without their cage by accident: a
  timed-out bwrap check proves nothing, a refused one is asked again a minute
  later, and once bwrap worked on the server a later failure stops gateways
  from starting (an error in Settings -> Errors) instead of starting them with
  the real Docker socket. `deploy/verify-server.sh` reports an uncaged gateway
  unless `AGOS_SANDBOXD=off` is set.
- The sandbox broker refuses a container or exec that asks to run as any user
  but the image's own `agent`.
- The web app moves to Next.js 16.4.3 (its security fixes).
- The owner's approval gate fails closed: when AGOS can't tell whether an
  action needs the owner's approval, it asks instead of letting it run.
- Repository addresses: the installer, `agos` and the docs name the public
  repository only; an MCP server's address is checked before it is saved.
- The internal token is no longer passed on a command line (where other
  programs on the machine could read it).

### Fixed

- A token, bridge key or sign-in state with an accented or other non-ASCII
  character is refused as wrong ("Not allowed") instead of an internal error.
- Signing in to a model subscription in Settings → Models (start, code,
  sign-out) no longer makes every other page and chat wait while Hermes starts.
- An update that changes AGOS's plugin inside Hermes (but not Hermes itself) now
  restarts the workspaces' engines once AGOS is up: before, they kept running the
  old plugin until their next restart.
- Creating a workspace (or hiring a new member) no longer waits for its
  Holographic memory install: that install holds the profile's config lock while
  it downloads, so on a slow network every later setup step waited minutes. The
  install now starts once the setup is written.
- `agos stop|restart|update` no longer print `/proc/<pid>/cmdline: No such file`
  when the last update's watch is gone, and always stop a running nohup watch;
  `agos update` no longer reinstalls a Hermes that is already on its pin, and
  `agos version` no longer prints "not found" under a working Hermes (pipes
  under `pipefail` failed by SIGPIPE).
- A chat message is no longer answered twice when the core restarts while
  Hermes takes it (the plugin confirms a message it already has instead of
  giving it to Hermes again).
- A request with a number too large for the database answers "invalid value"
  instead of an internal error.
- An update killed while making its rollback copy no longer leaves a folder
  that `agos rollback` takes for a good copy, and the rotation keeps the last
  three good copies (crash leftovers are removed).
- A backup without AGOS's database fails instead of passing; files that vanish
  during a backup are logged.
- The installer's AppArmor step for bwrap prefers the system's own profile,
  leaves one the admin disabled alone, and no longer stops the install when the
  profile can't be loaded.

[0.1.0]: https://github.com/xag-go/agos-by-xag/releases/tag/v0.1.0
