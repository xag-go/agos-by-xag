"""The root gateway's systemd unit: its name from Hermes, AGOS's drop-in (the install's
runtime, the managed scope, limits and the wall) and whether it is active.

Owns: The drop-in's content and when systemd reloads it; what the wall lets the gateway
open (engine/wall.py allow_list).

Must not: Start or stop the gateway (gateway_run.py) or write Hermes's own unit (Hermes's
`gateway install` does).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agos_core.engine import hermes_contract, root_unit, unit_limits, wall
from agos_core.engine import sandbox_broker as broker
from agos_core.engine.hermes.managed_scope import MANAGED_ENV
from agos_core.engine.hermes.runtime_env import JUDGE_RUN, child_env
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.root_unit import MARKER as ROOT_MARKER
from agos_core.engine.waits import hermes_wait
from agos_core.hermes_gateway.errors import EngineError

log = logging.getLogger("agos.engine")

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_root_unit_name",
    "_runtime_dropin",
    "refresh_dropin",
    "sandboxd_on",
    "service_active",
    "service_unit",
    "wall_lists",
]


def service_unit(self: "HermesEngine", workspace_id: str) -> Path:
    """Hermes's unit for this workspace's root (`hermes gateway install`)."""
    name = self._root_unit_name(workspace_id)
    return self.settings.host_home / ".config" / "systemd" / "user" / name


def _root_unit_name(self: "HermesEngine", workspace_id: str) -> str:
    """Hermes names a root's unit after a hash of its home: asked once from Hermes
    itself (its own get_service_name), then kept for that folder (engine/root_unit.py)."""
    if (known := root_unit.cached(self.root(workspace_id))) is not None:
        return known
    argv = list(self._runtime_argv())
    argv[-1] = argv[-1].replace(JUDGE_RUN, "exec(sys.stdin.read())")
    off_loop("hermes service name")
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher, fixed argv
        argv,
        input="from hermes_cli.gateway import get_service_name\nprint('AGOS-UNIT ' + get_service_name())\n",
        capture_output=True,
        text=True,
        timeout=hermes_wait(60),
        env=child_env(self.hermes_env(workspace_id)),
        check=False,
        start_new_session=True,
    )
    hermes_contract.ran(done)
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-UNIT ")]
    if done.returncode != 0 or not lines:
        raise EngineError("The engine did not name this workspace's gateway service")
    unit = lines[-1][len("AGOS-UNIT ") :].strip() + ".service"
    root_unit.remember(self.root(workspace_id), unit)
    return unit


def _runtime_dropin(self: "HermesEngine", workspace_id: str) -> None:
    """Hermes's unit for a root carries HERMES_HOME but not the install's runtime
    nor the managed scope: a systemd drop-in (kept when Hermes rewrites its unit)
    adds them, so the service never installs a runtime of its own nor rewrites
    the shared launcher, and reads the settings that are one value for every
    workspace (a running gateway takes them at its next start).
    Stays AGOS's: `hermes gateway install` has no option to add an Environment
    line (hermes_cli/gateway.py generate_systemd_unit), and a drop-in is
    systemd's own way to add one to a unit someone else owns."""
    unit = self.service_unit(workspace_id)
    folder = unit.with_name(unit.name + ".d")
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Written by AGOS (ADR 0020): the engine install's own runtime, the",
        "# settings that are one value for every workspace (the engine's Managed Scope)",
        "# and the wall around this workspace's gateway (rewritten when its folders change).",
        "[Service]",
    ]
    if self.settings.runtime_dir is not None:
        lines.append(f'Environment="HERMES_RUNTIME_DIR={self.settings.runtime_dir}"')
    lines.append(f'Environment="{MANAGED_ENV}={self.settings.managed_home}"')
    lines.append(f'Environment="HERMES_GATEWAY_LOCK_DIR={self.lock_dir(workspace_id)}"')
    # glibc gives every thread of the gateway its own malloc arena (live: 71 arenas,
    # 214 MB in a 78-thread gateway); RAM is this box's short supply. Two are
    # enough: Python's small objects use pymalloc, not these arenas. The member
    # runs Hermes's Kanban dispatcher starts inherit it. A running gateway takes
    # it at its next start: a changed drop-in only reloads systemd, below.
    lines.append('Environment="MALLOC_ARENA_MAX=2"')
    lines.append(f'Environment="BH_HOME={self.browser_dir(workspace_id)}"')
    lines += unit_limits.dropin_lines(self.settings.gateway_limits)
    # The wall (engine/wall.py): Hermes's own command, started behind AGOS's
    # Landlock launcher. systemd needs the empty ExecStart= to replace it.
    command = wall.exec_start(unit.read_text()) if unit.is_file() else ""
    if command:
        lines += broker.dropin_lines(self, workspace_id, command)
    else:
        log.warning("no ExecStart in %s: its gateway can't be walled", unit.name)
    body = "\n".join(lines) + "\n"
    target = folder / "agos-runtime.conf"
    if not target.is_file() or target.read_text() != body:
        target.write_text(body)
        self.runner.run(
            ["systemctl", "--user", "daemon-reload"],
            timeout=30,
            env={**self._env(), "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"},
        )


def wall_lists(self: "HermesEngine", workspace_id: str) -> wall.Lists:
    """What the root's gateway may open (engine/wall.py allow_list): its root,
    and the folders its profiles' sandboxes mount (Hermes's own
    terminal.docker_volumes, as AGOS's apply wrote them)."""
    from agos_core.engine import config_file
    from agos_core.engine.rules import WORKSPACE_MOUNT

    root_id = self.split(workspace_id)[0]
    root = self.root(root_id)
    members = root / "profiles"
    homes = [root]
    if members.is_dir():
        homes += sorted(p for p in members.iterdir() if (p / "config.yaml").is_file())
    install = (
        self.settings.runtime_dir.parent
        if self.settings.runtime_dir is not None
        else self.settings.hermes_home
    )
    return wall.allow_list(
        root=root,
        configs=[config_file.read(home) for home in homes],
        host_home=self.settings.host_home,
        install_home=install,
        runtime_dir=self.settings.runtime_dir,
        managed_home=self.settings.managed_home,
        hermes_bin=self.settings.hermes_bin,
        temp_dir=self.temp_dir(root_id),
        workspace_mount=WORKSPACE_MOUNT,
    )


def sandboxd_on(self: "HermesEngine") -> bool:
    return broker.on(self)


def refresh_dropin(self: "HermesEngine", workspace_id: str) -> None:
    """The drop-in of a root whose Hermes service AGOS already installed, as this
    AGOS writes it (a service installed before it carried the managed scope
    gets it for its next start). Nothing for the test-only "spawn" supervisor
    (its gateways get it from their spawn environment)."""
    if self.settings.gateway_supervisor != "systemd":
        return
    try:
        data = json.loads((self.root(workspace_id) / ROOT_MARKER).read_text())
    except (OSError, ValueError):
        return
    unit = str(data.get("unit") or "") if isinstance(data, dict) else ""
    if not unit.endswith(".service") or not self.service_unit(workspace_id).is_file():
        return
    try:
        self._runtime_dropin(workspace_id)
    except (EngineError, OSError) as error:
        log.warning("gateway drop-in of %s not refreshed: %s", workspace_id, error)


def service_active(self: "HermesEngine", workspace_id: str) -> bool:
    if self.settings.gateway_supervisor == "spawn":
        return False  # AGOS runs the gateways itself, no service
    if not self.service_unit(workspace_id).is_file():
        return False
    try:
        out = self.runner.run(
            ["systemctl", "--user", "is-active", self.service_unit(workspace_id).name],
            timeout=20,
            env={**self._env(), "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"},
        )
    except (EngineError, OSError):
        return False
    return out.strip() == "active"
