"""Subscription logins started from the app (Settings → Models).

The owner clicks Connect; agos-core runs Hermes's own login for that provider as
the AGOS user, in the Hermes that will use it (a workspace's own root, ADR 0020),
reads the link and code Hermes prints, and hands them to the browser. He finishes on the
provider's page; Hermes saves the login itself. No secret passes through here:
only the public sign-in link, the one-time device code he types on the
provider's page, and (Claude only) the authorization code he pastes back, which
goes straight to Hermes's stdin.
"""

import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python
from agos_core.engine.waits import hermes_wait

Status = Literal["idle", "starting", "waiting", "checking", "done", "failed", "cancelled"]

# AGOS provider id → Hermes provider slug for a subscription login.
SLUGS = {
    "openai": "openai-codex",
    "claude": "anthropic",
    "copilot": "copilot",
    "xai": "xai-oauth",
    "nous": "nous",
}


def slug_of(provider: str) -> str:
    """Hermes's provider id (Hermes's other providers use their own id in AGOS)."""
    from agos_core.engine.models import ALWAYS_LISTED

    if provider in ALWAYS_LISTED and provider not in SLUGS:  # one of the five, key only
        raise ValueError("This provider has no subscription login.")
    slug = SLUGS.get(provider, provider)
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", slug):
        raise ValueError("This provider has no subscription login.")
    return slug


# A tool service's sign-in (Hermes's `post_setup` on it) → the login above.
TOOL_LOGINS = {"xai_grok": "xai", "openai_codex": "openai"}
# The button's words for each login AGOS can start.
SIGN_IN_LABELS = {
    "xai": "Sign in to xAI (Grok)",
    "openai": "Sign in to OpenAI (ChatGPT)",
    "nous": "Sign in to Nous Portal",
    "claude": "Sign in to Claude",
    "copilot": "Sign in to GitHub Copilot",
}


def sign_in_for(service: dict[str, object]) -> dict[str, object] | None:
    """The sign-in a tool service needs, as the web shows it: the login AGOS starts
    (`id`, None when Hermes's service signs in a way AGOS can't start yet) and its
    words. None: the service needs no sign-in."""
    step = str(service.get("login") or "")
    if service.get("nous"):
        return {"id": "nous", "label": SIGN_IN_LABELS["nous"]}
    login = TOOL_LOGINS.get(step)
    if login is not None:
        return {"id": login, "label": SIGN_IN_LABELS.get(login, f"Sign in ({login})")}
    if step and service.get("login_is_auth"):
        return {
            "id": None,
            "label": f"This service signs in with the engine's own “{step}” login, which "
            "AGOS can't start yet: run `hermes tools` on this machine.",
        }
    return None


# Hermes's post_setup steps that are installs (run once for every workspace).
NOT_INSTALLS = frozenset({"xai_grok", "openai_codex", "spotify", "langfuse"})
LOGIN_TIMEOUT_S = 15 * 60

_COPILOT_LOGIN = """
import sys
from hermes_cli.copilot_auth import copilot_device_code_login
from hermes_cli.config import save_env_value
token = copilot_device_code_login(timeout_seconds=900)
if not token:
    sys.exit(1)
save_env_value("COPILOT_GITHUB_TOKEN", token)
print("Copilot login saved.")
"""

_LOGOUT = """
import sys
slug = sys.argv[1]
if slug == "copilot":
    from hermes_cli.config import remove_env_value
    remove_env_value("COPILOT_GITHUB_TOKEN")
else:
    from hermes_cli.auth import clear_provider_auth
    clear_provider_auth(slug)
print("ok")
"""

_URL = re.compile(r"https://[^\s│╭╰─]+")
_CODE_AFTER = re.compile(r"(?:Enter this code|enter code):\s*([A-Z0-9][A-Z0-9-]{3,})")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class LoginSession:
    provider: str
    workspace: str | None = None
    proc: subprocess.Popen[bytes] | None = None
    status: Status = "starting"
    url: str | None = None
    user_code: str | None = None
    needs_code: bool = False
    message: str = ""
    started: float = field(default_factory=time.monotonic)
    output: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "workspace": self.workspace,
            "status": self.status,
            "url": self.url,
            "userCode": self.user_code,
            "needsCode": self.needs_code,
            "message": self.message,
        }


def parse_output(text: str) -> tuple[str | None, str | None, bool]:
    """(sign-in link, device code, wants a pasted code) from what Hermes printed."""
    clean = _ANSI.sub("", text)
    # Hermes prints its "Portal:" (the provider's home) before the page to open.
    pages = "\n".join(ln for ln in clean.splitlines() if not ln.strip().startswith("Portal:"))
    url_match = _URL.search(pages)
    code_match = _CODE_AFTER.search(clean)
    needs_code = "Paste it below" in clean or "Authorization code:" in clean
    return (
        url_match.group(0).rstrip(".,)") if url_match else None,
        code_match.group(1) if code_match else None,
        needs_code,
    )


def last_line(text: str) -> str:
    lines = [ln.strip(" .✗") for ln in _ANSI.sub("", text).splitlines() if ln.strip(" .")]
    return lines[-1][:300] if lines else ""


class ProviderLogins:
    """At most one running login per (workspace, provider), kept in agos-core's memory.

    A subscription login is made in the Hermes that will use it: a workspace's own
    root (`workspace` given, ADR 0020: each root signs in on its own, the way Hermes
    wants single-use refresh tokens kept), or the shared home for the logins only
    the shared home uses (tool services, Copilot, Nous).
    """

    def __init__(
        self,
        engine: EngineConfig,
        is_connected: Callable[[str, str | None], bool],
        on_connected: Callable[[str, str | None], None] | None = None,
        home_of: Callable[[str], Path] | None = None,
    ) -> None:
        self.engine = engine
        self.is_connected = is_connected
        # After a login (AGOS turns the root's borrowing off: it has its own now).
        self.on_connected = on_connected
        # A workspace's Hermes root (HERMES_HOME of its login).
        self.home_of = home_of
        self._sessions: dict[str, LoginSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider: str, workspace: str | None) -> str:
        return f"{workspace}/{provider}" if workspace else provider

    def _env(self, workspace: str | None = None) -> dict[str, str]:
        env = {
            "HOME": str(self.engine.host_home),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "PYTHONUNBUFFERED": "1",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "2000",
            **self.engine.runtime_env(),
        }
        if workspace:
            if self.home_of is None:
                raise ValueError("This workspace isn't set up on its own yet.")
            env["HERMES_HOME"] = str(self.home_of(workspace))
        return env

    def _argv(self, provider: str) -> list[str]:
        slug = slug_of(provider)
        if slug == "copilot":
            return [hermes_python(self.engine), "-c", _COPILOT_LOGIN]
        return [self.engine.hermes_bin, "auth", "add", slug, "--type", "oauth", "--no-browser"]

    def get(self, provider: str, workspace: str | None = None) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(self._key(provider, workspace))
        if session is None:
            return LoginSession(provider, workspace, status="idle").view()
        self._expire(session)
        return session.view()

    def start(self, provider: str, workspace: str | None = None) -> dict[str, object]:
        self.cancel(provider, workspace)
        env = self._env(workspace)
        session = LoginSession(provider, workspace)
        off_loop("hermes login")
        session.proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            self._argv(provider),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        with self._lock:
            self._sessions[self._key(provider, workspace)] = session
        threading.Thread(target=self._follow, args=(session,), daemon=True).start()
        # Wait briefly for the link so the first answer already carries it.
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and session.status == "starting":
            time.sleep(0.2)
        return session.view()

    def send_code(
        self, provider: str, code: str, workspace: str | None = None
    ) -> dict[str, object]:
        with self._lock:
            session = self._sessions.get(self._key(provider, workspace))
        code = code.strip()
        if session is None or session.proc is None or session.status != "waiting":
            raise ValueError("No login is waiting. Click Connect again.")
        if not session.needs_code:
            raise ValueError("This login doesn't take a code here.")
        if not code or len(code) > 4000 or any(c in code for c in "\r\n"):
            raise ValueError("Paste the code exactly as the page shows it.")
        stdin = session.proc.stdin
        if stdin is None:
            raise ValueError("The login stopped. Click Connect again.")
        try:
            stdin.write(code.encode() + b"\n")
            stdin.flush()
        except OSError as error:
            raise ValueError("The login stopped. Click Connect again.") from error
        session.status = "checking"
        session.message = "Checking the code…"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and session.status == "checking":
            time.sleep(0.3)
        return session.view()

    def cancel(self, provider: str, workspace: str | None = None) -> dict[str, object]:
        with self._lock:
            session = self._sessions.pop(self._key(provider, workspace), None)
        if session is None:
            return LoginSession(provider, workspace, status="idle").view()
        if session.status in ("starting", "waiting", "checking"):
            session.status = "cancelled"
            session.message = "Login cancelled."
        _kill(session.proc)
        return session.view()

    def logout(self, provider: str, workspace: str | None = None) -> None:
        """Hermes's own logout (`clear_provider_auth`, what `hermes logout` runs), in
        the Hermes that holds the login."""
        self.cancel(provider, workspace)
        off_loop("hermes logout")
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [hermes_python(self.engine), "-c", _LOGOUT, slug_of(provider)],
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=self._env(workspace),
            check=False,
        )
        hermes_contract.ran(result)
        if result.returncode != 0:
            raise RuntimeError(
                last_line(result.stderr or result.stdout) or "The engine did not log out."
            )

    def _expire(self, session: LoginSession) -> None:
        if session.status in ("starting", "waiting", "checking") and (
            time.monotonic() - session.started > LOGIN_TIMEOUT_S
        ):
            session.status = "failed"
            session.message = "The login timed out. Click Connect to try again."
            _kill(session.proc)

    def _follow(self, session: LoginSession) -> None:
        proc = session.proc
        if proc is None or proc.stdout is None:
            return
        fd = proc.stdout.fileno()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            with session.lock:
                session.output = (session.output + chunk.decode(errors="replace"))[-20000:]
                url, code, needs = parse_output(session.output)
                pasted = slug_of(session.provider) == "anthropic"
                ready = bool(url) and (needs if pasted else bool(code))
                if ready and session.status == "starting":
                    session.url, session.user_code, session.needs_code = url, code, needs
                    session.status = "waiting"
                    session.message = (
                        "Open the page, allow access, then paste the code it shows."
                        if needs
                        else "Open the page and enter the code. This card updates by itself."
                    )
        code_rc = proc.wait()
        if session.status == "cancelled":
            return
        connected = False
        if code_rc == 0:
            session.status = "checking"
            session.message = "Checking the login…"
            try:
                connected = self.is_connected(session.provider, session.workspace)
            except Exception:  # noqa: BLE001 - reported to the owner as a failed check
                connected = False
        if connected and self.on_connected is not None:
            try:
                self.on_connected(session.provider, session.workspace)
            except Exception as error:  # noqa: BLE001 - shown to the owner
                session.status = "failed"
                session.message = f"Signed in, but the workspace was not updated: {error}"
                return
        if connected:
            session.status = "done"
            session.message = "Connected."
        else:
            session.status = "failed"
            session.message = _failure(session.output)


def _failure(output: str) -> str:
    """Why a login did not end connected, in Hermes's words (never its success line)."""
    line = last_line(output)
    if not line or line.startswith("Added "):
        return "The sign-in finished, but the login is not there. Click Connect to try again."
    return line


def _kill(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
