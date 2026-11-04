"""Foreign process records left in a profile moved out of the shared Hermes home
(migrate_root): Hermes's processes.json is cleaned of what this workspace's agent
did not start.

Owns: Which pids are agos-core's own and the rewrite of that one file.

Must not: Kill any process or touch a home that was not moved (a root's file is Hermes's
alone).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("agos.engine")


__all__ = [
    "_protected_pids",
    "scrub_foreign_processes",
]


def _protected_pids() -> set[int]:
    """agos-core, its process group and its parents."""
    pids = {os.getpid(), os.getppid()}
    with contextlib.suppress(OSError):
        pids.add(os.getpgid(0))
    pid = os.getppid()
    for _ in range(12):  # walk up the parents
        try:
            out = subprocess.run(  # noqa: S603 - fixed argv
                ["/bin/ps", "-o", "ppid=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            break
        if not out.isdigit() or int(out) <= 1:
            break
        pid = int(out)
        pids.add(pid)
    return pids


def scrub_foreign_processes(profile_home: Path) -> int:
    """Only for a profile moved out of the shared Hermes home (migrate_root): while
    it was a profile there, the owner's multiplexed gateway could record its own
    background processes in its `processes.json` (Hermes scope leak), and the
    workspace gateway would "recover" and later kill them (once agos-core itself).
    A workspace root (ADR 0020) is no profile of any other gateway, and Hermes's
    registry checks each pid's start time (tools/process_registry.py
    host_start_time), so a root's own file is Hermes's alone."""
    path = profile_home / "processes.json"
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        return 0
    if not isinstance(entries, list):
        return 0
    protected = _protected_pids()

    sandbox = f"hermes-profile={profile_home.name}"

    def foreign(entry: object) -> bool:
        """Only processes this workspace's own agent started are kept: they run
        in its sandbox (cwd under /workspace). Anything else — agos-core, its
        parents, host shells recorded by another Hermes — is foreign."""
        if not isinstance(entry, dict):
            return True
        command = str(entry.get("command") or "")
        pids = {entry.get("pid"), entry.get("pgid")}
        if pids & protected or "agos_core" in command:
            return True
        cwd = str(entry.get("cwd") or "")
        return not (cwd.startswith("/workspace") or sandbox in command)

    kept = [e for e in entries if not foreign(e)]
    removed = len(entries) - len(kept)
    if removed:
        tmp = path.with_suffix(".json.agos")
        tmp.write_text(json.dumps(kept, indent=2))
        tmp.replace(path)
        log.warning("removed %d foreign process record(s) from %s", removed, path)
    return removed
