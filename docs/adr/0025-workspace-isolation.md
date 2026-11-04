# ADR 0025: Workspace isolation — the wall's limits, resource caps, and the sandbox broker

Date: 2026-11-02 (step 4 built 2026-11-03). Status: accepted (steps 1–3 shipped
with this ADR; step 4 — the sandbox broker and the gateway cage — built on
`eng/iso2`, rollback switch `AGOS_SANDBOXD=off`).

## The problem

The goal (threat model T14/T16/T18, ASVS 21/36): no workspace can read or affect
another workspace or the host, **even if its agent is fully taken over by prompt
injection**. The audit found three holes:

1. **The gateway reaches the Docker socket.** The Landlock wall covers file opens,
   not `connect()`: code in a walled gateway can `docker run -v /:/host` and read
   every workspace (sec §4.4).
2. **Same-uid ambient authority.** Every gateway, the core and the web run as one
   user, which is in the `docker` group (root-equivalent, sec §9.1). `/proc` was
   open read-write; `systemd-run --user` (service mode) starts an **unwalled**
   process via the user manager's D-Bus (proved in this branch's probe).
3. **No resource limits** on agos-core/web/hooks or the gateways (docs-ops §5):
   one runaway agent OOMs the host.

One audit claim was **wrong**: "Hermes's terminal runs as root inside the sandbox"
(threat model T16, ASVS 36, from a stale comment in `docker/sandbox/Dockerfile`).
Checked on the live install (2026-11-02): sandboxes run as the unprivileged `agent`
(uid 1001, `Config.User=agent`), `docker exec` inherits that user, CapDrop=ALL,
no-new-privileges, Memory=5 GB, PidsLimit=2048. CapEff is 0. The caps Hermes
re-adds to the _bounding set_ (CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID — for
root-started images) are unreachable here: gaining them needs setuid/file-caps,
which no-new-privileges forbids. They also cannot be removed from AGOS's side —
Docker lets `--cap-add` win over a later `--cap-drop` (verified against a real
daemon: CapBnd stayed 0xcb). Minimizing them needs a Hermes-side option:
`docs/upstream/terminal-docker-cap-minimize.md`.

## What ships now (this branch)

1. **Wall hardening** (`engine/wall.py`): `/proc` read-only (reading pid start
   times stays; writing another same-uid process's `/proc` files — `comm`,
   settings — is closed); Landlock ABI 6 **abstract-unix-socket scope** (a walled
   gateway can't connect to abstract sockets of processes outside its domain).
   Signals are _not_ scoped: a new gateway must still kill a stale one it replaces
   (Hermes `gateway/status.py`), and `kill(pid, 0)` liveness probes elsewhere in
   Hermes treat EPERM as "alive" but we don't want takeover to break.
2. **Gateway resource limits** (`engine/unit_limits.py`, written into the existing
   `agos-runtime.conf` drop-in): MemoryHigh/MemoryMax scaled to RAM
   (max = clamp(RAM/4, 1 GiB, 4 GiB), high = ¾ of it), TasksMax=512. Overridable:
   `AGOS_GATEWAY_MEMORY_{HIGH,MAX}_MB`, `AGOS_GATEWAY_TASKS_MAX`,
   `AGOS_GATEWAY_LIMITS=off`. User units can set these: cpu/memory/pids cgroup
   controllers are delegated to user slices.
3. **Service limits + hardening** (`deploy/install-server.sh`): core
   MemoryHigh/Max (RAM-scaled), TasksMax=512, OOMScoreAdjust=-500,
   ProtectProc=invisible, RestrictSUIDSGID, LockPersonality, RestrictRealtime;
   web and hooks additionally `InaccessiblePaths=-/run/docker.sock` (they never
   talk to Docker) and tight Memory/TasksMax; hooks also ProcSubset=pid,
   PrivateDevices, empty CapabilityBoundingSet. Journald capped:
   `/etc/systemd/journald.conf.d/agos.conf` `SystemMaxUse=1G`.
   Proof on a live install: `deploy/verify-server.sh` (new "Isolation" section)
   and `scripts/check-isolation.sh`.

**The owner's powers are untouched**: skills/profiles/automations are files in the
gateway's own root (read-write behind the wall — proved by
`test_a_walled_gateway_keeps_its_powers`), `/workspace` stays a read-write mount,
and the sandbox user/home layout (`agent`, bind-mounted `/root`) is unchanged.

## Step 4 as built: the broker and the cage, one OS user (the owner's rule)

The first design above had two moves: (a) one OS user per workspace, (b) the
broker. **The owner rejected (a)** — no new Linux users, everything keeps running
as the single AGOS user exactly as today — so (a) is out for good (hard rule 2 in
the engineering standards). What closes the two holes instead, inside one uid:

**The broker** (`engine/sandboxd.py`, stdlib-only asyncio, run by the system
python from the `agos-sandboxd` systemd _user_ unit — `engine/cage.py
unit_text`): **one process serving one filtered unix socket per workspace**
(0600, under `/run/user/<uid>/agos-sandboxd/<profile>/docker.sock`; a staging copy's
broker serves its own under `agos-sandboxd/stg/`, and every cage puts a tmpfs over the
whole `agos-sandboxd` folder and binds back only its own socket folder, so neither
instance's gateways reach the other's sockets). One process,
not one per workspace: the sockets already partition the clients, the policies
are per-socket JSON files re-read on every request (a changed grant applies at
once, a new workspace needs no restart — the folder is rescanned every 2 s), and
N daemons would be N× the RAM on a 14 GB box for zero isolation gain (the broker
holds no per-workspace secrets; its only power is the real socket, which any
single compromised broker process would hold either way). It forwards exactly
what Hermes's docker terminal backend needs (create/start/exec/logs/attach/
archive/rm on _this workspace's labelled containers only_, list only with the
workspace's own label filter, pull/inspect of the sandbox image only, ping/
version/info) and refuses everything else with a 403 JSON + a security line
(journal + `events.jsonl`). Validated bodies are re-framed (own Content-Length,
no Transfer-Encoding) so nothing smuggles a second request past the check, and a
checked container reference is pinned to its full id before forwarding (a name
re-pointed between check and call can't swap targets). Hermes's cgroup probe
(`docker run --rm <image> sleep 0`, no labels) is adopted: the broker stamps it
with the workspace's own label so its start/wait pass the ownership check.

**The cage** (`engine/cage.py`): each gateway's ExecStart becomes
`bwrap <masks> -- python3 wall.py <lists> -- hermes gateway run`. bwrap (an
unprivileged user-namespace tool, no setuid) binds `/dev/null` over the real
Docker socket(s) (connect() → ECONNREFUSED) and over the user bus, puts a tmpfs
over `$XDG_RUNTIME_DIR/systemd` (so `systemd-run --user` / `systemctl --user`
fail inside — the unwalled-process escape is closed) and over the broker's
sockets base with only this workspace's folder bound back (a gateway can't even
see a sibling's filtered socket), unsets INVOCATION_ID (Hermes's process registry
then takes its in-process path instead of erroring) and sets DOCKER_HOST to the
workspace's filtered socket. Hermes's docker client honors DOCKER_HOST: the
terminal is not reimplemented (hard rule 1). `HermesEngine.walled()` composes the
same cage in front of the wall for every root-code process AGOS starts (plugin
CLI, `hermes cron run`, automation scripts).

Verified on this kernel (bwrap probes + `tests/test_cage.py`): systemd _user_
units cannot use InaccessiblePaths= themselves (no privilege for mount
namespaces) — hence bwrap in ExecStart, not unit directives; bwrap does **not**
forward SIGTERM to its child, so the caged drop-in sets `KillMode=control-group`
(systemd signals every process in the unit; a TERM delivered to the child itself
drains it — proved by `test_bwrap_does_not_forward_sigterm_...`) and rewrites
ExecReload to signal the pid from the gateway's own `gateway.pid` JSON record
(the unit's `/bin/kill -USR1 $MAINPID` would hit bwrap and be lost).

**Amended (audit F9, `docs/compliance/audit-2026-11.md`)**: the cage is now
required by default. An unset `AGOS_SANDBOXD`, `auto` and `on` all read as
`required`: no working bwrap means no gateway starts (`CageRefused`, code
`cage_refused`, an ERROR in Settings → Errors and a line in Settings → Server &
backup), never an uncaged one. Only `AGOS_SANDBOXD=off` (installer `--no-cage`)
runs gateways uncaged, and Settings and `agos doctor` show that as long as it
lasts. The installer installs bubblewrap with the system's package manager, turns
user namespaces on where the kernel has them off, adds bwrap's AppArmor profile,
and refuses to finish when its self-test as the AGOS user fails
(`deploy/cage-setup.sh`, exit 3, with the fix). What follows describes the
original `auto`, kept as history.

**Switches**: `AGOS_SANDBOXD=off` restores today's behaviour exactly (no bwrap in
the drop-in, no KillMode override, no broker unit — proved by
`test_sandboxd_off_keeps_todays_dropin`); `auto` (default) cages wherever bwrap
is installed (the installer adds `bubblewrap`) and a real `bwrap ... -- true` run
works, and warns otherwise; `on` refuses to run without a working bwrap. `auto`
never uncages on a doubt: only a successful probe is kept (it writes
`<data>/system/cage.ok` with the machine id), a refused probe is asked again after
60 s, a probe that times out proves nothing and refuses like `on`, and once bwrap
ran on this machine (the marker, or a caged drop-in of this AGOS's roots) a later
failure refuses to start gateways with an ERROR instead of starting them with the
real Docker socket; `deploy/verify-server.sh` fails an uncaged gateway unless
agos-core runs with `AGOS_SANDBOXD=off`. Ubuntu
24.04 restricts user namespaces to AppArmor-profiled programs and ships no bwrap
profile: there the installer adds Ubuntu's own `bwrap-userns-restrict`
(`deploy/bwrap-apparmor.sh`: the system's own extra-profiles copy when it ships one, else
`deploy/apparmor/`; a profile the admin disabled is left alone, and a parser that can't
load it only warns; children keep no capability); without it every caged gateway
died at start (ops VM). Policies live in `<roots>/../sandboxd/*.policy.json`,
written by the same code that writes the drop-ins (`engine/sandbox_broker.py ensure`, called from
`_runtime_dropin`, which core start and every apply already run).

**The owner's powers are untouched**: the policy's bind list mirrors the wall's
allow-list (the workspace's files folder read-write, its grants, its root), so
the Co-Founder still writes skills/agents via Hermes and still writes and runs
its own scripts in `/workspace`; the container user, `/root` layout and mounts
are byte-identical (the broker forwards a valid create unchanged apart from
framing).

**Residual risks (live)**:

- The **core** keeps the real Docker socket (it builds the sandbox image and runs
  the egress-proxy/MCP containers); a core compromise is still host-equivalent.
  Its move behind the broker is the last step, as planned.
- The broker is same-uid with the gateways: a kernel/bwrap escape from the cage
  reaches the real socket. The cage is namespace + Landlock, not a uid boundary —
  accepted with the owner's no-new-users rule.
- A caged gateway keeps the host network namespace (Telegram, its API port):
  TCP services on localhost stay reachable; the user manager's D-Bus is closed,
  abstract sockets are Landlock-scoped since step 1.
- Gateways pick the cage up at their **next start**: after `agos update`, running
  gateways stay uncaged until restarted (the update restarts them only when the
  Hermes pin changes). First ship should restart the gateways once.
- `docker logs -f` style unframed streams hold a broker connection open until the
  daemon hangs up; the broker never buffers them (spliced), so the cost is one fd
  per stream.

## The original step-4 sketch (kept for the record)

A fully hostile gateway can still, today:

- `connect()` to `/run/docker.sock` (docker group) → mount anything → host root.
- ask the **user manager** (`systemd-run --user`, service mode) to start an
  unwalled process as the same user.

Landlock cannot close either (both are connect()/D-Bus, not file opens), and the
gateway _needs_ Docker to start its own sandbox. The wall is therefore real
defense-in-depth against path reads/writes, **not** a boundary against hostile
code in the gateway. Closing it needs two moves:

**(a) One OS user per workspace** (`agos-ws-<id>`): the gateway runs as its own
uid (Hermes already runs gateways as systemd user services; linger per user).
Then DAC closes every other root, `/proc` (other uids), the user manager (its own,
empty), and Yama closes ptrace. The wall stays as the second layer.

**(b) A sandbox broker** (`agos-sandboxd`): the only member of the `docker`
group (the AGOS user **leaves** it). A small system service exposing one unix
socket per workspace (0600, owned by that workspace's uid), speaking the Docker
API as a **filtering proxy**, so Hermes's terminal keeps working unchanged with
`DOCKER_HOST=unix:///run/agos/sandbox-<ws>.sock` set in the gateway drop-in
(Hermes's docker client honors DOCKER_HOST; AGOS does not reimplement the
terminal — hard rule 1). The broker allows, per workspace, exactly:

- `POST /containers/create`: image ∈ {agos-sandbox:*}, binds under the
  workspace's files folder + its grants (the same list `wall.allow_list` builds),
  network = the workspace's `agos-net-*`, no `--privileged`, no cap-add beyond
  Hermes's five, pids/memory limits present;
- `start/stop/restart/rm/exec/attach/resize/inspect/logs` only on containers
  labeled `hermes-profile=<this workspace>`;
- `GET /version,/info,/images/<agos-sandbox:*>/json`, `POST /images/create`
  (pull) for the pinned sandbox image only;
- everything else: 403, logged to the System Log.

Exec streams are hijacked HTTP — the broker must splice bytes after the headers
(same as docker's own proxy); that and the API-surface audit are why this is a
separate step, not a same-day change. The core keeps the real socket meanwhile
(it builds the image and runs the egress proxy/MCP containers); its own moves
behind the broker last.

**Tradeoffs considered.** _Rootless Docker per AGOS user_: removes
root-equivalence but not cross-workspace reads (all gateways share the uid; a
hijacked gateway still mounts any AGOS-readable path), and container processes
escape the wall (children of dockerd, not of the gateway) — rejected alone,
useful _per workspace uid_ later. _A docker-socket-proxy container (Tecnativa
style)_: filters by endpoint, not by body — can't pin mounts/image per workspace
— rejected. _seccomp on connect()_: can't filter unix paths — rejected.
_Removing the docker group now without the broker_: breaks every sandbox start —
rejected.

## Consequences for a live ship

- Changed gateway drop-ins reload systemd; limits apply to **running** gateways
  at the reload (generous defaults: a live gateway measured ~215 MB vs
  MemoryMax ≥ 1 GiB). The wall change (/proc RO, abstract scope) applies at each
  gateway's **next restart**.
- The installer unit changes need `agos update` + service restart; journald
  restarts once.
- If a sandbox image or workflow ever needs abstract-socket connects out of the
  gateway (none known), the wall fails it closed — watch the System Log after
  shipping.

### Step 4 hardening (eng/iso2): strict HTTP and a creation pin

The broker no longer forwards any byte the client wrote. Its HTTP is strict RFC
9112 (`engine/sandboxd_http.py`): bare CR/LF, NUL or control bytes, obs-fold,
duplicate or non-token headers, duplicate Content-Length, CL+TE, any
Transfer-Encoding but exactly `chunked`, chunk extensions/trailers, oversized
heads and bodies all end in 400 and a closed connection — Docker's lenient Go
parser (bare LF as a line end, case-folded JSON field names) can no longer see a
request the broker read differently. The path is decoded once into segments
(no %2F/%5C/../'//'/non-ASCII; only known /v1.NN prefixes), each route takes only
its known query parameters, and the upstream request is rebuilt by the broker
(fixed Host, its own framing, the re-serialised validated body, the checked
bind sources by realpath), one upstream connection per request; after a 101 on
an exec/attach route only that pair of connections is spliced. Create bodies
are a closed checklist (`engine/sandboxd_rules.py`): unknown top-level or
HostConfig fields, Volumes, Mounts, case-folded duplicate JSON names and
non-string lists are refused; the broker stamps `agos-sandboxd-owner=<profile>`
(callers may set only `hermes-*` labels), a create or exec may not ask for a user other
than the image's own `agent` (or the broker's own uid, what Hermes sends with
`docker_run_as_host_user`), and by-id calls pass only for
containers created through that workspace's socket (containers from before the
broker's first policy are adopted by their Hermes label once). The cage also
masks containerd's and dockerd's socket folders, the system D-Bus socket, the
AGOS internal token file and the whole AGOS system folder; AGOS_SANDBOXD=auto
without bwrap logs an ERROR (a Problem in the workspace Log) instead of a quiet
warning.
