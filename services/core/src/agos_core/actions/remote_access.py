"""Settings → Access → "Use AGOS from other devices": Tailscale in one click.

AGOS has no login and listens on 127.0.0.1 only. Another device reaches it through
the owner's Tailscale: `tailscale serve` gives this machine an HTTPS address on his
tailnet (https://<machine>.<tailnet>.ts.net) and tells AGOS who is asking (the
Tailscale-User-Login header). The web lets a request in only when its Host is the
saved address and its login is the saved one (apps/web/src/server/access.ts).

What the Activate button does, step by step (each step can stop and say why):

  find `tailscale` → is its service running? → logged in? if not, `tailscale up`
  and hand its login link to the card → once logged in, `tailscale serve --bg
  <web port>` → save the machine's address and the owner's login.

The saved part is one small file beside the internal token
(<data>/system/remote-access.json), so the web reads it on every request (with a
short cache) without asking the core. Nothing here needs sudo: setup runs
`tailscale set --operator=<agos user>` once; when it didn't, the card shows that
one command.
"""

from __future__ import annotations

import contextlib
import getpass
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core

log = logging.getLogger("agos.remote_access")

FILE_NAME = "remote-access.json"

LOGIN_WAIT_S = 20.0  # how long Activate waits for `tailscale up` to give its link
SERVE_WAIT_S = 20.0  # how long `tailscale serve --bg` may take
STATUS_WAIT_S = 8.0
MAX_ALSO_ALLOW = 20

_URL = re.compile(r"https://\S+")
_NOTHING_SERVED = re.compile(r"does not exist|not found|nothing to", re.I)
_LOGIN_NAME = re.compile(r"^[^\s,@]+@[^\s,]+$")
_LOCK = threading.RLock()  # one activation step at a time in this process


# ---- what the card is told ----------------------------------------------------------


@dataclass
class View:
    """The card's state, in plain words. `state` is one of:
    not-installed, no-daemon, needs-operator, off, waiting-login, needs-https, on,
    error."""

    state: str
    message: str = ""
    command: str = ""  # one line to run in a terminal on this machine
    login_url: str = ""  # the big button's link (Tailscale's login or HTTPS page)
    address: str = ""
    user: str = ""
    also_allow: list[str] = field(default_factory=list)
    warning: str = ""


# ---- the saved file -----------------------------------------------------------------


def saved_file(core: Core) -> Path:
    """Beside the internal token: the web reads it from the same folder."""
    return core.settings.internal_token_file.parent / FILE_NAME


def read_saved(core: Core) -> dict[str, Any] | None:
    try:
        data = json.loads(saved_file(core).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("host"), str):
        return None
    return data


def _write_saved(core: Core, data: dict[str, Any]) -> None:
    path = saved_file(core)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    tmp.replace(path)


def _forget_saved(core: Core) -> None:
    with contextlib.suppress(FileNotFoundError):
        saved_file(core).unlink()


# ---- the tailscale command ----------------------------------------------------------

# Where the apps put the command when it is not on PATH.
_KNOWN_PLACES = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)


def tailscale_bin() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    return next((p for p in _KNOWN_PLACES if Path(p).is_file()), None)


def install_command() -> str:
    system = platform.system()
    if system == "Darwin":
        return "brew install tailscale && sudo brew services start tailscale"
    if system == "Windows":
        return "winget install --id Tailscale.Tailscale -e"
    return "curl -fsSL https://tailscale.com/install.sh | sh"


def start_service_command() -> str:
    system = platform.system()
    if system == "Darwin":
        return "sudo brew services start tailscale"
    if system == "Windows":
        return "Start-Service Tailscale"
    return "sudo systemctl enable --now tailscaled"


def operator_command() -> str:
    return f"sudo tailscale set --operator={getpass.getuser()}"


def _run(binary: str, args: list[str], timeout: float) -> tuple[int, str]:
    """Runs `tailscale <args>`; (exit code, stdout + stderr). A timeout is 124."""
    try:
        done = subprocess.run(  # noqa: S603 - the tailscale command, fixed arguments
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as late:
        return 124, _text(late.stdout) + _text(late.stderr)
    except OSError as error:
        return 127, str(error)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _no_daemon(output: str) -> bool:
    low = output.lower()
    return "tailscaled" in low and ("doesn't appear to be running" in low or "connect" in low)


def _access_denied(output: str) -> bool:
    return "access denied" in output.lower() or "--operator" in output


@dataclass
class Status:
    """What `tailscale status --json` says about this machine."""

    backend: str  # Running, NeedsLogin, NeedsMachineAuth, Stopped, ...
    dns_name: str  # machine.tailnet.ts.net (no trailing dot), "" when unknown
    login: str  # the logged-in Tailscale account
    auth_url: str


def read_status(binary: str) -> Status | View:
    """The machine's Tailscale state, or the View that says why it can't be read."""
    code, out = _run(binary, ["status", "--json"], STATUS_WAIT_S)
    if code != 0 and _no_daemon(out):
        return View(
            "no-daemon",
            message="Tailscale is installed but its service isn't running on this machine.",
            command=start_service_command(),
        )
    try:
        data = json.loads(out[out.index("{") :]) if "{" in out else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return View("error", message=_last_line(out) or "Tailscale didn't answer.")
    me = _dict(data.get("Self"))
    user = _dict(_dict(data.get("User")).get(str(me.get("UserID"))))
    return Status(
        backend=str(data.get("BackendState") or ""),
        dns_name=str(me.get("DNSName") or "").rstrip(".").lower(),
        login=str(user.get("LoginName") or "").strip().lower(),
        auth_url=str(data.get("AuthURL") or ""),
    )


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


# ---- `tailscale up`: the login link -------------------------------------------------


@dataclass
class _Login:
    """A running `tailscale up` (it waits until the owner logged in)."""

    process: subprocess.Popen[str]
    lines: list[str] = field(default_factory=list)
    url: str = ""
    found: threading.Event = field(default_factory=threading.Event)

    def alive(self) -> bool:
        return self.process.poll() is None

    def output(self) -> str:
        return "\n".join(self.lines)


@dataclass
class _Pending:
    """An activation that waits for the owner (logging in, or turning HTTPS on)."""

    port: int
    login: _Login | None = None
    https_url: str = ""


_PENDING: _Pending | None = None


def _start_login(binary: str) -> _Login:
    process = subprocess.Popen(  # noqa: S603 - fixed arguments, no shell
        [binary, "up"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    login = _Login(process)

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            login.lines.append(line.rstrip())
            match = _URL.search(line)
            if match and not login.url:
                login.url = match.group(0)
                login.found.set()
        process.wait()
        login.found.set()

    threading.Thread(target=read, name="tailscale-up", daemon=True).start()
    return login


def _stop_login(pending: _Pending | None) -> None:
    if pending and pending.login and pending.login.alive():
        with contextlib.suppress(OSError):
            pending.login.process.terminate()


# ---- the steps ----------------------------------------------------------------------


def view(core: Core) -> View:
    """The card's state (polled while it waits). When the owner just logged in or
    turned HTTPS on, this finishes the activation."""
    global _PENDING
    with _LOCK:
        binary = tailscale_bin()
        saved = read_saved(core)
        if binary is None:
            return View(
                "not-installed",
                message="Tailscale isn't installed on this machine. Run this once, then "
                "press Activate:",
                command=install_command(),
            )
        pending = _PENDING
        if pending is None:
            return _view_of_saved(binary, saved)
        status = read_status(binary)
        if isinstance(status, View):
            return status
        if status.backend == "Running":
            return _finish(core, binary, status, pending.port)
        if pending.login and pending.login.alive():
            url = pending.login.url or status.auth_url
            return _waiting_login(url)
        # `tailscale up` ended without a login: say what it said.
        out = pending.login.output() if pending.login else ""
        _PENDING = None
        return _failed_up(out)


def _view_of_saved(binary: str, saved: dict[str, Any] | None) -> View:
    if saved is None:
        return View("off")
    on = _on(saved)
    status = read_status(binary)
    if isinstance(status, View) or status.backend != "Running":
        on.warning = (
            "Tailscale isn't connected on this machine right now, so other devices "
            "can't reach AGOS. Press Activate to connect it again."
        )
    return on


def _on(saved: dict[str, Any]) -> View:
    also = [str(x) for x in saved.get("alsoAllow") or [] if isinstance(x, str)]
    return View(
        "on",
        address=f"https://{saved['host']}",
        user=str(saved.get("user") or ""),
        also_allow=also,
    )


def _waiting_login(url: str) -> View:
    return View(
        "waiting-login",
        message="Log in to Tailscale in the new tab (Google, GitHub, Apple or Microsoft). "
        "This card moves on by itself once you're in.",
        login_url=url,
    )


def _failed_up(output: str) -> View:
    if _access_denied(output):
        return View(
            "needs-operator",
            message="AGOS isn't allowed to control Tailscale yet. Run this once on this "
            "machine, then press Activate again:",
            command=operator_command(),
        )
    if _no_daemon(output):
        return View(
            "no-daemon",
            message="Tailscale is installed but its service isn't running on this machine.",
            command=start_service_command(),
        )
    return View("error", message=_last_line(output) or "Tailscale didn't log in.")


def activate(core: Core, port: int) -> View:
    """The Activate button."""
    global _PENDING
    with _LOCK:
        binary = tailscale_bin()
        if binary is None:
            return view(core)
        status = read_status(binary)
        if isinstance(status, View):
            return status
        if status.backend == "Running":
            _PENDING = _Pending(port)
            return _finish(core, binary, status, port)
        pending = _PENDING
        if pending and pending.login and pending.login.alive():
            pending.port = port
            return _waiting_login(pending.login.url or status.auth_url)
        login = _start_login(binary)
        _PENDING = _Pending(port, login=login)
        login.found.wait(LOGIN_WAIT_S)
        if login.url:
            return _waiting_login(login.url)
        if login.alive():
            if status.auth_url:
                return _waiting_login(status.auth_url)
            return View(
                "waiting-login",
                message="Waiting for Tailscale to give a login link…",
            )
        # `tailscale up` is done: logged in already, or refused.
        after = read_status(binary)
        if isinstance(after, Status) and after.backend == "Running":
            return _finish(core, binary, after, port)
        _PENDING = None
        return _failed_up(login.output())


def _serving_other(binary: str, host: str, port: int) -> str:
    """What else `tailscale serve` shows on this machine's HTTPS address, if any."""
    code, out = _run(binary, ["serve", "status", "--json"], STATUS_WAIT_S)
    if code != 0 or "{" not in out:
        return ""
    try:
        data = json.loads(out[out.index("{") :])
    except ValueError:
        return ""
    web = data.get("Web") if isinstance(data, dict) else None
    site = web.get(f"{host}:443") if isinstance(web, dict) else None
    handlers = site.get("Handlers") if isinstance(site, dict) else None
    root = handlers.get("/") if isinstance(handlers, dict) else None
    target = str(root.get("Proxy") or "") if isinstance(root, dict) else ""
    ours = (f"http://127.0.0.1:{port}", f"http://localhost:{port}", str(port))
    return target if target and target.rstrip("/") not in ours else ""


def _finish(core: Core, binary: str, status: Status, port: int) -> View:
    """Logged in: serve the web on the tailnet, then save the address and login."""
    global _PENDING
    if not status.dns_name or not status.login:
        _PENDING = None
        return View(
            "error",
            message="Tailscale is logged in but gave no machine name. Turn on MagicDNS in "
            "the Tailscale admin console (DNS page), then press Activate again.",
        )
    other = _serving_other(binary, status.dns_name, port)
    if other:
        _PENDING = None
        return View(
            "error",
            message=f"Tailscale already serves something else on this machine's address "
            f"({other}). Remove it with `tailscale serve reset`, then press Activate.",
        )
    code, out = _run(binary, ["serve", "--bg", str(port)], SERVE_WAIT_S)
    if code != 0:
        url = _URL.search(out)
        if url and code == 124:  # it waits until HTTPS is turned on for the tailnet
            _PENDING = _Pending(port, https_url=url.group(0))
            return View(
                "needs-https",
                message="One more click: Tailscale needs HTTPS turned on for your tailnet. "
                "Press the button, allow it, then come back here.",
                login_url=url.group(0),
            )
        _PENDING = None
        if _access_denied(out):
            return _failed_up(out)
        return View("error", message=_last_line(out) or "tailscale serve failed.")
    before = read_saved(core) or {}
    also = [u for u in before.get("alsoAllow") or [] if isinstance(u, str)]
    saved = {
        "host": status.dns_name,
        "user": status.login,
        "alsoAllow": [u for u in also if u != status.login],
        "port": port,
        "since": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_saved(core, saved)
    _PENDING = None
    log.info("remote access on at %s", status.dns_name)
    return _on(saved)


def turn_off(core: Core) -> View:
    """Turn off: stop serving AGOS on the tailnet and forget the address and logins.
    Tailscale itself stays installed and logged in."""
    global _PENDING
    with _LOCK:
        _stop_login(_PENDING)
        _PENDING = None
        saved = read_saved(core)
        _forget_saved(core)  # first: from here on the web refuses the address
        binary = tailscale_bin()
        if binary is None or saved is None:
            return View("off")
        code, out = _run(binary, ["serve", "--https=443", "off"], SERVE_WAIT_S)
        if code != 0 and not _NOTHING_SERVED.search(out):
            log.warning("tailscale serve off: %s", _last_line(out))
            return View(
                "off",
                warning="AGOS no longer lets other devices in, but Tailscale still shows "
                "its address. To remove it too, run this on this machine:",
                command="tailscale serve reset",
            )
        return View("off")


def set_also_allow(core: Core, logins: list[str]) -> View:
    """The "Also allow" list: more Tailscale logins (family, team) let in."""
    with _LOCK:
        saved = read_saved(core)
        if saved is None:
            raise ActionError("Turn on access from other devices first.")
        clean: list[str] = []
        for raw in logins:
            login = raw.strip().lower()
            if not login:
                continue
            if not _LOGIN_NAME.match(login) or len(login) > 200:
                raise ActionError(f"“{raw.strip()}” isn't a Tailscale login (like name@gmail.com).")
            if login != saved.get("user") and login not in clean:
                clean.append(login)
        if len(clean) > MAX_ALSO_ALLOW:
            raise ActionError(f"At most {MAX_ALSO_ALLOW} other logins.")
        saved["alsoAllow"] = clean
        _write_saved(core, saved)
        return _on(saved)
