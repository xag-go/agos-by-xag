"""Driving Hermes Agent for AGOS workspaces (ADR 0010, ADR 0020).

One workspace = one Hermes root of its own: its default profile is the Co-Founder,
each team member a profile under it, and the root's one gateway serves them all.
agos-core is the only writer of its config.
The profile's tools run in a Docker sandbox that has only the workspace's
folders; after every folder change the sandbox is rebuilt and checked.

Everything that touches the outside world (the `hermes` CLI, `docker`, the
profile's HTTP API) goes through `Runner`, so tests can replace it.

This module is a compatibility facade (Strangler Fig): the engine's code lives in
this package's modules, one concern each (paths, profiles, sessions, commands,
managed, env, tools, accounts, status, gateway_unit, gateway_run, sandboxes, egress,
skills, held_writes, webhooks, stamps, foreign_processes; shared state in common).
HermesEngine binds their functions as its methods and every old module-level name
is re-exported here, so imports and patches of `agos_core.engine.hermes.<name>` keep
working. What stays here: the engine's state (__init__), `apply` (the one sequence
that composes the parts: config, reload, rebuild the sandbox), `owner_zone`, and the
two methods that call names tests replace on this module (`env_in_use` calls
`_side_by_side`, `screen_jpeg` calls `_run_bytes`). `apply` and `owner_zone` hold
the two recorded layer breaks of this module (lazy imports of actions/general_sync and
actions/owner_time); they move out once those breaks are fixed. New code goes into
the part it belongs to, never here.
"""

import contextlib
import copy
import json
import logging
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from agos_core.config import EngineConfig
from agos_core.engine import network as net
from agos_core.engine import read_cache
from agos_core.engine.hermes import accounts as _accounts
from agos_core.engine.hermes import commands as _commands
from agos_core.engine.hermes import egress as _egress
from agos_core.engine.hermes import env as _env_part
from agos_core.engine.hermes import gateway_run as _gateway_run
from agos_core.engine.hermes import gateway_unit as _gateway_unit
from agos_core.engine.hermes import held_writes as _held_writes
from agos_core.engine.hermes import managed as _managed
from agos_core.engine.hermes import paths as _paths
from agos_core.engine.hermes import profiles as _profiles
from agos_core.engine.hermes import sandboxes as _sandboxes
from agos_core.engine.hermes import sessions as _sessions
from agos_core.engine.hermes import skills as _skills
from agos_core.engine.hermes import status as _status
from agos_core.engine.hermes import tools as _tools
from agos_core.engine.hermes import webhooks as _webhooks
from agos_core.engine.hermes.accounts import _LANES as _LANES
from agos_core.engine.hermes.accounts import _LOGINS as _LOGINS
from agos_core.engine.hermes.accounts import _POOL as _POOL
from agos_core.engine.hermes.apply_stamp import ApplyResult as ApplyResult
from agos_core.engine.hermes.apply_stamp import _digest as _digest
from agos_core.engine.hermes.commands import _CONFIG_WRITES as _CONFIG_WRITES
from agos_core.engine.hermes.env import _AS_READ as _AS_READ
from agos_core.engine.hermes.env import _ENV_IN_USE as _ENV_IN_USE
from agos_core.engine.hermes.env import _side_by_side as _side_by_side
from agos_core.engine.hermes.foreign_processes import _protected_pids as _protected_pids
from agos_core.engine.hermes.foreign_processes import (
    scrub_foreign_processes as scrub_foreign_processes,
)
from agos_core.engine.hermes.gateway_limits import API_HOST as API_HOST
from agos_core.engine.hermes.gateway_limits import RESTART_DRAIN_S as RESTART_DRAIN_S
from agos_core.engine.hermes.gateway_limits import STOP_HEADROOM_S as STOP_HEADROOM_S
from agos_core.engine.hermes.gateway_limits import STOP_WAIT_S as STOP_WAIT_S
from agos_core.engine.hermes.gateway_limits import SUPERVISORS as SUPERVISORS
from agos_core.engine.hermes.gateway_run import _QUIET_DRAIN as _QUIET_DRAIN
from agos_core.engine.hermes.gateway_run import _START_GUARD as _START_GUARD
from agos_core.engine.hermes.gateway_run import _START_LOCKS as _START_LOCKS
from agos_core.engine.hermes.gateway_run import QUIET_PRINCIPAL as QUIET_PRINCIPAL
from agos_core.engine.hermes.gateway_run import _http_ok as _http_ok
from agos_core.engine.hermes.gateway_run import _start_lock as _start_lock
from agos_core.engine.hermes.gateway_run import quiet_drain_set as quiet_drain_set
from agos_core.engine.hermes.held_writes import _APPLY_REST as _APPLY_REST
from agos_core.engine.hermes.held_writes import _DECIDE_PENDING as _DECIDE_PENDING
from agos_core.engine.hermes.held_writes import _PENDING as _PENDING
from agos_core.engine.hermes.held_writes import _SKILL_LEDGER as _SKILL_LEDGER
from agos_core.engine.hermes.held_writes import _UNDO_PENDING as _UNDO_PENDING
from agos_core.engine.hermes.held_writes import memory_undo_ops as memory_undo_ops
from agos_core.engine.hermes.home_lock import _HOME_DEPTH as _HOME_DEPTH
from agos_core.engine.hermes.home_lock import _HOME_GUARD as _HOME_GUARD
from agos_core.engine.hermes.home_lock import _HOME_LOCKS as _HOME_LOCKS
from agos_core.engine.hermes.home_lock import _WRITING as _WRITING
from agos_core.engine.hermes.home_lock import HOME_LOCK as HOME_LOCK
from agos_core.engine.hermes.home_lock import _Locks as _Locks
from agos_core.engine.hermes.home_lock import home_write_lock as home_write_lock
from agos_core.engine.hermes.home_lock import writes_config as writes_config
from agos_core.engine.hermes.managed import _MANAGED_KEYS as _MANAGED_KEYS
from agos_core.engine.hermes.managed_scope import MANAGED_ENV as MANAGED_ENV
from agos_core.engine.hermes.managed_scope import MANAGED_FIRST_TIMEOUT_S as MANAGED_FIRST_TIMEOUT_S
from agos_core.engine.hermes.managed_scope import MANAGED_LOCK as MANAGED_LOCK
from agos_core.engine.hermes.managed_scope import managed_files as managed_files
from agos_core.engine.hermes.paths import ROOT_MARKER as ROOT_MARKER
from agos_core.engine.hermes.probe_runs import HERMES_SETTING_UP as HERMES_SETTING_UP
from agos_core.engine.hermes.probe_runs import SETTINGS_RUNS as SETTINGS_RUNS
from agos_core.engine.hermes.probe_runs import _ProbeRuns as _ProbeRuns
from agos_core.engine.hermes.profiles import _DESCRIPTION as _DESCRIPTION
from agos_core.engine.hermes.profiles import _DISPLAY_NAME as _DISPLAY_NAME
from agos_core.engine.hermes.profiles import _free_port as _free_port
from agos_core.engine.hermes.runtime_env import JUDGE_MODULE as JUDGE_MODULE
from agos_core.engine.hermes.runtime_env import JUDGE_RUN as JUDGE_RUN
from agos_core.engine.hermes.runtime_env import RUNTIME as RUNTIME
from agos_core.engine.hermes.runtime_env import child_env as child_env
from agos_core.engine.hermes.runtime_env import with_runtime as with_runtime
from agos_core.engine.hermes.sandboxes import sandbox_label_of as sandbox_label_of
from agos_core.engine.hermes.skills import _SKILL_CHANGES as _SKILL_CHANGES
from agos_core.engine.hermes.skills import _SKILL_CHECK as _SKILL_CHECK
from agos_core.engine.hermes.skills import _SKILL_HISTORY as _SKILL_HISTORY
from agos_core.engine.hermes.skills import _SKILL_MANAGE as _SKILL_MANAGE
from agos_core.engine.hermes.skills import _SKILL_ROLLBACK as _SKILL_ROLLBACK
from agos_core.engine.hermes.stamps import _LAMP_GATEWAY_KEYS as _LAMP_GATEWAY_KEYS
from agos_core.engine.hermes.stamps import _LAMP_PLATFORM_KEYS as _LAMP_PLATFORM_KEYS
from agos_core.engine.hermes.stamps import _gateway_files as _gateway_files
from agos_core.engine.hermes.stamps import _held_stamp as _held_stamp
from agos_core.engine.hermes.stamps import _ledger_stamp as _ledger_stamp
from agos_core.engine.hermes.stamps import _routing_stamp as _routing_stamp
from agos_core.engine.hermes.status import _GATEWAY_SOCKET_MAX as _GATEWAY_SOCKET_MAX
from agos_core.engine.hermes.status import _GATEWAY_STATUS as _GATEWAY_STATUS
from agos_core.engine.hermes.status import _PAIRED as _PAIRED
from agos_core.engine.hermes.status import _SOCKET_ONLY as _SOCKET_ONLY
from agos_core.engine.hermes.status import _USAGE as _USAGE
from agos_core.engine.hermes.status import GATEWAY_SOCKET as GATEWAY_SOCKET
from agos_core.engine.hermes.status import GATEWAY_SOCKET_POINTER as GATEWAY_SOCKET_POINTER
from agos_core.engine.hermes.status import GATEWAY_SOCKET_PROTOCOL as GATEWAY_SOCKET_PROTOCOL
from agos_core.engine.hermes.status import GATEWAY_SOCKET_WAIT_S as GATEWAY_SOCKET_WAIT_S
from agos_core.engine.hermes.status import gateway_socket_status as gateway_socket_status
from agos_core.engine.hermes.tools import _COMMAND_MENU as _COMMAND_MENU
from agos_core.engine.hermes.tools import _CREDENTIALS as _CREDENTIALS
from agos_core.engine.hermes.tools import _TOOL_ACTIVE as _TOOL_ACTIVE
from agos_core.engine.hermes.tools import _TOOL_CHECK as _TOOL_CHECK
from agos_core.engine.hermes.tools import _TOOL_SERVICE as _TOOL_SERVICE
from agos_core.engine.hermes.tools import _TOOLS_CATALOG as _TOOLS_CATALOG
from agos_core.engine.hermes.tools import SERVICE_TOOLSETS as SERVICE_TOOLSETS
from agos_core.engine.hermes.tools import TOOLS_CHECK_TTL as TOOLS_CHECK_TTL
from agos_core.engine.hermes.webhooks import _WEBHOOK_ROUTES as _WEBHOOK_ROUTES
from agos_core.engine.hermes.webhooks import apply_webhook_routes as apply_webhook_routes
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.rules import (
    Grant,
    build_mounts,
    model_pairs,
    profile_config,
)
from agos_core.engine.waits import hermes_wait

# Moved to the Hermes Gateway (ADR 0024); the old names stay importable here.
from agos_core.hermes_gateway.errors import EngineError as EngineError
from agos_core.hermes_gateway.runner import Runner as Runner
from agos_core.hermes_gateway.runner import SubprocessRunner as SubprocessRunner
from agos_core.hermes_gateway.runner import refusal_line as refusal_line
from agos_core.hermes_gateway.runner import wrapped

log = logging.getLogger("agos.engine")

# Runs inside the sandbox: grab the X display named by DISPLAY (Pillow ships
# in agos-sandbox:desktop), shrink to the asked width, write a JPEG to stdout.
_GRAB = """
import io, os, sys
from PIL import ImageGrab
img = ImageGrab.grab(xdisplay=os.environ["DISPLAY"])
w = int(sys.argv[1])
if img.width > w:
    img = img.resize((w, round(img.height * w / img.width)))
buf = io.BytesIO()
img.convert("RGB").save(buf, "JPEG", quality=int(sys.argv[2]), optimize=True)
sys.stdout.buffer.write(buf.getvalue())
"""


def _run_bytes(args: list[str], *, timeout: float) -> bytes:
    """Binary stdout of a fixed argv (no shell); b"" when the command fails."""
    off_loop("docker exec screen")
    done = subprocess.run(  # noqa: S603 — fixed argv, no shell
        args,
        capture_output=True,
        timeout=hermes_wait(timeout),
        env=child_env(),
        check=False,
        start_new_session=True,
    )
    return done.stdout if done.returncode == 0 else b""


class HermesEngine:
    # gateway_run.py
    gateway_key = _gateway_run.gateway_key
    is_running = _gateway_run.is_running
    serve = _gateway_run.serve
    start = _gateway_run.start
    _start_root = _gateway_run._start_root
    _wait_running = _gateway_run._wait_running
    stop = _gateway_run.stop
    _quiet_drain = _gateway_run._quiet_drain
    park = _gateway_run.park

    # gateway_unit.py
    service_unit = _gateway_unit.service_unit
    _root_unit_name = _gateway_unit._root_unit_name
    _runtime_dropin = _gateway_unit._runtime_dropin
    wall_lists = _gateway_unit.wall_lists
    sandboxd_on = _gateway_unit.sandboxd_on
    refresh_dropin = _gateway_unit.refresh_dropin
    service_active = _gateway_unit.service_active

    # profiles.py
    _profile_of = staticmethod(_profiles._profile_of)
    _cli_finds = _profiles._cli_finds
    _profile_cli = _profiles._profile_cli
    set_display_name = _profiles.set_display_name
    set_description = _profiles.set_description
    _profile_meta = _profiles._profile_meta
    ensure_profile = _profiles.ensure_profile
    _make_in_root = _profiles._make_in_root
    _write_api_env = _profiles._write_api_env
    api = _profiles.api
    delete_profile = _profiles.delete_profile
    _delete_in_root = _profiles._delete_in_root

    # sessions.py
    archive_sessions = _sessions.archive_sessions
    pin_sessions = _sessions.pin_sessions
    rename_session = _sessions.rename_session

    # sandboxes.py
    sandbox_label = _sandboxes.sandbox_label
    has_screen = _sandboxes.has_screen
    _docker = _sandboxes._docker
    sandboxes = _sandboxes.sandboxes
    _sandbox_of = _sandboxes._sandbox_of
    sandbox_address = _sandboxes.sandbox_address
    sandbox_kill = _sandboxes.sandbox_kill
    screen_container = _sandboxes.screen_container
    remove_sandboxes = _sandboxes.remove_sandboxes
    sandbox_mounts = _sandboxes.sandbox_mounts
    verify = _sandboxes.verify
    _clear_sandbox_dirs = _sandboxes._clear_sandbox_dirs

    # egress.py
    ensure_network = _egress.ensure_network
    ensure_proxy = _egress.ensure_proxy
    remove_network = _egress.remove_network

    # skills.py
    skill_manage = _skills.skill_manage
    skill_check = _skills.skill_check
    skill_rollback = _skills.skill_rollback
    skill_changes = _skills.skill_changes
    skill_history = _skills.skill_history
    ledger_stamp = _skills.ledger_stamp
    bundled_skills = _skills.bundled_skills

    # held_writes.py
    pending_writes = _held_writes.pending_writes
    decide_pending = _held_writes.decide_pending
    hermes_check = _held_writes.hermes_check
    apply_pending_rest = _held_writes.apply_pending_rest
    undo_pending = _held_writes.undo_pending

    # env.py
    as_hermes_reads = _env_part.as_hermes_reads
    hermes_secrets = _env_part.hermes_secrets
    _as_read = _env_part._as_read
    _env_yaml_side = _env_part._env_yaml_side
    _env_gateway = _env_part._env_gateway
    _env_run = _env_part._env_run
    config_schema = _env_part.config_schema
    _read_schema = _env_part._read_schema

    # webhooks.py
    webhook_routes = _webhooks.webhook_routes

    # accounts.py
    hermes_lanes = _accounts.hermes_lanes
    hermes_logins = _accounts.hermes_logins
    credential_pool = _accounts.credential_pool

    # status.py
    pairing_approved = _status.pairing_approved
    gateway_status = _status.gateway_status
    _gw_ask = _status._gw_ask
    _gw_socket = staticmethod(_status._gw_socket)
    _gw_mark = staticmethod(_status._gw_mark)
    _gw_behind = _status._gw_behind
    gateway_shown = _status.gateway_shown
    _gateway_up = _status._gateway_up
    _wait_gone = _status._wait_gone
    hermes_usage = _status.hermes_usage

    # tools.py
    tool_readiness = _tools.tool_readiness
    _check_tools = _tools._check_tools
    tools_catalog = _tools.tools_catalog
    save_credentials = _tools.save_credentials
    set_tool_service = _tools.set_tool_service
    tool_services_in = _tools.tool_services_in
    _tool_services_now = _tools._tool_services_now
    command_menu = _tools.command_menu
    _read_menu = _tools._read_menu
    tools_install = _tools.tools_install
    forget_tools = _tools.forget_tools
    tool_keys = _tools.tool_keys

    # commands.py
    _in_runtime = _commands._in_runtime
    set_setting = _commands.set_setting
    _cli = _commands._cli
    backup = _commands.backup
    backup_root = _commands.backup_root
    _hermes = _commands._hermes
    config_writes = _commands.config_writes
    _config_writes = _commands._config_writes
    _config_batch = _commands._config_batch
    _runtime_argv = _commands._runtime_argv

    # managed.py
    managed_keys = _managed.managed_keys
    _env = _managed._env
    _unmanaged = _managed._unmanaged
    managed_config = _managed.managed_config
    managed_write = _managed.managed_write
    unmanaged_hermes = _managed.unmanaged_hermes
    unmanaged_writes = _managed.unmanaged_writes
    unmanaged_in = _managed.unmanaged_in
    gateway_managed = _managed.gateway_managed

    # paths.py
    profile = _paths.profile
    own_profiles = _paths.own_profiles
    split = staticmethod(_paths.split)
    root = _paths.root
    legacy_home = _paths.legacy_home
    migrating = _paths.migrating
    not_migrated = _paths.not_migrated
    hermes_name = _paths.hermes_name
    profile_home = _paths.profile_home
    home_in = _paths.home_in
    home_of = _paths.home_of
    hermes_env = _paths.hermes_env
    walled = _paths.walled
    walled_for_home = _paths.walled_for_home
    walled_cli = _paths.walled_cli
    lock_dir = _paths.lock_dir
    browser_dir = _paths.browser_dir
    forbidden = _paths.forbidden
    temp_dir = _paths.temp_dir
    is_member = staticmethod(_paths.is_member)

    @property
    def runner(self) -> Runner:
        """Every command's runner, under the Hermes Gateway's policies (ADR 0024)."""
        return self._runner

    @runner.setter
    def runner(self, runner: Runner) -> None:
        self._runner = wrapped(runner)

    def __init__(
        self, settings: EngineConfig, runner: Runner | None = None, *, egress: bool = True
    ) -> None:
        self.settings = settings
        self.runner = runner or SubprocessRunner()
        self._locks = _Locks()
        RUNTIME.clear()
        RUNTIME.update(settings.runtime_env())
        with contextlib.suppress(OSError):
            settings.managed_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Step 6b: sandboxes on an internal network behind AGOS's egress proxy.
        self.egress = egress
        self._judge_argv: list[str] | None = None
        # Each workspace's tool check (tool_readiness), per stamp of what Hermes reads.
        self._tools_seen: read_cache.ReadCache[dict[str, bool]] = read_cache.ReadCache(
            "tool_readiness", max_entries=256
        )
        # Each home's tool services as Hermes's picker finds them (tool_services_in).
        self._services: read_cache.ReadCache[dict[str, str | None]] = read_cache.ReadCache(
            "tool_services", max_entries=256
        )
        # Each root's "/" menu, per stamp of its config and AGOS's policy file.
        self._menus: read_cache.ReadCache[list[dict[str, str]]] = read_cache.ReadCache(
            "command_menu", max_entries=64
        )
        # Each home's last gateway verdict: (when asked, the verdict, its _gw_mark).
        self._gw_seen: dict[str, tuple[float, dict[str, Any], tuple[Any, ...]]] = {}
        self._gw_asking: set[str] = set()
        self._gw_lock = threading.Lock()
        # The lamps' gateway verdicts (gateway_shown) and what the gateway's files
        # said when each one was asked.
        self._lamps: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache("gateway-lamp")
        self._lamp_files: dict[str, Any] = {}
        self._usage: read_cache.ReadCache[dict[str, dict[str, dict[str, int]]]] = (
            read_cache.ReadCache("hermes-usage")
        )
        # Hermes's answers kept while what they come from holds, asked once at a
        # time (engine/read_cache.py): what the gateway uses per .env name (per home),
        # each profile's config as Hermes reads it (per list of homes).
        self._env_use: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache("env_in_use")
        # The probe's YAML side alone (config.yaml with the managed config.yaml on
        # top): a .env change doesn't ask it again.
        self._env_yaml: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache(
            "env_in_use-yaml"
        )
        # At most SETTINGS_RUNS Hermes processes at once for these settings reads,
        # whoever asks (a page, the read-ahead, a warm-up after a save).
        self._settings_slots = threading.BoundedSemaphore(SETTINGS_RUNS)
        # The probe's runs running now: a run refused while a root is set up asks
        # again after them (_env_run).
        self._probe_runs = _ProbeRuns()
        self._as_reads: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache(
            "as_hermes_reads", max_entries=16
        )
        self._logins_seen: dict[tuple[str, bool], tuple[tuple[int, ...], dict[str, Any]]] = {}
        self._lanes: read_cache.ReadCache[dict[str, list[dict[str, Any]]]] = read_cache.ReadCache(
            "hermes-lanes"
        )
        # Hermes's held writes and skill ledger of each home (pending_writes, skill_changes).
        self._held: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache("held-writes")
        self._ledger: read_cache.ReadCache[list[dict[str, Any]]] = read_cache.ReadCache(
            "skill-ledger"
        )
        self._schema_lock = threading.Lock()
        self._schema_failed: tuple[float, str] | None = None
        # Settings → Health: each root's last `hermes status`/`hermes doctor` report
        # with when it was taken (actions/hermes_health.py; memory only).
        self.health_kept: dict[tuple[str, str], Any] = {}

    # ---- apply: config → reload → rebuild sandbox → verify -------------

    def owner_zone(self) -> str:
        """The owner's timezone: Hermes's `timezone` in its managed scope (the same
        for every home; actions/owner_time.py writes it)."""
        from agos_core.domain.time_zone import zone_of
        from agos_core.engine import config_file

        zone = config_file.get(self.managed_config(), "timezone")
        name = zone.strip() if isinstance(zone, str) else ""
        # A zone Hermes rejects (hermes_time.py falls back to local time) is never
        # shown: the core's start repairs it (actions/hermes_managed.repair_zone).
        return name if zone_of(name) is not None else ""

    def apply(
        self,
        workspace_id: str,
        *,
        files_dir: Path,
        workspaces_dir: Path,
        agos_data: Path,
        grants: list[Grant] | Callable[[], list[Grant]],
        model: tuple[str, str, str] | None = None,
        files_read_only: bool = False,
        restart: bool = True,
        members: Sequence[tuple[str, tuple[str, str, str] | None]] = (),
    ) -> ApplyResult:
        """Makes the workspace's sandbox match the grants exactly. Safe to repeat.
        The model fallback chain is never set here: it is Hermes's own, changed only
        from General settings → Fallback models (actions/hermes_fallback.py).

        `grants` as a function: read (Hermes's own list) once this profile's setup
        is this apply's, so a folder click written meanwhile is never written back
        over. `restart=False` (the owner's folder click): Hermes's keys take the new
        setup and nothing else; the stop / sandbox drop / start a running gateway
        needs then comes from the next apply (a background one,
        actions/engine.restart_later), which finds the setup not applied yet.
        `members` (profile key, model): the root's team members, which mount the
        same folders; when the root's sandbox setup changed, each one's apply runs
        while the root's one gateway is down, so they take it in that one restart."""
        with contextlib.ExitStack() as hold:
            # Restarts of a profile run one at a time (the profile's lock); its
            # setup (read, compare, write Hermes's keys) has a short lock of its
            # own, so a folder click writes its setup while a restart still runs.
            if restart:
                hold.enter_context(self._locks.hold(self.profile(workspace_id)))
            writing = hold.enter_context(contextlib.ExitStack())
            writing.enter_context(self._locks.hold(f"{self.profile(workspace_id)} setup"))
            got = grants() if callable(grants) else grants
            mounts = build_mounts(
                files_dir,
                got,
                workspaces_dir=workspaces_dir,
                forbidden=self.forbidden(agos_data),
                files_read_only=files_read_only,
            )
            self.ensure_profile(workspace_id)
            network_config = None
            if self.egress:
                self.ensure_network(workspace_id)
                network_config = net.sandbox_settings(self.profile(workspace_id))
            setup: dict[str, Any] = {
                "image": self.settings.sandbox_image,
                "mounts": mounts,
                "network": network_config,
                "model": model,
                "container_key": self.profile(workspace_id),
            }
            config = profile_config(**setup, zone=self.owner_zone())
            # Same setup as the one already applied: nothing to reload, so a running
            # answer is never cut (each core start re-checks every workspace).
            stamp = self.profile_home(workspace_id) / ".agos-applied"
            # The stamp leaves the owner's timezone out: it reaches the sandboxes
            # without a restart (actions/owner_time.set_zone writes every profile's
            # terminal.docker_env at once, general_sync retries a missed one, and
            # Hermes's terminal tool reads TERMINAL_DOCKER_ENV, bridged from
            # config.yaml, for each new terminal session), so a zone change must not
            # make every workspace re-write its keys and restart at its next sync.
            # It holds the sandbox's part (what the running gateway and its sandboxes
            # keep: image, folders, network, container) apart from the model, which
            # Hermes's gateway reads again for each turn (gateway/run_turn.py
            # _load_gateway_config; its agent cache is keyed on the model): a member
            # following its workspace's new model, or its own pick, is no reason to
            # stop the root's one gateway (it was, once per member, at the next
            # library switch).
            sandbox = _digest(profile_config(**{**setup, "model": None}, zone=""))
            digest = f"3:{sandbox}:{_digest(model)}"
            # A stamp from before (the whole setup, without the zone or with it) still
            # counts.
            before = ("2:" + _digest(profile_config(**setup, zone="")), _digest(config))
            # The toolsets: AGOS's base list only for a new profile. Afterwards they
            # are the workspace's own Hermes setting (the owner's switches,
            # actions/hermes_config.py), never reset by a sandbox sync.
            from agos_core.engine import config_file

            have = config_file.string_list(
                config_file.get(
                    config_file.read(self.profile_home(workspace_id)), "agent.disabled_toolsets"
                )
            )
            if have is not None:
                config.pop("agent.disabled_toolsets", None)
            # The owner's access switch is Hermes's approvals.mode once he has one
            # (off / manual, actions/access.py); a new profile (Hermes's default
            # "smart") starts on manual.
            current = config_file.get(
                config_file.read(self.profile_home(workspace_id)), "approvals.mode"
            )
            if current is False or str(current).lower() in ("off", "manual"):
                config.pop("approvals.mode", None)
            # The timeouts and the video model: the owner's values only for a
            # profile that doesn't have them yet; afterwards they are his (General
            # settings → Time limits), never reset by a sandbox sync.
            from agos_core.engine.rules import seeded_config

            have_config = config_file.read(self.profile_home(workspace_id))
            have_env = config_file.read_env(self.profile_home(workspace_id))
            for key in seeded_config():
                found = have_env.get(key) if key.isupper() else config_file.get(have_config, key)
                if found is not None and found != "":
                    config.pop(key, None)
            # AGOS's recommendations (engine/owner_choices.py): only where the profile
            # has none yet; afterwards the owner's (Settings → Hermes settings).
            from agos_core.engine.owner_choices import keep_owner

            root_id, member = self.split(workspace_id)
            config = keep_owner(
                config,
                have_config,
                config_file.read(self.profile_home(root_id)) if member else None,
            )
            # A root whose model runs on a subscription it has no login of its own
            # for yet keeps reading Claude Code's file until the owner connects it
            # (Settings → Models); then its own login takes over for good.
            from agos_core.engine.login_borrow import borrowing_needed

            if borrowing_needed(self, self.root(workspace_id)):
                config.pop("auth.adopt_external_logins", None)
            was_running = self.is_running(workspace_id)
            # Running or not: the stamp is written only after every key was set and
            # the sandboxes were dropped, so a stopped (archived, crashed) workspace
            # whose setup is unchanged has nothing to write either (it used to set
            # ~15 keys and drop its sandboxes on every sync). The folders are the
            # one list read back from Hermes (its terminal.docker_volumes): when
            # Hermes's list is no longer the one applied (changed in Hermes), the
            # owner's folder click must still win, so that case writes again.
            held = stamp.read_text().strip() if stamp.is_file() else ""
            folders_held = config_file.get(have_config, "terminal.docker_volumes") == json.loads(
                config.get("terminal.docker_volumes", "null")
            )
            if folders_held and held in (digest, *before):
                if held != digest:
                    stamp.write_text(digest)  # the same setup: its stamp, in this form
                return ApplyResult(self.profile(workspace_id), mounts, was_running, 0)
            if folders_held and held.startswith(f"3:{sandbox}:"):
                # The sandbox as applied, only the model moved: its keys alone (one
                # Hermes process, only the ones Hermes doesn't hold already). The
                # gateway runs on, the sandboxes stay.
                moved = model_pairs(*model) if model else {}
                self.config_writes(
                    workspace_id, [("config", "set", k, v) for k, v in config.items() if k in moved]
                )
                stamp.write_text(digest)
                return ApplyResult(self.profile(workspace_id), mounts, was_running, 0)
            # Every key in one Hermes process (Hermes's own writer), only the ones
            # whose value the profile doesn't hold already (a folder click changes
            # terminal.docker_volumes alone; ~15 CLI one after another before).
            self.config_writes(
                workspace_id, [("config", "set", key, value) for key, value in config.items()]
            )
            if not restart:
                # Hermes holds the new setup (the page reads its list); no stamp yet,
                # so the restart's own apply still stops, drops and starts.
                return ApplyResult(self.profile(workspace_id), mounts, was_running, 0)
            # The next folder click may write its setup now, while this one restarts
            # (it is applied by the next round of the same background restart).
            writing.close()
            # The gateway's wall follows the folders (engine/wall.py): its next
            # start, below or whenever systemd starts it, opens only these.
            self.refresh_dropin(self.gateway_key(workspace_id))
            # Hermes keeps the old mounts in memory and in the running sandbox
            # (ADR 0010, finding 7): stop it, drop the sandbox, then start again.
            # A member's settings live in the root's one gateway.
            gateway = self.gateway_key(workspace_id)
            if was_running:
                self.stop(gateway)
            # The team's members mount the same folders: their sandbox keys (each
            # its own apply, Hermes's own writer) while the root's one gateway is
            # down, so a folder click is one restart and every member has the folder
            # at once (each member's next re-sync used to stop and start it again).
            for member, member_model in members:
                self.apply(
                    member,
                    files_dir=files_dir,
                    workspaces_dir=workspaces_dir,
                    agos_data=agos_data,
                    grants=got,
                    model=member_model,
                )
            removed = self.remove_sandboxes(workspace_id)
            if was_running:
                self.start(gateway)
            stamp.write_text(digest)
            # AGOS's old screen marker: Hermes's own config says it now (has_screen).
            (self.profile_home(workspace_id) / ".agos-screen").unlink(missing_ok=True)
        return ApplyResult(self.profile(workspace_id), mounts, was_running, removed)

    def env_in_use(self, home: Path) -> dict[str, Any]:
        """What Hermes's gateway really uses for each .env name of this home (with
        Hermes's managed scope, as the gateway's unit has it), what config.yaml alone
        would set (the profile's, with the managed config.yaml on top), and which
        names the managed .env pins: {"used": {...}, "yaml": {...}, "managed": [...]}.

        Two Hermes runs, started at once (the page waits for the longer one, not
        both): the YAML side, kept while the home's and the managed config.yaml hold
        the same text, and the gateway's side, kept while those and both .env files
        do (a .env change asks only that one again). The gateway's side reports every
        UPPER name its start left in the environment; AGOS keeps the YAML side's
        names and the .env's, exactly the names the old second run was given. In a
        root not set up yet, a run Hermes refuses asks again after the other
        (_env_run): the answer is still Hermes's, as with the runs one after the other."""
        managed = managed_files(self.settings.managed_home)
        key = str(home)
        yaml_now = read_cache.content_stamp(home / "config.yaml", managed[0])
        env_now = read_cache.content_stamp(home / "config.yaml", home / ".env", *managed)
        yaml_side, gateway = _side_by_side(
            lambda: self._env_yaml.get(key, yaml_now, lambda: self._env_yaml_side(home)),
            lambda: self._env_use.get(key, env_now, lambda: self._env_gateway(home)),
        )
        env: dict[str, Any] = gateway.get("env") or {}
        used = {**{name: env.get(name) for name in yaml_side}, **gateway["used"]}
        return copy.deepcopy(
            {"used": dict(sorted(used.items())), "yaml": yaml_side, "managed": gateway["managed"]}
        )

    def screen_jpeg(
        self, workspace_id: str, *, width: int = 1440, quality: int = 70
    ) -> bytes | None:
        """One JPEG of the workspace's screen, grabbed INSIDE its sandbox (the X
        display and its cookie live there), the way Hermes grabs its own thumbnail
        (sandbox_host.grab_jpeg). None when Hermes has no screen running."""
        cid = self.screen_container(workspace_id)
        if cid is None:
            return None
        profile = self.hermes_name(workspace_id)
        # Hermes's Bot Desktop state INSIDE the container (sandbox_host._remote_dir).
        rdir = f"/tmp/hermes-bot-desktop/{profile}"  # noqa: S108 - path in the sandbox
        try:
            out = _run_bytes(
                [
                    self.settings.docker_bin,
                    "exec",
                    cid,
                    "sh",
                    "-c",
                    f"test -s {rdir}/env || exit 3; set -a; . {rdir}/env; set +a; "
                    f'exec python3 -c "$0" {int(width)} {int(quality)}',
                    _GRAB,
                ],
                timeout=20,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return out if out.startswith(b"\xff\xd8") else None
