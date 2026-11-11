"""A card's runtime services and preview links (Step 59, F49).

A card's worker starts a dev server or preview with its agos_service tool (the
agos-guard's services.py): Hermes runs it as its own background process (its
terminal tool, background + persist_on_release, so it outlives the worker's run;
Hermes's process registry and processes.json have it). The guard tells AGOS the
process Hermes gave (session id, pid, pid scope) and the port; AGOS keeps that row
(card_services) because Hermes's processes.json is rewritten by whichever process
of the profile writes last, and has no port or card.

The preview opens through AGOS's own web app at /preview/<ws>/<card>/<port>/, so it
is reached only the way AGOS is (Tailscale, never public); the web proxies to the
service on this machine (or its sandbox's address) with a sandboxed page policy, so
the preview's scripts never run as AGOS. Stop: Hermes's own process when the
worker still runs it (the tool), else a TERM to the pid AGOS was given (checked
against its start time first, so a reused pid is never stopped).
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import sqlite3
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import card_services as card_services_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import now

log = logging.getLogger("agos.card_services")

MAX_RUNNING = 6  # per card: a worker that keeps starting servers is refused
PROBE_S = 0.3


def preview_path(workspace_id: str, card_id: str, port: int) -> str:
    """Where the web app shows this service (a path of AGOS's own address)."""
    return f"/preview/{workspace_id}/{card_id}/{port}/"


def _agos_profile(core: Core, workspace_id: str, hermes_name: str) -> str:
    """The AGOS profile of the Hermes profile the worker runs as ("default" is the
    Co-Founder's, "a-<name>" a member's); refused when it is not this workspace's."""
    if core.engine is None:
        raise ActionError("The engine isn't set up yet.")
    own = core.engine.profile(workspace_id)
    name = own if hermes_name in ("", "default") else f"{own}--{hermes_name}"
    if name not in core.engine.own_profiles(workspace_id):
        raise ActionError("That profile is not this workspace's.")
    return name


def _start_mark(pid: int) -> int | None:
    """The pid's start time on this machine (/proc/<pid>/stat field 22), None when
    there is no such process (or no /proc)."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = text.rsplit(")", 1)[1].split()
        return int(fields[19])
    except (OSError, IndexError, ValueError):
        return None


def _alive(row: sqlite3.Row) -> bool:
    if row["stopped_at"]:
        return False
    if row["pid_scope"] != "host" or not row["pid"]:
        return True  # a sandbox's pid: Hermes's sandbox has it, the port tells
    mark = _start_mark(int(row["pid"]))
    return mark is not None and (row["started_mark"] is None or mark == row["started_mark"])


def _host(core: Core, row: sqlite3.Row) -> str:
    """Where the service listens: this machine, or the worker's sandbox."""
    if row["pid_scope"] == "sandbox" and core.engine is not None:
        found = core.engine.sandbox_address(str(row["profile"]))
        if found:
            return found
    return "127.0.0.1"


def _answers(host: str, port: int) -> bool:
    with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=PROBE_S):
        return True
    return False


def _view(core: Core, workspace_id: str, row: sqlite3.Row, *, probe: bool) -> dict[str, Any]:
    running = _alive(row)
    return {
        "id": int(row["id"]),
        "card": str(row["card"]),
        "label": str(row["label"] or ""),
        "command": str(row["command"]),
        "port": int(row["port"]),
        "processId": str(row["process_id"] or ""),
        "running": running,
        "answering": running and probe and _answers(_host(core, row), int(row["port"])),
        "preview": preview_path(workspace_id, str(row["card"]), int(row["port"])),
        "startedAt": str(row["started_at"]),
        "stoppedAt": row["stopped_at"],
    }


def _rows(core: Core, workspace_id: str, card_id: str) -> list[sqlite3.Row]:
    return card_services_repo.of_card(core.db, workspace_id, card_id)


def of_card(core: Core, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
    """The card's services, newest first: running ones with whether they answer."""
    out = [_view(core, workspace_id, r, probe=True) for r in _rows(core, workspace_id, card_id)]
    gone = [s for s in out if not s["running"] and not s["stoppedAt"]]
    if gone:
        at = now()
        with transaction(core.db):
            for service in gone:
                card_services_repo.stopped(core.db, workspace_id, int(service["id"]), at)
                service["stoppedAt"] = at  # found gone: Hermes's process ended
    return out


def from_tool(
    core: Core,
    workspace_id: str,
    *,
    action: str,
    card_id: str,
    profile: str = "",
    process_id: str = "",
    pid: int | None = None,
    pid_scope: str = "host",
    command: str = "",
    port: int = 0,
    label: str = "",
) -> dict[str, Any]:
    """The agos_service tool's report: `started` (Hermes started it), `stopped`
    (Hermes stopped it), `list`. Answers what the agent reads."""
    if action == "list":
        return {"services": [_short(s) for s in of_card(core, workspace_id, card_id)]}
    if action == "stopped":
        with transaction(core.db):
            card_services_repo.stop_process(core.db, workspace_id, card_id, process_id, now())
        return {"ok": True}
    if not 1024 <= port <= 65535:
        return {"error": "Give the port the server listens on (1024-65535)."}
    try:
        name = _agos_profile(core, workspace_id, profile)
    except ActionError as error:
        return {"error": error.message}
    running = [s for s in of_card(core, workspace_id, card_id) if s["running"]]
    if len(running) >= MAX_RUNNING:
        return {"error": f"This card already runs {MAX_RUNNING} services: stop one first."}
    with transaction(core.db):
        card_services_repo.stop_on_port(core.db, workspace_id, card_id, port, now())
        card_services_repo.add(
            core.db,
            workspace_id,
            card_id,
            {
                "profile": name,
                "process_id": process_id[:64],
                "pid": pid,
                "pid_scope": pid_scope,
                "started_mark": _start_mark(pid) if pid and pid_scope == "host" else None,
                "command": command[:2000],
                "port": port,
                "label": label.strip()[:80],
                "started_at": now(),
            },
        )
    return {
        "ok": True,
        "preview": preview_path(workspace_id, card_id, port),
        "note": "The owner opens it from the card in AGOS (Services). Serve it under that "
        "path (a base path), or at / with relative links.",
    }


def _short(s: dict[str, Any]) -> dict[str, Any]:
    return {
        k: s[k]
        for k in ("label", "command", "port", "processId", "running", "answering", "preview")
    }


def _one(core: Core, workspace_id: str, service_id: int) -> sqlite3.Row:
    row = card_services_repo.get(core.db, workspace_id, service_id)
    if row is None:
        raise NotFoundError("This service")
    return row


def stop(core: Core, workspace_id: str, service_id: int) -> dict[str, Any]:
    """The owner's Stop: TERM to the process (and its group) Hermes started, when it
    is still the same process; a sandbox's one is stopped inside its sandbox."""
    row = _one(core, workspace_id, service_id)
    if _alive(row) and row["pid"]:
        pid = int(row["pid"])
        if row["pid_scope"] == "host":
            with contextlib.suppress(OSError):
                group = os.getpgid(pid)
                if group != os.getpgid(0):  # never AGOS's own group
                    os.killpg(group, signal.SIGTERM)
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
        elif core.engine is not None:
            core.engine.sandbox_kill(str(row["profile"]), pid)
    with transaction(core.db):
        card_services_repo.stopped(core.db, workspace_id, service_id, now())
    return _view(core, workspace_id, _one(core, workspace_id, service_id), probe=False)


def target(core: Core, workspace_id: str, card_id: str, port: int) -> dict[str, Any]:
    """Where the web's preview proxy goes for /preview/<ws>/<card>/<port>/: only a
    running service this card's worker started on that port."""
    for row in _rows(core, workspace_id, card_id):
        if int(row["port"]) == port and _alive(row):
            return {"host": _host(core, row), "port": port}
    raise NotFoundError("This preview")
