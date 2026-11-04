# ADR 0021 — The workspace's screen is Hermes's; what stays AGOS's after Step 14

Date: 2026-10-15 · Status: accepted (owner, Step 14: "AGOS = only the web UI;
Hermes runs everything")

Hermes source paths below are relative to `~/.hermes/hermes-agent`; docs to its
`website/docs`.

## 1. The Screen tab is Hermes's Bot Desktop

Before: AGOS decided per workspace whether its sandbox had a screen. Turning
Browser or Computer use on swapped the sandbox image (`agos-sandbox:1` ↔
`agos-sandbox:desktop`), rebuilt the sandbox (stop gateway, remove sandbox, start
again), and wrote its own marker (`.agos-screen`) that the Screen tab read.

Now:

- **One sandbox image for every workspace: the one with the desktop stack**, as
  Hermes's own default is (`hermes_cli/config_defaults.py`: `DEFAULT_SANDBOX_IMAGE =
"nousresearch/hermes-sandbox:desktop"`). The image only carries the packages;
  nothing runs until a tool needs it.
- **The screen's life is Hermes's.** `bot_desktop.placement: terminal` (AGOS
  writes it for every profile) puts the screen inside the sandbox and refuses
  rather than use the host. Hermes starts it on the first browser / computer_use
  call (`tools/bot_desktop/runtime.py`: `ensure_started_for_tool`,
  `tool_placement`) and stops it after `bot_desktop.idle_stop_minutes` (Hermes's
  default, 30; `stop_if_idle`). AGOS no longer writes `auto_start` /
  `idle_stop_minutes` (Hermes's defaults; `auto_start` only matters for a screen
  on the gateway host).
- **On / off is Hermes's config.** Browser and Computer use are only
  `agent.disabled_toolsets` (written by the library like every optional tool). No
  image switch, no sandbox rebuild, no marker. `GET /workspaces/{id}/screen` asks
  Hermes: `hermes config get agent.disabled_toolsets --json`.
- **The picture is Hermes's running screen.** Hermes records the sandbox that hosts
  a profile's screen in `<home>/bot-desktop/sandbox.json`
  (`tools/bot_desktop/sandbox_host.py`: `_marker`, `_owner_identity`) and keeps the
  display env in `/tmp/hermes-bot-desktop/<profile>/env` inside it (`_remote_dir`).
  `screen.jpg` reads that record (no record = 204, no Docker call), checks the
  container is one of this workspace's own sandboxes, and grabs one JPEG there the
  way Hermes's own thumbnail does (`sandbox_host.grab_jpeg`).

Why AGOS still grabs the picture itself: Hermes serves its thumbnail only over the
desktop app's JSON-RPC (`tui_gateway/methods_display.py`: `display.thumbnail`), not
over the gateway's API server. `hermes computer-use screen status` exists, but in a
fresh process it re-attaches to the sandbox through the terminal planner
(`runtime._owned_sandbox_env` → `_sandbox_env(create=True)`): too heavy for a
picture refreshed every second, and a status probe must never touch the agent's
sandbox. The grab is read only, like Hermes's.

The web UI is unchanged (same endpoints, same page).

Live migration: the first sync after this ships changes every profile's
`terminal.docker_image` to `<AGOS_SANDBOX_IMAGE base>:desktop`, so each gateway is
restarted once and each sandbox recreated once (files in `/workspace` are host
mounts and stay). **`agos-sandbox:desktop` must exist on the machine first**:
`scripts/build-sandbox.sh` now builds both images (it is what
`deploy/install-server.sh` runs). Old `.agos-screen` markers are removed at the next
apply.

## 2. Sweep: AGOS engine logic left after Step 14

Checked against `docs` and the source; each row says what moved or why it stays.

### Moved / removed

- **Kanban `wake` thread** (`kanban_board.py`): already gone with the member
  lifecycle (Phase 1). The root's one gateway runs Hermes's dispatcher
  (`kanban.dispatch_in_gateway: true`, `config_defaults.py`), which starts every
  card's worker itself.
- **Capability requests and Co-Founder actions after the answer**
  (`capabilities.after_turn`, `cofounder_actions.after_turn`): removed. The ask is
  Hermes's own approval gate: before `agos_action` / `agos_capability` run, the
  agos-guard plugin asks AGOS (`hermes_channel.tool_check`) and returns `approve`
  from Hermes's `pre_tool_call`, so Hermes shows its Allow / Deny (the same gate as
  a command; `tools/approval.py`). The tools run only after the owner's yes.
- **Autonomy asks on a card** (`agos_guard.card_ask`): the card waits with Hermes's
  typed human wait, `kanban_block` kind `needs_input` (`hermes_cli/kanban_db.py`:
  `VALID_BLOCK_KINDS`; user-guide/features/kanban.md: needs_input surfaces to a
  human), and the owner's answer is a comment + unblock with Hermes's CLI.

### Stays AGOS's (with the reason)

- **Egress proxy and per-workspace network** (`engine/egress_proxy.py`,
  `engine/network.py`). Parity with Hermes's iron-proxy is **not** proven, so it
  stays:
  - Same: iron-proxy refuses private, loopback, link-local (IMDS), CGNAT, ULA and
    IPv4-mapped ranges at connect time, so DNS rebinding is covered
    (user-guide/egress/iron-proxy.md, "Default SSRF deny CIDRs").
  - Missing 1: iron-proxy is a proxy the sandbox is asked to use; the docs say a
    process that opens a raw socket bypasses it (iron-proxy.md, "Security model"). AGOS's sandbox sits on an `--internal` Docker network whose only
    reachable host is AGOS's proxy: a raw socket has no route out.
  - Missing 2: with `enforce_on_docker: true`, Hermes refuses a sandbox whose
    `docker_extra_args` sets `--network` (iron-proxy.md, "Failure modes"). So
    iron-proxy enforcement and AGOS's internal network cannot be combined.
  - Missing 3: the iron-proxy sandbox stays on Docker's default bridge with
    `--add-host host.docker.internal:host-gateway`; it can reach the host's bridge
    address and other containers on that bridge (iron-proxy.md, "Bind policy").
    AGOS's network reaches nothing but the proxy.
  - What iron-proxy adds is swapping provider keys for tokens. AGOS sandboxes hold
    no keys (`terminal.docker_forward_env: []`, `credential_files: []`), so there is
    nothing to swap.
  - user-guide/egress/network-isolation.md is the same internal-network + proxy
    idea, written as compose for Hermes's own container, not per sandbox.
- **Account pause at the owner's level** (`account_pause.py`). The pause is
  Hermes's own `hermes pause`/`resume` per workspace root (the ESTOP sentinel,
  `agent/estop.py`: its cron, its Kanban dispatcher and new gateway turns wait;
  running work is never killed; AGOS resumes only a sentinel carrying its own
  reason — ADR 0022). The watcher stays:
  Hermes only holds work after a provider says the window is closed (cron
  `quota_hold`, `cron/quota_hold.py` and `cron/jobs.py` mark_job_run; the Kanban's
  rate-limit cooldown, `hermes_cli/kanban_db.py`); it has no "pause at N% used" setting (`config_defaults.py`
  `kanban` / `cron` sections). The level is one General setting over every
  account and every workspace; one AGOS loop reads the accounts once
  (`agent/account_usage.py` via `engine/limits.py`) instead of N copies, one per
  root.
- **Ask records for Autonomy on a card** (`kanban_asks` table). The card carries
  the wait (above). AGOS keeps one row per ask because (1) Allow once / Deny buttons
  in the web and on Telegram need a stable key (`kask:once:<id>`), and (2) the grant
  written to the member's home (`agos-kanban-allowed.json`, read by the guard) must
  name the exact action class the guard stopped. On the card that would only be the
  block reason, which the worker model writes itself (`kanban_block reason`): the
  agent would choose what gets allowed.
- **Co-Founder control-plane tools** (`agos_action`, `agos_capability`, their cards
  with Undo, an app's login before it turns on, AGOS's own bundle cards). They
  change AGOS objects (automations, library, apps, owner rules) that only AGOS
  writes into Hermes; Hermes has no such objects. The approval in front of them is
  Hermes's (above).
- **Screen picture grab**: see 1.
