"""The root gateway's run state: running or not, serve as Hermes's service, start,
stop with Hermes's quiet drain, and park (nothing keeps running for an archived
workspace).

Owns: The start/stop protocol: one start at a time per root, the quiet-drain marker,
the stop budget and the health checks.

Must not: Write the unit or its drop-in (gateway_unit.py), report the gateway's status to
pages (status.py) or remove sandboxes itself (sandboxes.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine import hermes_contract, wall
from agos_core.engine.hermes import mcp_guard
from agos_core.engine.hermes.gateway_limits import STOP_HEADROOM_S, STOP_WAIT_S
from agos_core.engine.hermes.runtime_env import JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "QUIET_PRINCIPAL",
    "_QUIET_DRAIN",
    "_START_GUARD",
    "_START_LOCKS",
    "_http_ok",
    "_quiet_drain",
    "_start_lock",
    "_start_root",
    "_wait_running",
    "gateway_key",
    "is_running",
    "park",
    "quiet_drain_set",
    "serve",
    "start",
    "stop",
]


QUIET_PRINCIPAL = "agos-quiet-stop"
# Hermes's own drain marker, written and removed by Hermes's code (drain_control):
# set before a stop AGOS means, removed after it (only AGOS's own, never a drain
# someone else asked for), so the gateway that starts next takes work as usual.
# "on" also prints Hermes's own stop budget for this home: the seconds systemd's
# TimeoutStopSec is sized from (gateway/restart.py resolve_systemd_timeout_stop_sec
# over hermes_cli/gateway.py's own readers of agent.restart_drain_timeout and
# agent.cron_drain_timeout), the wait AGOS's stop gives the gateway.
_QUIET_DRAIN = f"""
import sys
from gateway.drain_control import clear_drain_request, read_drain_request, write_drain_request
budget = 0.0
if sys.argv[-1] == "on":
    write_drain_request(principal={QUIET_PRINCIPAL!r}, suppress_notification=True)
    try:
        from gateway.restart import resolve_systemd_timeout_stop_sec
        from hermes_cli.gateway import _get_cron_drain_timeout, _get_restart_drain_timeout
        budget = float(resolve_systemd_timeout_stop_sec(_get_restart_drain_timeout(), _get_cron_drain_timeout()))
    except Exception:
        budget = 0.0
elif (read_drain_request() or {{}}).get("principal") == {QUIET_PRINCIPAL!r}:
    clear_drain_request()
print("AGOS-QUIET ok " + str(budget))
"""


def quiet_drain_set(home: Path) -> bool:
    """AGOS's own quiet-stop marker is in this home (read only)."""
    try:
        return bool(
            json.loads((home / ".drain_request.json").read_text()).get("principal")
            == QUIET_PRINCIPAL
        )
    except (OSError, ValueError, AttributeError):
        return False


_START_LOCKS: dict[str, threading.Lock] = {}
_START_GUARD = threading.Lock()


def _start_lock(root_key: str) -> threading.Lock:
    with _START_GUARD:
        return _START_LOCKS.setdefault(root_key, threading.Lock())


def _http_ok(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 — loopback URL we built
            return bool(response.status == 200)
    except OSError:
        return False


# ---- the profile's Hermes process --------------------------------


def gateway_key(self: "HermesEngine", key: str) -> str:
    """Whose gateway runs this profile: the root's (the Co-Founder's) one gateway
    serves every member too (Hermes multiplexing)."""
    return self.split(key)[0]


def is_running(self: "HermesEngine", workspace_id: str) -> bool:
    workspace_id = self.gateway_key(workspace_id)
    try:
        base, _ = self.api(workspace_id)
    except (EngineError, FileNotFoundError):
        return False
    if _http_ok(f"{base}/health"):
        return True
    # A root's one gateway carries every member's turns and its rooms: busy, it
    # can miss a 2-second health check. Never restart (--replace) a live one.
    return self._gateway_up(self.profile_home(workspace_id))


def serve(self: "HermesEngine", workspace_id: str, *, wait_s: float = 90) -> bool:
    """The Co-Founder's gateway as Hermes runs its own: Hermes's systemd service
    (Restart=always, starts at boot). A gateway AGOS started earlier is handed
    over to it. True when it changed something."""
    if self.is_member(workspace_id) or self.service_active(workspace_id):
        return False
    if self.is_running(workspace_id):
        # The one AGOS spawned before (no service yet): Hermes stops it itself.
        with contextlib.suppress(EngineError):
            self._hermes(workspace_id, "gateway", "stop", timeout=60)
    self._hermes(
        workspace_id,
        "gateway",
        "install",
        "--no-start-now",
        "--start-on-login",
        "--if-missing",
        timeout=120,
    )
    self._runtime_dropin(workspace_id)
    self._hermes(workspace_id, "gateway", "start", timeout=120)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if self.is_running(workspace_id):
            return True
        time.sleep(0.5)
    raise EngineError("the workspace's engine did not start")


def start(self: "HermesEngine", workspace_id: str, *, wait_s: float = 60) -> None:
    """The root's one gateway runs (a member's key starts its root's)."""
    self._start_root(self.split(workspace_id)[0], wait_s)


def _start_root(self: "HermesEngine", workspace_id: str, wait_s: float) -> None:
    """The root's one gateway (its Co-Founder and every member): Hermes's own
    service, or (supervisor "spawn", tests only) a process AGOS starts. Never
    `gateway.standalone`: a root's default gateway is its host."""
    if self.migrating(workspace_id):
        raise EngineError("this workspace is moving to its own root")
    mcp_guard.switch_off_private(self, workspace_id)  # Hermes connects from this machine
    if quiet_drain_set(self.root(workspace_id)):
        self._quiet_drain(self.root(workspace_id), on=False)
    if self.settings.gateway_supervisor == "spawn":
        # One start at a time per root: two gateways started together both lose
        # on a newer Hermes ("already owns profile"); an older one let the last win.
        with _start_lock(workspace_id):
            if self.is_running(workspace_id):
                return
            root = self.root(workspace_id)
            # The gateway that just stopped may still be exiting: newer Hermes
            # refuses `--replace` for a process its pid record no longer names.
            self._wait_gone(root)
            off_loop("hermes gateway run")
            self.runner.spawn(
                wall.argv(
                    wall.python(),
                    self.wall_lists(workspace_id),
                    [self.settings.hermes_bin, "gateway", "run", "--replace"],
                ),
                log_file=root / "logs" / "agos-gateway.log",
                env={
                    **self.hermes_env(workspace_id),
                    "TMPDIR": str(self.temp_dir(workspace_id)),
                },
            )
            self._wait_running(workspace_id, wait_s)
        return
    if not self.serve(workspace_id) and not self.is_running(workspace_id):
        self._runtime_dropin(workspace_id)
        self._hermes(workspace_id, "gateway", "start", timeout=120)
        self._wait_running(workspace_id, wait_s)


def _wait_running(self: "HermesEngine", workspace_id: str, wait_s: float) -> None:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if self.is_running(workspace_id):
            return
        time.sleep(0.5)
    raise EngineError("the workspace's engine did not start")


def stop(self: "HermesEngine", workspace_id: str, *, wait_s: float | None = None) -> None:
    """Stops the root's gateway. The wait (unless given) is Hermes's own stop
    budget for that home, from the owner's agent.restart_drain_timeout, plus
    AGOS's headroom; STOP_WAIT_S when Hermes can't say."""
    if self.split(workspace_id)[1] is not None:
        return  # a member is a tenant of its root's gateway: that one keeps running
    home = self.profile_home(workspace_id)
    # A stop AGOS means (a reload, an archive): Hermes's own quiet drain, so
    # its home channel isn't told "Hermes is shutting down" each time. A chat
    # whose answer is cut is still told by Hermes; a crash is still announced.
    budget = self._quiet_drain(home, on=True)
    if wait_s is None:
        wait_s = (
            budget + STOP_HEADROOM_S if isinstance(budget, float) and budget > 0 else STOP_WAIT_S
        )
    try:
        # Hermes stops its service, or the gateway of this home it finds running
        # (hermes_cli/gateway.py `_cmd_stop`: service first, else the profile's).
        with contextlib.suppress(EngineError):
            self._hermes(workspace_id, "gateway", "stop", timeout=wait_s)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and self.is_running(workspace_id):
            time.sleep(0.5)
        if self.is_running(workspace_id):
            raise EngineError("the workspace's engine did not stop")
    finally:
        if quiet_drain_set(home):
            self._quiet_drain(home, on=False)


def _quiet_drain(self: "HermesEngine", home: Path, *, on: bool) -> float | None:
    """Hermes's drain marker with suppress_notification, written (or removed,
    when it is AGOS's own) by Hermes's own code in the home. Its answer: Hermes's
    stop budget for the home in seconds ("on"; 0.0 when it can't say or "off"),
    or None when the marker can't be changed."""
    try:
        argv = list(self._runtime_argv())
    except (EngineError, OSError, ValueError):
        return None
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    argv.append("on" if on else "off")
    env = child_env({**self._env(), "HERMES_HOME": str(home)})
    off_loop("hermes quiet drain")
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
            argv,
            input=_QUIET_DRAIN,
            capture_output=True,
            text=True,
            timeout=hermes_wait(30),
            env=env,
            check=False,
            start_new_session=True,
        )
        hermes_contract.ran(done)
    except (OSError, subprocess.TimeoutExpired):
        return None
    said = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-QUIET ok")]
    if done.returncode != 0 or not said:
        log.info("quiet drain of %s not changed: %s", home.name, done.stderr[-300:])
        return None
    try:
        return max(0.0, float(said[-1].split()[-1]))
    except ValueError:
        return 0.0


# ---- trash / purge -----------------------------------------------


def park(self: "HermesEngine", workspace_id: str) -> None:
    """Workspace archived or trashed: nothing keeps running for it."""
    if not (self.profile_home(workspace_id) / ".env").is_file():
        return
    if self.split(workspace_id)[1] is not None:
        # A member of a root: its root's gateway keeps serving the others; its
        # own sandboxes go (AGOS routes nothing to it any more).
        with self._locks.hold(self.profile(workspace_id)):
            self.remove_sandboxes(workspace_id)
        return
    with self._locks.hold(self.profile(workspace_id)):
        if self.is_running(workspace_id):
            self.stop(workspace_id)
        with contextlib.suppress(EngineError):  # archived/trashed: off at boot too
            if self.service_unit(workspace_id).is_file():
                self._hermes(workspace_id, "gateway", "uninstall", timeout=120)
        self.remove_sandboxes(workspace_id)
        from agos_core.engine import mcp_runner

        with contextlib.suppress(EngineError):
            mcp_runner.remove_all(self._docker, self.profile(workspace_id))
