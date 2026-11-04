"""Sign a workspace in to an MCP server with OAuth, from the app.

Runs Hermes's own `hermes -p <profile> mcp login <server>` (the same flow as
`hermes mcp add … --auth oauth` in a terminal): Hermes makes the authorize URL,
listens on its loopback callback, exchanges the code and stores the tokens in
the workspace's profile (`mcp-tokens/`). AGOS only hands the URL to the web app
(which opens it in the owner's browser) and reports when it is done. Tokens
never pass through AGOS. One workspace's sign-in is never seen by another.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.library import apply_workspace, oauth_signed_in
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.engine.loop_guard import off_loop
from agos_core.hermes_gateway import process as hermes_process

log = logging.getLogger(__name__)

_URL = re.compile(r"https://\S+")
WAIT_FOR_URL_S = 40
FLOW_LIFETIME_S = 15 * 60


@dataclass
class Flow:
    workspace_id: str
    server: str
    process: hermes_process.Popen[str]
    started: float = field(default_factory=time.monotonic)
    url: str | None = None
    status: str = "starting"  # starting | waiting | done | error
    error: str | None = None
    output: list[str] = field(default_factory=list)
    ready: threading.Event = field(default_factory=threading.Event)


_flows: dict[tuple[str, str], Flow] = {}
_lock = threading.Lock()
# Servers being signed in right now: their config keeps `auth: oauth` before tokens exist.
signing_in: set[tuple[str, str]] = set()


def _server(core: Core, workspace_id: str, item_id: int) -> str:
    """The server's name: this workspace's own, or a shared one (Settings → Connectors).
    Another workspace's server is not found here, whatever its id."""
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "mcp" or row["workspace_id"] not in (None, workspace_id):
        raise NotFoundError("This MCP server")
    return str(row["name"])


def _clean(line: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", line).strip()


def _watch(core: Core, flow: Flow) -> None:
    assert flow.process.stderr is not None
    for raw in flow.process.stderr:
        line = _clean(raw)
        if not line:
            continue
        flow.output.append(line[:300])
        if flow.url is None:
            found = _URL.search(line)
            if found and "authorize" in found.group(0):
                flow.url = found.group(0)
                flow.status = "waiting"
                flow.ready.set()
    code = flow.process.wait()
    home = core.engine.profile_home(flow.workspace_id) if core.engine else None
    ok = code == 0 and home is not None and flow.server in oauth_signed_in(home)
    if ok:
        flow.status = "done"
    else:
        flow.status = "error"
        tail = [ln for ln in flow.output if "✗" in ln or "rror" in ln or "denied" in ln.lower()]
        flow.error = (tail or flow.output or ["The sign-in did not finish."])[-1]
    signing_in.discard((flow.workspace_id, flow.server))
    flow.ready.set()
    if ok:
        _reload(core, flow.workspace_id)


def _reload(core: Core, workspace_id: str) -> None:
    """New tokens: rewrite the profile's MCP setup; the running gateway reconnects
    the server with them (Hermes's /reload-mcp: its entry is the same, its login
    is new, so Hermes's own reconcile would not touch a server already live)."""
    if core.engine is None:
        return
    from agos_core.actions.library import reload_gateway

    with contextlib.suppress(OSError):
        (core.engine.profile_home(workspace_id) / ".agos-connectors").unlink(missing_ok=True)
    apply_workspace(core, workspace_id)
    reload_gateway(core, workspace_id)


def start(core: Core, workspace_id: str, item_id: int) -> dict[str, str | None]:
    engine = core.engine
    if engine is None:
        raise ActionError("The engine is off.", 409)
    server = _server(core, workspace_id, item_id)
    from agos_core.actions.library import switches

    mine = switches(core, workspace_id).get(item_id)
    if not (mine and mine.on):
        raise ActionError("Turn this server on for the workspace first.", 409)
    key = (workspace_id, server)
    with _lock:
        # One sign-in at a time on this computer: the server sends the browser back
        # to one fixed local port, so a second open login could never finish.
        for other_key, other in list(_flows.items()):
            if other.process.poll() is None:
                other.process.terminate()
                other.status = "error"
                other.error = "Stopped: another sign-in was started."
                signing_in.discard(other_key)
        # The profile's config must say `auth: oauth` for Hermes to run the login.
        signing_in.add(key)
        with contextlib.suppress(OSError):
            (engine.profile_home(workspace_id) / ".agos-connectors").unlink(missing_ok=True)
        problem = apply_workspace(core, workspace_id)
        if problem:
            signing_in.discard(key)
            raise ActionError(problem, 503)
        env = {**engine._env(), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        env["BROWSER"] = "/usr/bin/true"  # the app opens the page, not Hermes
        # Hermes runs IN the workspace's own root (ADR 0020).
        env["HERMES_HOME"] = str(engine.profile_home(workspace_id))
        off_loop("hermes mcp sign-in")
        process = hermes_process.spawn_process(
            [
                engine.settings.hermes_bin,
                "mcp",
                "login",
                server,
                "--flow",
                "browser",
            ],
            stdin=hermes_process.PIPE,
            stdout=hermes_process.DEVNULL,
            stderr=hermes_process.PIPE,
            text=True,
            env=env,
        )
        flow = Flow(workspace_id=workspace_id, server=server, process=process)
        _flows[key] = flow
    threading.Thread(target=_watch, args=(core, flow), daemon=True).start()
    threading.Timer(FLOW_LIFETIME_S, _expire, args=(flow,)).start()
    flow.ready.wait(WAIT_FOR_URL_S)
    return snapshot(flow)


def _expire(flow: Flow) -> None:
    if flow.process.poll() is None:
        flow.process.terminate()


def snapshot(flow: Flow) -> dict[str, str | None]:
    return {"status": flow.status, "url": flow.url, "error": flow.error}


def status(core: Core, workspace_id: str, item_id: int) -> dict[str, str | None]:
    server = _server(core, workspace_id, item_id)
    flow = _flows.get((workspace_id, server))
    if flow is not None:
        return snapshot(flow)
    home = core.engine.profile_home(workspace_id) if core.engine else None
    signed = home is not None and server in oauth_signed_in(home)
    return {"status": "done" if signed else "none", "url": None, "error": None}


def sign_out(core: Core, workspace_id: str, item_id: int) -> None:
    engine = core.engine
    if engine is None:
        raise ActionError("The engine is off.", 409)
    server = _server(core, workspace_id, item_id)
    flow = _flows.pop((workspace_id, server), None)
    if flow and flow.process.poll() is None:
        flow.process.terminate()
    signing_in.discard((workspace_id, server))
    folder: Path = engine.profile_home(workspace_id) / "mcp-tokens"
    for suffix in (".json", ".client.json", ".meta.json"):
        with contextlib.suppress(OSError):
            (folder / f"{server}{suffix}").unlink(missing_ok=True)
    _reload(core, workspace_id)
