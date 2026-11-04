"""The cage around each workspace's Hermes gateway: bubblewrap mount masking.

The Landlock wall (engine/wall.py) covers file opens, not `connect()`: a hijacked
gateway could still talk to the Docker socket (docker group = host root) and to the
user manager (`systemd-run --user`, service mode = an unwalled process). This module
builds the `bwrap` prefix that closes both WITHOUT a new OS user (the owner's rule):

- /dev/null is bound over /run/docker.sock (and /var/run/docker.sock when it is its
  own file): connect() gets ECONNREFUSED;
- /dev/null is bound over the user bus ($XDG_RUNTIME_DIR/bus) and a tmpfs over
  $XDG_RUNTIME_DIR/systemd (the private and varlink control sockets, io.systemd.*):
  `systemd-run --user` and `systemctl --user` fail inside; Hermes's restart-safe
  worker scopes degrade to plain children (INVOCATION_ID is unset so Hermes's
  tools/process_registry takes its in-process path instead of erroring);
- the whole agos-sandboxd family folder (/run/user/<uid>/agos-sandboxd: live's
  per-workspace sockets, and staging's under its `stg/`) gets a tmpfs, and only this
  workspace's own socket folder is bound back, so no gateway reaches another
  workspace's or the other AGOS instance's broker socket, not even one made after
  the cage started; DOCKER_HOST points at its filtered socket (engine/sandboxd.py),
  so Hermes's own docker backend keeps working unchanged; a docker CLI config
  folder bound over ~/.docker makes that socket the CLI's default context too, for
  Hermes children whose env drops DOCKER_HOST (its sandboxed browser's `docker exec`);
- containerd's and dockerd's own socket folders get a tmpfs, the system D-Bus
  socket gets /dev/null, and so do AGOS's own secrets the caller names (the
  internal token file, and AGOS's system folder that holds it and agos.db).

bwrap (an unprivileged, setuid-free user-namespace tool, AppArmor-profiled on
Ubuntu) runs OUTSIDE the Landlock wall: the drop-in's ExecStart is
`bwrap <masks> -- python3 wall.py <lists> -- hermes gateway run`. bwrap does not
forward SIGTERM to its child (verified), so the drop-in also sets
KillMode=control-group: systemd signals every process in the unit, the gateway
drains as before. Scripts started by the gateway inherit the cage like the wall.

Verified on this kernel/systemd (Ubuntu 26.04, systemd 259): systemd *user* units
cannot use InaccessiblePaths=/TemporaryFileSystem= themselves ("Failed to set up
mount namespacing: Operation not supported" — the user manager has no privilege for
mount namespaces), which is why the cage is bwrap in ExecStart, not unit directives.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agos_core.engine import wall

BWRAP = "bwrap"
DOCKER_SOCKETS = ("/run/docker.sock", "/var/run/docker.sock")
# Folders of the container runtimes' other sockets (containerd's API, dockerd's
# plugins and metrics): a tmpfs over each that exists.
RUNTIME_SOCKET_DIRS = ("/run/containerd", "/var/run/containerd", "/run/docker", "/var/run/docker")
SYSTEM_BUS = ("/run/dbus/system_bus_socket", "/var/run/dbus/system_bus_socket")
SERVICE = "agos-sandboxd.service"
log = logging.getLogger("agos.engine.cage")


def available() -> bool:
    """bwrap is installed (the installer adds `bubblewrap`)."""
    return shutil.which(BWRAP) is not None


class CageRequiredError(RuntimeError):
    """The cage is required (every AGOS_SANDBOXD but "off") and can't be built."""


# The plain code a refused cage carries everywhere (API body, logs, installer):
# docs/errors.md `cage_refused` (hermes_gateway/errors.py CAGE_REFUSED is the same).
CODE = "cage_refused"
OFF_ON_PURPOSE = (
    "Workspace isolation is OFF on purpose (AGOS_SANDBOXD=off): gateways keep the "
    "real Docker socket. Remove AGOS_SANDBOXD=off from agos-core's environment to "
    "turn it back on"
)

_told_missing: list[bool] = []
# When each refusal message was last logged (time.monotonic): once a minute at most.
_told_at: dict[str, float] = {}
TELL_EVERY = 60.0


def _tell(message: str) -> None:
    now = time.monotonic()
    if now - _told_at.get(message, -TELL_EVERY) >= TELL_EVERY:
        _told_at[message] = now
        log.error("%s", message)


def enabled(
    mode: str,
    runs: Callable[[], bool | None] | None = None,
    proven: Callable[[], bool] | None = None,
) -> bool:
    """Whether gateways are caged. Every mode but "off" is "required" (audit F9:
    config.py reads an unset AGOS_SANDBOXD, "auto" and "on" as "required"): the
    cage works, or this raises CageRequiredError and no gateway starts. `runs` is a
    real bwrap run (engine/sandbox_broker.py): True = it made its sandbox here,
    False = it refused (Ubuntu 24.04's user-namespace restriction without bwrap's
    AppArmor profile), None = unknown (timed out, could not start). Never uncaged
    on a doubt. The refusal is an agos.* ERROR (System Log, Settings → Errors) at
    most once a minute; `proven` (bwrap worked on this machine before) only adds
    that to the words.

    "off" is the owner's own choice: gateways run uncaged, said once per process
    (a warning in the System Log; Settings → Server & backup and `agos doctor`
    show it for as long as it lasts, actions/isolation.py)."""
    if mode == "off":
        if not _told_missing:
            _told_missing.append(True)
            log.warning("%s", OFF_ON_PURPOSE)
        return False
    installed = available()
    result = (runs() if runs is not None else True) if installed else False
    if result is True:
        return True
    if not installed:
        why = "bwrap (bubblewrap) is not installed"
    elif result is None:
        why = "bwrap's check here didn't finish (timed out or could not start)"
    else:
        why = (
            "bwrap (bubblewrap) is installed but can't run here (the kernel refuses its user "
            "namespace: the installer adds bwrap's AppArmor profile)"
        )
    ran_before = proven is not None and proven()
    message = (
        f"Workspace isolation can't be built ({CODE}): {why}"
        + ("; it worked on this server before" if ran_before else "")
        + ". Gateways won't start until it works, rather than start with the real "
        "Docker socket. Run `agos doctor` on the server for the fix "
        "(docs/troubleshooting.md), or set AGOS_SANDBOXD=off to run them uncaged on purpose"
    )
    _tell(message)
    raise CageRequiredError(message)


def argv(
    *,
    socket_dir: Path,
    runtime_dir: Path,
    family: Path,
    hidden_files: tuple[Path, ...] = (),
    hidden_dirs: tuple[Path, ...] = (),
    docker_config: tuple[Path, Path] | None = None,
) -> list[str]:
    """The bwrap prefix (ends with "--") in front of the wall's own launcher.

    `socket_dir`: this workspace's own agos-sandboxd folder (its docker.sock).
    `family`: the folder every AGOS instance's broker sockets live under (live's
    run dir, staging's beside its workspaces inside it): hidden whole under a
    tmpfs, `socket_dir` (which must sit inside it) bound back alone. `runtime_dir`:
    /run/user/<uid> (the user bus and the user manager's control sockets).
    `hidden_files` / `hidden_dirs`: more of AGOS's own paths the gateway must
    never open (the internal token file, AGOS's system folder).
    `docker_config`: (the folder `write_docker_config` made, the gateway's
    $HOME/.docker): bound read-only over it, so a docker CLI whose env lost
    DOCKER_HOST still reaches the filtered socket, never the real one.
    Only paths that exist are masked: a missing socket is nothing to close.
    """
    if not socket_dir.is_relative_to(family) or socket_dir == family:
        raise ValueError(f"the socket folder {socket_dir} is not inside the broker family {family}")
    out = [BWRAP, "--dev-bind", "/", "/", "--die-with-parent"]
    masked: set[str] = set()
    for sock in (*DOCKER_SOCKETS, *SYSTEM_BUS, *(str(p) for p in hidden_files)):
        path = Path(sock)
        if path.exists() and not path.is_dir() and str(path.resolve()) not in masked:
            masked.add(str(path.resolve()))
            out += ["--ro-bind", "/dev/null", sock]
    for folder in (*RUNTIME_SOCKET_DIRS, *(str(p) for p in hidden_dirs)):
        path = Path(folder)
        if path.is_dir() and str(path.resolve()) not in masked:
            masked.add(str(path.resolve()))
            out += ["--tmpfs", str(path.resolve())]
    bus = runtime_dir / "bus"
    if bus.exists():
        out += ["--ro-bind", "/dev/null", str(bus)]
    manager = runtime_dir / "systemd"
    if manager.is_dir():
        out += ["--tmpfs", str(manager)]
    # The whole family, always: a sibling folder that appears later (the other
    # instance's broker starting after this cage) is hidden too.
    out += ["--tmpfs", str(family), "--bind", str(socket_dir), str(socket_dir)]
    if docker_config is not None:
        # The docker CLI's own default (no DOCKER_HOST): a folder bind, so files
        # AGOS rewrites inside it show through (a file bind would go stale).
        out += ["--ro-bind", str(docker_config[0]), str(docker_config[1])]
    out += [
        "--unsetenv", "INVOCATION_ID",
        "--setenv", "DOCKER_HOST", f"unix://{socket_dir / 'docker.sock'}",
        "--",
    ]  # fmt: skip
    return out


DOCKER_CONTEXT = "agos"


def _write_if_changed(path: Path, body: str) -> None:
    with contextlib.suppress(OSError):
        if path.read_text() == body:
            return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    spare = path.with_name(path.name + ".new")
    spare.write_text(body)
    spare.replace(path)  # in place: the cage's folder bind sees the new file


def write_docker_config(folder: Path, socket: Path, host_config: Path) -> Path:
    """This workspace's docker CLI config folder, bound over the gateway's
    ~/.docker inside its cage (`argv` docker_config): `currentContext` names a
    context whose endpoint is the workspace's filtered `socket`. The docker CLI
    uses it whenever DOCKER_HOST and DOCKER_CONTEXT are unset, which is how
    Hermes runs its sandboxed browser (tools/browser_tool_session `_sandbox_wrap`
    gives `docker exec` only PATH and HOME). The host's own config.json settings
    (`host_config`: credsStore, auths, proxies) are kept; only the context
    changes. Rewritten only on change, file by file inside the folder."""
    settings: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        found = json.loads(host_config.read_text())
        if isinstance(found, dict):
            settings = found
    settings = {**settings, "currentContext": DOCKER_CONTEXT}
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_if_changed(folder / "config.json", json.dumps(settings, indent=1, sort_keys=True) + "\n")
    meta = {
        "Name": DOCKER_CONTEXT,
        "Metadata": {"Description": "this workspace's filtered Docker socket (AGOS)"},
        "Endpoints": {"docker": {"Host": f"unix://{socket}", "SkipTLSVerify": False}},
    }
    digest = hashlib.sha256(DOCKER_CONTEXT.encode()).hexdigest()
    _write_if_changed(
        folder / "contexts" / "meta" / digest / "meta.json",
        json.dumps(meta, indent=1, sort_keys=True) + "\n",
    )
    return folder


def policy(
    *,
    labels: list[str],
    images: list[str],
    network: str,
    root: Path,
    temp_dir: Path,
    configs: list[dict[str, Any]],
    host_home: Path,
    workspace_mount: str,
) -> dict[str, Any]:
    """This workspace's sandboxd policy (engine/sandboxd.py Policy): exactly what
    its gateway may ask Docker for. The bind lists mirror the wall's `allow_list`
    minus the system folders (binding /run into a container would hand it the real
    Docker socket): the root (the sandbox /root and /workspace state live under
    root/sandboxes), its temp folder (Hermes's symlink-safe skills copies), the
    workspace's files folder and the owner's grants as the profiles' own
    `terminal.docker_volumes` say, the connector symlink targets, and the shared
    skill folders read-only. Another root's folder is never bindable."""
    rw: list[str] = [str(root), str(temp_dir)]
    ro: list[str] = []
    for config in configs:
        for host, target, read_only in wall._volumes(config):
            (ro if read_only else rw).append(host)
            if target == workspace_mount and not read_only:
                rw.append(host)
    homes = [root]
    members = root / "profiles"
    if members.is_dir():
        homes += sorted(p for p in members.iterdir() if p.is_dir())
    for home in homes:
        for entry in sorted(home.iterdir()) if home.is_dir() else []:
            if entry.is_symlink():
                rw.append(str(entry.resolve()))
    roots_dir = root.parent.resolve()
    own_root = root.resolve()
    for config in configs:
        skills = config.get("skills") if isinstance(config, dict) else None
        dirs = skills.get("external_dirs") if isinstance(skills, dict) else None
        for folder in dirs if isinstance(dirs, list) else []:
            if isinstance(folder, str) and folder.strip():
                path = folder.strip()
                if path.startswith("~/"):
                    path = str(host_home / path[2:])
                if not wall._other_root(Path(path), roots_dir, own_root):
                    ro.append(path)
    return {
        "labels": sorted(set(labels)),
        "images": sorted(set(images)),
        "networks": sorted({network, "none"}),
        "binds_rw": sorted(set(rw)),
        "binds_ro": sorted(set(ro)),
    }


def sandboxd_policy_suffix() -> str:
    """The broker's policy file suffix (engine/sandboxd.py POLICY_SUFFIX), without
    importing the daemon module at import time."""
    from agos_core.engine import sandboxd

    return sandboxd.POLICY_SUFFIX


def write_policy(folder: Path, profile: str, content: dict[str, Any]) -> Path:
    """The policy file sandboxd serves `profile` from; written only on change
    (sandboxd re-reads per request, so no restart is needed)."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{profile}{sandboxd_policy_suffix()}"
    # The first policy written for a workspace marks when its broker took over:
    # older containers (no owner label yet) are the only ones adopted by label.
    since = time.time()
    with contextlib.suppress(OSError, ValueError, TypeError, KeyError):
        since = float(json.loads(target.read_text())["legacy_before"])
    body = json.dumps({**content, "legacy_before": since}, indent=1, sort_keys=True) + "\n"
    if not target.is_file() or target.read_text() != body:
        target.write_text(body)
    return target


def unit_text(*, script: Path, sockets_dir: Path, policies_dir: Path) -> str:
    """The agos-sandboxd systemd user unit: the same AGOS user, outside every
    gateway's cage (it holds the real Docker socket on their behalf). The system
    python runs the stdlib-only script, like the wall's launcher."""
    command = wall.systemd_quote(
        [
            wall.python(),
            "-I",
            str(script),
            "--sockets",
            str(sockets_dir),
            "--policies",
            str(policies_dir),
            "--events",
            str(policies_dir / "events.jsonl"),
        ],
    )
    return (
        "# Written by AGOS (ADR 0025): the per-workspace Docker API filter.\n"
        "[Unit]\n"
        "Description=AGOS sandbox broker (one filtered Docker socket per workspace)\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={command}\n"
        "Restart=always\n"
        "RestartSec=2\n"
        "NoNewPrivileges=yes\n"
        "MemoryAccounting=yes\n"
        "MemoryMax=256M\n"
        "TasksMax=64\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
