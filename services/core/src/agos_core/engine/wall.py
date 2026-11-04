"""The wall around each workspace's Hermes gateway: Linux Landlock (unprivileged).

A root's gateway (its Co-Founder and every member, their Kanban workers, cron runs and
subagents: Landlock is inherited by every child, `systemd-run --user --scope`
included, which runs the command in the caller's own process) can open only:
- read-write: its own root, its workspace's files folder, its temp folders (/tmp,
  /var/tmp, its own ~/.agos-tmp/<id>, which holds its own gateway-locks folder:
  Hermes's HERMES_GATEWAY_LOCK_DIR), /dev;
- read-only: the Hermes install (~/.hermes/hermes-agent, its runtime ~/.hermes/tools,
  the `hermes` launcher), Hermes's managed scope, the owner's extra folders the
  workspace was granted, Docker's client config and the system folders.
Everything else under the home is closed to it: the other roots, the other
workspaces, AGOS's data (system/, backups), the shared Hermes home and its logins,
and Hermes's per-user lock folder ~/.local/state/hermes (every other gateway's
locks and host records).

Landlock (kernel ABI ≥ 1, used here up to the rights of ABI 5, plus ABI 6's
abstract-unix-socket scope) needs no privilege and keeps Docker working: the Docker
socket is a connect(), not a file open. /proc is read-only (reading its own /proc
entries is enough for Hermes; writing another same-uid process's /proc files, e.g.
its `comm`, is not; a side effect is that WRITING via /dev/stdout-style /proc/self/fd
paths fails, which nothing in a gateway does). What the wall does NOT close — the
same-uid ambient authority reachable by connect() or D-Bus: the Docker socket and
`systemd-run --user` (service mode) both let fully hostile gateway code act outside
the wall. Closing those needs a uid per workspace plus a sandbox broker
(docs/adr/0025-workspace-isolation.md). Fails
closed: a kernel without Landlock exits with an error rather than run unwalled.

This file runs as a tiny stdlib launcher in front of Hermes's own command
(`python3 -I wall.py --rw DIR ... --ro DIR ... -- hermes gateway run`): AGOS's
systemd drop-in wraps the unit's ExecStart with it, and the test-only spawn
supervisor puts it in front of its argv. `allow_list` (the one place that says what
is open) builds the lists. Nothing outside the standard library at import time.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple

SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446  # same numbers on x86_64 and arm64
PR_SET_NO_NEW_PRIVS = 38
CREATE_RULESET_VERSION = 1
RULE_PATH_BENEATH = 1

# Filesystem rights by the ABI that added them.
EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1, 2, 4, 8
_ABI_RIGHTS = {1: (1 << 13) - 1, 2: (1 << 14) - 1, 3: (1 << 15) - 1, 5: (1 << 16) - 1}
TRUNCATE, IOCTL_DEV = 1 << 14, 1 << 15
RO = EXECUTE | READ_FILE | READ_DIR
FILE_RIGHTS = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV

# System folders every process needs to read (programs, libraries, /etc, sockets'
# folders), and the ones it writes.
SYSTEM_RO = (
    "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc", "/opt",
    "/var", "/run", "/sys", "/snap", "/proc",
)  # fmt: skip
SYSTEM_RW = ("/tmp", "/var/tmp", "/dev")  # noqa: S108 - opened to Hermes, not used here

# Landlock scopes (ABI 6): a walled process can't connect() to an abstract unix
# socket of a process outside its own domain. Signals are NOT scoped: a new
# gateway must still kill a stale one it replaces (Hermes gateway/status.py).
SCOPE_ABSTRACT_UNIX_SOCKET = 1


class _Attr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _Beneath(ctypes.Structure):
    _pack_ = 1
    _layout_ = "ms"  # packed like the kernel's __attribute__((packed)) struct
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def abi() -> int:
    """The kernel's Landlock ABI (0: none)."""
    libc = ctypes.CDLL(None, use_errno=True)
    found = libc.syscall(SYS_CREATE, None, 0, CREATE_RULESET_VERSION)
    return int(found) if found > 0 else 0


def _rights(version: int) -> int:
    return _ABI_RIGHTS[max(v for v in _ABI_RIGHTS if v <= version)]


def wall(rw: list[str], ro: list[str]) -> None:
    """Walls this process (and everything it starts) to `rw` and `ro`. Raises
    OSError when the kernel can't."""
    libc = ctypes.CDLL(None, use_errno=True)
    version = abi()
    if version < 1:
        raise OSError(38, "this kernel has no Landlock")
    every = _rights(version)
    attr = _Attr(every, 0, SCOPE_ABSTRACT_UNIX_SOCKET if version >= 6 else 0)
    size = ctypes.sizeof(_Attr) if version >= 6 else 8 if version < 4 else 16
    fd = libc.syscall(SYS_CREATE, ctypes.byref(attr), size, 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    try:
        for paths, rights in ((rw, every), (ro, RO & every)):
            for path in paths:
                try:
                    pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
                except OSError:
                    continue  # a folder that isn't there is nothing to open
                try:
                    is_dir = Path(path).is_dir()
                    rule = _Beneath(rights if is_dir else rights & FILE_RIGHTS, pfd)
                    if libc.syscall(SYS_ADD, fd, RULE_PATH_BENEATH, ctypes.byref(rule), 0) < 0:
                        raise OSError(ctypes.get_errno(), f"landlock_add_rule {path}")
                finally:
                    os.close(pfd)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0:
            raise OSError(ctypes.get_errno(), "no_new_privs")
        if libc.syscall(SYS_RESTRICT, fd, 0) < 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(fd)


class Lists(NamedTuple):
    """What a walled process may open. `locks`: Hermes install-state folders whose
    lock files and lease folders are looked up when it starts (`install_locks`)."""

    rw: list[str]
    ro: list[str]
    locks: list[str]


def argv(python: str, lists: Lists, command: list[str]) -> list[str]:
    """The launcher in front of `command`."""
    out = [python, "-I", str(Path(__file__).resolve())]
    for flag, paths in (("--rw", lists.rw), ("--ro", lists.ro), ("--locks", lists.locks)):
        for path in paths:
            out += [flag, path]
    return [*out, "--", *command]


def systemd_quote(argv_: list[str]) -> str:
    """argv quoted for a systemd Exec line (Hermes's own rule, hermes_cli/gateway.py
    _systemd_command: specifiers and $ escaped)."""
    return " ".join(
        '"'
        + part.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        + '"'
        for part in argv_
    )


def exec_start(unit_text: str) -> str:
    """The unit's own ExecStart command line (Hermes's unit has one), as written."""
    found = ""
    for line in unit_text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == "ExecStart" and value.strip():
            found = value.strip()
    return found


def python() -> str:
    """The interpreter that runs the launcher: the system's (it outlives AGOS's
    own environment), else the one running AGOS."""
    return "/usr/bin/python3" if Path("/usr/bin/python3").exists() else sys.executable


def _volumes(config: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Hermes's `terminal.docker_volumes` (host:target[:ro]) as AGOS wrote them."""
    terminal = config.get("terminal")
    raw = terminal.get("docker_volumes") if isinstance(terminal, dict) else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    out: list[tuple[str, str, bool]] = []
    for spec in raw if isinstance(raw, list) else []:
        parts = str(spec).split(":")
        if len(parts) >= 2 and parts[0].startswith("/"):
            out.append((parts[0], parts[1], len(parts) > 2 and parts[2] == "ro"))
    return out


def allow_list(
    *,
    root: Path,
    configs: list[dict[str, Any]],
    host_home: Path,
    install_home: Path,
    runtime_dir: Path | None,
    managed_home: Path,
    hermes_bin: str,
    temp_dir: Path | None,
    workspace_mount: str,
) -> Lists:
    """The one list of what a root's gateway may open. `configs`: the root's and
    its members' config.yaml (their sandbox mounts name the workspace's files folder
    and the owner's extra folders). `install_home`: the Hermes install's home
    (~/.hermes: its code `hermes-agent`, runtime `tools`, state `installs`), of
    which nothing else (logins, keys, profiles of the shared home) is open."""
    # Not ~/.local/state/hermes: Hermes's per-user lock folder holds every
    # gateway's locks; each root's gateway has its own (HERMES_GATEWAY_LOCK_DIR in
    # its temp folder, engine/hermes.py lock_dir).
    rw: list[str] = [str(root), *SYSTEM_RW]
    if temp_dir is not None:
        rw.append(str(temp_dir))
    installs = install_home / "installs"
    ro: list[str] = [
        str(install_home / "hermes-agent"),
        str(installs),
        str(managed_home),
        str(host_home / ".docker"),
    ]
    if runtime_dir is not None:
        ro.append(str(runtime_dir))
    launcher = Path(hermes_bin)
    ro += [str(launcher), str(launcher.resolve())]
    for config in configs:
        for host, target, _read_only in _volumes(config):
            if target == workspace_mount:
                rw.append(host)  # the workspace's files (its playbooks inside are ro in Docker)
            elif not target.startswith(f"{workspace_mount}/"):
                ro.append(host)  # an extra folder the owner granted: read-only here
    # Links in the root and its member profiles (mcp-tokens: AGOS keeps each
    # workspace's app logins in its connectors folder): Hermes reads and refreshes
    # them, so the link's target is open read-write (only that folder).
    homes = [root]
    members = root / "profiles"
    if members.is_dir():
        homes += sorted(p for p in members.iterdir() if p.is_dir())
    for home in homes:
        for entry in sorted(home.iterdir()) if home.is_dir() else []:
            if entry.is_symlink():
                rw.append(str(entry.resolve()))
    # The skill folders the profiles read (Hermes's skills.external_dirs: AGOS's own
    # and the Brain's, and for a member its workspace's folder, which is inside this
    # root and open already): read-only (Hermes never writes an external skill
    # folder). A folder of ANOTHER root is never opened, whatever a config names.
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
                if _other_root(Path(path), roots_dir, own_root):
                    continue
                ro.append(path)
    ro += SYSTEM_RO
    seen: set[str] = set()

    def once(paths: list[str]) -> list[str]:
        kept = [p for p in paths if p not in seen]
        seen.update(kept)
        return kept

    return Lists(once(rw), once(ro), [str(installs)])


def _other_root(path: Path, roots_dir: Path, own_root: Path) -> bool:
    """`path` is in the folder of every workspace's root but not in this root."""
    try:
        found = path.resolve()
    except OSError:
        return True
    inside = found == roots_dir or roots_dir in found.parents
    return inside and found != own_root and own_root not in found.parents


def install_locks(installs: str) -> list[str]:
    """The lock files and lease folders of Hermes's install state (`~/.hermes/
    installs/<key>`): every Hermes process takes a lease on the dependency
    environment it runs from and a lock to check it (pm/runtime.py
    lease_current_runtime; else \"install state is not writable by this user\").
    Looked up when the gateway starts, so a generation a Hermes update adds is
    found; the environments themselves stay read-only."""
    out: list[str] = []
    base = Path(installs)
    if not base.is_dir():
        return out
    for depth in range(1, 6):
        for found in base.glob("/".join(["*"] * depth)):
            name = found.name
            lease = name == ".leases" and found.is_dir()
            lock = name.endswith(".lock") and name != "uv.lock" and found.is_file()
            if lease or lock:
                out.append(str(found))
    return sorted(out)


def main(args: list[str]) -> None:
    if "--" not in args:
        sys.exit("usage: wall.py [--rw DIR]... [--ro DIR]... [--locks DIR] -- command [args]")
    cut = args.index("--")
    rw: list[str] = []
    ro: list[str] = []
    head = args[:cut]
    for flag, value in zip(head[::2], head[1::2], strict=False):
        if flag == "--locks":
            rw += install_locks(value)
        else:
            (rw if flag == "--rw" else ro if flag == "--ro" else []).append(value)
    command = args[cut + 1 :]
    if not command:
        sys.exit("wall.py: no command")
    # A writable folder that isn't there yet (a fresh home has no ~/.local/state)
    # could never be made once walled: make it first.
    for folder in rw:
        with contextlib.suppress(OSError):
            Path(folder).mkdir(parents=True, exist_ok=True)
    try:
        wall(rw, ro)
    except OSError as error:
        sys.exit(f"wall.py: the Landlock wall could not be set ({error}); not starting")
    os.execvp(command[0], command)  # noqa: S606 - Hermes's own command, as given


if __name__ == "__main__":
    main(sys.argv[1:])
