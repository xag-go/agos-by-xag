"""The sandbox broker's side of the engine (ADR 0025 step 4): whether the broker is in
force, the cage prefix of a root's gateway, the policy it serves for a workspace, the
agos-sandboxd user unit, and the drop-in lines that start a gateway inside its cage.

Moved out of engine/hermes.py (a frozen big file): every function takes the
HermesEngine it works for; HermesEngine keeps `sandboxd_on` and `walled` as
one-line entry points."""

from __future__ import annotations

import contextlib
import logging
import os
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import cage, wall
from agos_core.engine import network as net
from agos_core.hermes_gateway.errors import CageRefused, EngineError, HermesFailed

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

log = logging.getLogger("agos.engine")


# Seconds before a bwrap that refused to run is asked again (review M1).
RETRY_AFTER = 60.0
_clock = time.monotonic
MACHINE_ID = Path("/etc/machine-id")


@dataclass
class _Probe:
    ran: bool = False
    refused_at: float | None = None


# Whether bwrap can make its sandbox on this machine, per engine: only a success is
# kept for good; a refusal is asked again after RETRY_AFTER.
_PROBES: weakref.WeakKeyDictionary[HermesEngine, _Probe] = weakref.WeakKeyDictionary()


def _bwrap_runs(engine: HermesEngine) -> bool | None:
    """True: bwrap made its sandbox (kept, and cage.ok written). False: it ran and
    refused (a non-zero exit). None: unknown (the check timed out or could not
    start: a busy machine, TasksMax), which proves nothing either way."""
    state = _PROBES.setdefault(engine, _Probe())
    if state.ran:
        return True
    now = _clock()
    if state.refused_at is not None and now - state.refused_at < RETRY_AFTER:
        return False
    try:
        engine.runner.run([cage.BWRAP, "--dev-bind", "/", "/", "--", "true"], timeout=20)
    except HermesFailed:
        state.refused_at = now
        return False
    except (EngineError, OSError):
        return None
    state.ran = True
    state.refused_at = None
    _remember_ran(engine)
    return True


def _machine() -> str:
    try:
        return MACHINE_ID.read_text().strip()
    except OSError:
        return ""


def marker(engine: HermesEngine) -> Path:
    """<data>/system/cage.ok: bwrap made its sandbox on this machine once (its
    machine id inside, so a backup restored elsewhere proves nothing there)."""
    return engine.settings.cage_ok_file or engine.settings.roots_dir.parent / "system" / "cage.ok"


def _remember_ran(engine: HermesEngine) -> None:
    path = marker(engine)
    try:
        if not path.is_file() or path.read_text().strip() != _machine():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_machine() + "\n")
    except OSError as error:
        log.warning("the cage's marker %s could not be written: %s", path, error)


def _ran_here(engine: HermesEngine) -> bool:
    """bwrap worked on this machine before: the marker, or a drop-in of this AGOS's
    roots that already starts its gateway in the cage (an install older than the
    marker)."""
    with contextlib.suppress(OSError):
        if marker(engine).read_text().strip() == _machine():
            return True
    units = engine.settings.host_home / ".config" / "systemd" / "user"
    roots = f"{engine.settings.roots_dir}/"
    for conf in sorted(units.glob("*.service.d/agos-runtime.conf")):
        with contextlib.suppress(OSError):
            text = conf.read_text()
            if '"bwrap"' in text and roots in text:
                return True
    return False


def on(engine: HermesEngine) -> bool:
    """The broker is in force (engine/cage.py `enabled`: AGOS_SANDBOXD required/off).
    A cage that can't be built raises CageRefused (code cage_refused): nothing
    that needs the cage (a gateway start, a walled command) runs uncaged."""
    try:
        return cage.enabled(
            engine.settings.sandboxd, lambda: _bwrap_runs(engine), lambda: _ran_here(engine)
        )
    except cage.CageRequiredError as error:
        raise CageRefused(str(error)) from None


def state(engine: HermesEngine) -> str:
    """What the cage is doing, from what this engine already knows (never runs
    bwrap: Settings reads it on every page view): "off" (the owner's
    AGOS_SANDBOXD=off), "ok" (bwrap made its sandbox), "refused" (bwrap missing,
    or its last check refused within RETRY_AFTER), "unchecked" (no gateway asked yet)."""
    if engine.settings.sandboxd == "off":
        return "off"
    if not cage.available():
        return "refused"
    probe = _PROBES.get(engine)
    if probe is None:
        return "unchecked"
    if probe.ran:
        return "ok"
    if probe.refused_at is not None and _clock() - probe.refused_at < RETRY_AFTER:
        return "refused"
    return "unchecked"


def paths(engine: HermesEngine) -> tuple[Path, Path]:
    """(the policies folder beside the roots, the per-workspace sockets base
    under /run/user/<uid>: short paths, gone with the boot like the sockets)."""
    run_dir = engine.settings.sandboxd_run_dir or (
        Path(f"/run/user/{os.getuid()}") / "agos-sandboxd"
    )
    return (engine.settings.roots_dir.parent / "sandboxd", run_dir)


FAMILY = "agos-sandboxd"
# Each workspace's docker CLI config folder, in the policies folder (engine/cage.py
# write_docker_config): <policies>/docker-config/<profile>/.
DOCKER_CONFIGS = "docker-config"


def family(run_dir: Path) -> Path:
    """The broker family folder `run_dir` sits in (the outermost one named
    agos-sandboxd: live's run dir itself, staging's <family>/stg). Every cage
    hides it whole (engine/cage.py argv); a run dir outside one can't be hidden
    from the other instance's cages, so it is refused (config.py checks the env)."""
    for folder in (*reversed(run_dir.parents), run_dir):
        if folder.name == FAMILY:
            return folder
    raise EngineError(f"the broker's socket folder {run_dir} is not inside an {FAMILY} folder")


def cage_argv(engine: HermesEngine, workspace_id: str) -> list[str]:
    """The bwrap prefix for this root's gateway (engine/cage.py), [] when the
    broker is off."""
    if not engine.sandboxd_on():
        return []
    run_dir = paths(engine)[1]
    socket_dir = run_dir / engine.profile(engine.split(workspace_id)[0])
    folders = family(run_dir)
    socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    home_docker = engine.settings.host_home / ".docker"
    home_docker.mkdir(mode=0o700, exist_ok=True)  # the bind's mount point
    config = cage.write_docker_config(
        paths(engine)[0] / DOCKER_CONFIGS / socket_dir.name,
        socket_dir / "docker.sock",
        home_docker / "config.json",
    )
    return cage.argv(
        socket_dir=socket_dir,
        runtime_dir=Path(f"/run/user/{os.getuid()}"),
        family=folders,
        hidden_files=engine.settings.cage_hidden_files,
        hidden_dirs=engine.settings.cage_hidden_dirs,
        docker_config=(config, home_docker),
    )


def walled(engine: HermesEngine, key: str, command: list[str]) -> list[str]:
    """`command` behind this root's cage (when the broker is on) and Landlock wall."""
    return [*cage_argv(engine, key), *wall.argv(wall.python(), engine.wall_lists(key), command)]


def policy(engine: HermesEngine, workspace_id: str) -> dict[str, Any]:
    """What this workspace's gateway may ask Docker for (engine/sandboxd.py):
    its root's and members' sandbox labels, AGOS's sandbox image(s), its own
    internal network, and binds from its profiles' own config (engine/cage.py)."""
    from agos_core.engine import config_file
    from agos_core.engine.hermes import sandbox_label_of
    from agos_core.engine.rules import WORKSPACE_MOUNT, screen_image

    root_id = engine.split(workspace_id)[0]
    root = engine.root(root_id)
    keys = [root_id]
    members = root / "profiles"
    if members.is_dir():
        keys += [
            f"{root_id}--{p.name}"
            for p in sorted(members.iterdir())
            if (p / "config.yaml").is_file()
        ]
    image = engine.settings.sandbox_image
    return cage.policy(
        labels=[sandbox_label_of(engine.profile(k)) for k in keys],
        images=[image, screen_image(image)],
        network=net.network_name(engine.profile(root_id)),
        root=root,
        temp_dir=engine.temp_dir(root_id),
        configs=[config_file.read(engine.profile_home(k)) for k in keys],
        host_home=engine.settings.host_home,
        workspace_mount=WORKSPACE_MOUNT,
    )


def _active(engine: HermesEngine, env: dict[str, str]) -> str:
    try:
        return engine.runner.run(
            ["systemctl", "--user", "is-active", engine.settings.sandboxd_unit], timeout=20, env=env
        ).strip()
    except (EngineError, OSError):
        return ""


def ensure(engine: HermesEngine, workspace_id: str) -> None:
    """The broker serves this workspace before its gateway starts: policy
    written, the agos-sandboxd user unit installed and running, its socket up."""
    if not engine.sandboxd_on():
        return
    from agos_core.engine import sandboxd as sandboxd_module

    policies, sockets = paths(engine)
    root_id = engine.split(workspace_id)[0]
    cage.write_policy(policies, engine.profile(root_id), policy(engine, root_id))
    unit = (
        engine.settings.host_home / ".config" / "systemd" / "user" / engine.settings.sandboxd_unit
    )
    body = cage.unit_text(
        script=Path(sandboxd_module.__file__).resolve(),
        sockets_dir=sockets,
        policies_dir=policies,
    )
    env = {**engine._env(), "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}"}
    changed = not unit.is_file() or unit.read_text() != body
    if changed:
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(body)
        engine.runner.run(["systemctl", "--user", "daemon-reload"], timeout=30, env=env)
    active = _active(engine, env)
    if changed or active != "active":
        with contextlib.suppress(EngineError, OSError):
            engine.runner.run(
                ["systemctl", "--user", "enable", "--now", engine.settings.sandboxd_unit],
                timeout=30,
                env=env,
            )
        if changed and active == "active":
            with contextlib.suppress(EngineError, OSError):
                engine.runner.run(
                    ["systemctl", "--user", "restart", engine.settings.sandboxd_unit],
                    timeout=30,
                    env=env,
                )
        active = _active(engine, env)
    if active != "active":
        log.warning("agos-sandboxd is not active: its gateway socket may be missing")
        return
    sock = sockets / engine.profile(root_id) / "docker.sock"
    deadline = time.monotonic() + 10
    while not sock.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    if not sock.exists():
        log.warning(
            "agos-sandboxd socket %s is not up: the gateway's sandbox won't "
            "start until it is (systemctl --user status %s)",
            sock,
            engine.settings.sandboxd_unit,
        )


def dropin_lines(engine: HermesEngine, workspace_id: str, command: str) -> list[str]:
    """The gateway drop-in's ExecStart lines: Hermes's own `command` behind the
    Landlock wall, inside the cage when the broker is on (with the cage's own
    KillMode and reload)."""
    ensure(engine, workspace_id)
    caged = cage_argv(engine, workspace_id)
    launcher = wall.argv(wall.python(), engine.wall_lists(workspace_id), [])
    lines = [
        "# The Landlock wall: this workspace's own folders only (engine/wall.py).",
        "ExecStart=",
        f"ExecStart={wall.systemd_quote([*caged, *launcher])} {command}",
    ]
    if caged:
        reload_code = (
            "import json,os,signal;"
            "os.kill(json.load(open("
            f"{str(engine.root(workspace_id) / 'gateway.pid')!r}"
            '))["pid"],signal.SIGUSR1)'
        )
        lines += [
            "# The cage (engine/cage.py): no real Docker socket, no user bus;",
            "# DOCKER_HOST is this workspace's filtered socket. bwrap does not",
            "# forward SIGTERM, so systemd signals the whole cgroup, and reload",
            "# (the drain) goes by the gateway's own pid record (a JSON file).",
            "KillMode=control-group",
            "ExecReload=",
            f"ExecReload={wall.systemd_quote([wall.python(), '-c', reload_code])}",
        ]
    return lines
