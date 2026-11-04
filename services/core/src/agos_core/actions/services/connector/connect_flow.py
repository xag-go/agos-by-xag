"""Connecting an app: the login flow Hermes runs (and Google's), its callback, waiting on it, recording the login.
Must not: disconnect an app or touch Composio's keys.

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.connector.app_catalog import (
    _HELPER,
    FLOW_TTL_S,
    GOOGLE_MCP,
    Flow,
    _title,
    catalog,
    connectors_home,
    workspace_home,
)
from agos_core.actions.services.connector.workspace_apps import _login_row, _turn_on
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import workspace_app_logins as logins_repo
from agos_core.db.activity import add_activity
from agos_core.db.rows import dump_json
from agos_core.domain.secrets import same_secret
from agos_core.engine import apps as eng
from agos_core.engine import google as gg
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python, hermes_repo
from agos_core.hermes_gateway import process as hermes_process

__all__ = [
    "LOGIN_PREFIX",
    "Process",
    "check_redirect",
    "deliver_callback",
    "get_flow",
    "login_home",
    "spawn",
    "start_connect",
    "wait_flow",
]

# ---- connecting (login) ---------------------------------------------------------------


class Process(Protocol):
    stdin: Any
    stdout: Any

    def poll(self) -> int | None: ...
    def kill(self) -> None: ...


@dataclass
class _Flow:
    id: str
    workspace_id: str
    app: str
    proc: Process
    created: float = field(default_factory=time.monotonic)
    status: str = "starting"
    url: str | None = None
    state: str | None = None
    error: str | None = None
    tools: list[dict[str, str]] = field(default_factory=list)
    # The login finished; status turns "connected" after it is saved and applied.
    done: bool = False
    google: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_flows: dict[str, _Flow] = {}
_flows_lock = threading.Lock()


def _spawn(core: Core, workspace_id: str, job: dict[str, str]) -> Process:
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    python = hermes_python(core.engine.settings)
    home = login_home(core, workspace_id)
    off_loop("hermes apps helper")
    return hermes_process.spawn_process(
        [python, str(_HELPER), json.dumps(job)],
        cwd=str(hermes_repo(core.engine.settings) or Path(python).parent),
        stdin=hermes_process.PIPE,
        stdout=hermes_process.PIPE,
        stderr=hermes_process.DEVNULL,
        text=True,
        env={
            "HOME": str(core.engine.settings.host_home),
            "PATH": "/usr/bin:/bin",
            "HERMES_HOME": str(home),
            **core.engine.settings.runtime_env(),
        },
        start_new_session=True,
    )


LOGIN_PREFIX = "agoslogin-"  # never a workspace's own profile (those are agos-<id>)


def login_home(core: Core, workspace_id: str) -> Path:
    """Where the login helper runs Hermes for one workspace: a profile of the AGOS
    Hermes (so Hermes finds its own install) whose `mcp-tokens` is that workspace's
    own login folder. Nothing else is kept there."""
    assert core.engine is not None
    home = core.engine.settings.hermes_home / "profiles" / f"{LOGIN_PREFIX}w-{workspace_id}"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    eng.link_tokens(home, workspace_home(core, workspace_id))
    return home


spawn = _spawn  # tests replace this


def check_redirect(redirect_uri: str) -> str:
    parts = urlsplit(redirect_uri)
    local = parts.hostname in ("localhost", "127.0.0.1")
    if parts.scheme not in ("http", "https") or (parts.scheme == "http" and not local):
        raise ActionError("Open AGOS on this computer (or over HTTPS) to connect an app.")
    if parts.path != "/connectors/callback" or parts.query or parts.fragment:
        raise ActionError("Wrong return address.")
    return redirect_uri


def start_connect(core: Core, workspace_id: str, name: str, redirect_uri: str) -> Flow:
    """Log THIS workspace in to an app (its own account)."""
    require_workspace(core, workspace_id)
    app = catalog(core).get(name)
    if app is None:
        raise NotFoundError("This app")
    if app.locked:
        raise ActionError(app.locked, 409)
    if app.auth == "none":
        raise ActionError("This app needs no login; just turn it on.", 409)
    check_redirect(redirect_uri)
    _sweep()
    with _flows_lock:
        for old in list(_flows.values()):
            if (
                old.workspace_id == workspace_id
                and old.app == name
                and old.status in ("starting", "authorize")
            ):
                _end(old, "Replaced by a new login.")
    if app.source == "google":
        return _start_google(core, workspace_id, name, redirect_uri)
    job: dict[str, Any] = {
        "name": eng.server_name(name),
        "url": app.url,
        "redirect_uri": redirect_uri,
    }
    if app.oauth_client is not None:
        job["oauth"] = {"client_id": app.oauth_client[0], "client_secret": app.oauth_client[1]}
    proc = spawn(core, workspace_id, job)
    flow = _Flow(id=secrets.token_urlsafe(12), workspace_id=workspace_id, app=name, proc=proc)
    with _flows_lock:
        _flows[flow.id] = flow
    threading.Thread(target=_read, args=(core, flow), daemon=True).start()
    return _public(flow)


class _NoProcess:
    """Google's login runs inside the core; nothing to start or stop."""

    stdin = None
    stdout: tuple[str, ...] = ()

    def poll(self) -> int | None:
        return None

    def kill(self) -> None:
        return None


def _start_google(core: Core, workspace_id: str, name: str, redirect_uri: str) -> Flow:
    client = gg.load_client(connectors_home(core))
    if client is None:
        raise ActionError("AGOS's Google app file is missing.", 409)
    try:
        redirect = gg.pick_redirect(client, redirect_uri)
    except gg.GoogleError as error:
        raise ActionError(str(error), 409) from error
    verifier, challenge = gg.pkce()
    state = secrets.token_urlsafe(24)
    flow = _Flow(
        id=secrets.token_urlsafe(12), workspace_id=workspace_id, app=name, proc=_NoProcess()
    )
    flow.state = state
    flow.url = gg.login_url(client, redirect, state, challenge)
    flow.status = "authorize"
    flow.google = {"verifier": verifier, "redirect": redirect}
    with _flows_lock:
        _flows[flow.id] = flow
    return _public(flow)


def _finish_google(core: Core, flow: _Flow, code: str | None, error: str | None) -> None:
    try:
        if error or not code:
            raise gg.GoogleError(
                "Google login was cancelled." if error == "access_denied" else (error or "No code.")
            )
        client = gg.load_client(connectors_home(core))
        if client is None:
            raise gg.GoogleError("AGOS's Google app file is missing.")
        gg.finish_login(
            workspace_home(core, flow.workspace_id),
            client,
            code,
            flow.google["redirect"],
            flow.google["verifier"],
        )
        _google_connected(core, flow.workspace_id, flow.app)
        with flow.lock:
            flow.done = True
    except (gg.GoogleError, OSError, KeyError) as failure:
        with flow.lock:
            flow.status, flow.error = "error", str(failure)[:500]
    _record(core, flow)
    with flow.lock:
        if flow.done and flow.status != "error":
            flow.status = "connected"


def _read(core: Core, flow: _Flow) -> None:
    for line in flow.proc.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        with flow.lock:
            if event.get("event") == "authorize":
                flow.url = str(event.get("url") or "")
                states = parse_qs(urlsplit(flow.url).query).get("state") or []
                flow.state = states[0] if states else None
                flow.status = "authorize"
            elif event.get("event") == "done":
                flow.tools = [
                    {"name": str(t["name"])[:200], "description": str(t.get("description", ""))}
                    for t in event.get("tools") or []
                ][:500]
                flow.done = True
            elif event.get("event") == "error":
                flow.error = str(event.get("message") or "Login failed.")[:500]
                flow.status = "error"
    with flow.lock:
        if flow.status in ("starting", "authorize") and not flow.done:
            flow.status, flow.error = "error", "The login stopped."
    _record(core, flow)
    # "connected" only once it is saved and on in the workspaces that asked, so
    # whoever waits on the login sees the finished state, never a half one.
    with flow.lock:
        if flow.done and flow.status != "error":
            flow.status = "connected"


def _save_login(core: Core, workspace_id: str, name: str, tools: list[dict[str, str]]) -> None:
    logins_repo.save_connected(core.db, workspace_id, name, dump_json(tools))


def _google_connected(core: Core, workspace_id: str, asked: str) -> None:
    """Drive, Sheets and Docs share this workspace's one Google login: all three are
    connected; the one it was connected from turns on (the others stay as they were)."""
    for name in GOOGLE_MCP:
        _save_login(core, workspace_id, name, [])
    _turn_on(core, workspace_id, asked)


def _record(core: Core, flow: _Flow) -> None:
    ok = flow.done and flow.status != "error"
    if ok and not flow.google:
        _save_login(core, flow.workspace_id, flow.app, flow.tools)
        # Connected from this workspace = wanted here: it is on at once.
        _turn_on(core, flow.workspace_id, flow.app)
    elif (
        not ok
        and _login_row(core, flow.workspace_id, flow.app) is not None
        and flow.error != "Replaced by a new login."
    ):
        # A failed re-login keeps the old login (Hermes restores it); only note the error.
        logins_repo.set_error(core.db, flow.workspace_id, flow.app, flow.error)
    if ok:
        add_activity(
            core.db,
            flow.workspace_id,
            kind="connector.changed",
            text=f"{_title(flow.app)} connected",
        )
    if flow.error != "Replaced by a new login.":
        # Requests from a chat waiting on this login go on (or say why not).
        from agos_core.actions import capabilities  # late: it imports this module

        capabilities.after_login(core, flow.workspace_id, flow.app, ok, flow.error)


def _public(flow: _Flow) -> Flow:
    with flow.lock:
        return Flow(
            id=flow.id,
            workspace_id=flow.workspace_id,
            app=flow.app,
            status=flow.status,  # type: ignore[arg-type]
            url=flow.url if flow.status == "authorize" else None,
            error=flow.error,
        )


def get_flow(flow_id: str) -> Flow:
    with _flows_lock:
        flow = _flows.get(flow_id)
    if flow is None:
        raise NotFoundError("This login")
    return _public(flow)


def deliver_callback(
    state: str,
    code: str | None,
    error: str | None,
    iss: str | None,
    core: Core | None = None,
) -> Flow:
    """The browser came back to AGOS from the app's login page."""
    with _flows_lock:
        flow = next(
            (f for f in _flows.values() if same_secret(state, f.state) and f.status == "authorize"),
            None,
        )
    if flow is None:
        raise NotFoundError("This login (it expired or was already used)")
    if flow.google:
        with flow.lock:
            if flow.google.get("used"):
                raise NotFoundError("This login (it expired or was already used)")
            flow.google["used"] = "1"
        if core is None:
            raise ActionError("The core isn't ready.", 409)
        threading.Thread(target=_finish_google, args=(core, flow, code, error), daemon=True).start()
        return _public(flow)
    payload = {"code": code, "state": state, "error": error, "iss": iss}
    try:
        flow.proc.stdin.write(json.dumps(payload) + "\n")
        flow.proc.stdin.flush()
    except (OSError, ValueError) as err:
        raise ActionError("The login stopped; start it again.", 409) from err
    return _public(flow)


def wait_flow(flow_id: str, timeout: float = 90) -> Flow:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        flow = get_flow(flow_id)
        if flow.status in ("connected", "error"):
            return flow
        time.sleep(0.3)
    return get_flow(flow_id)


def _end(flow: _Flow, reason: str) -> None:
    with flow.lock:
        if flow.status in ("starting", "authorize"):
            flow.status, flow.error = "error", reason
    with contextlib.suppress(OSError):
        flow.proc.kill()


def _sweep() -> None:
    with _flows_lock:
        for key, flow in list(_flows.items()):
            if time.monotonic() - flow.created > FLOW_TTL_S:
                _end(flow, "The login took too long.")
                del _flows[key]
