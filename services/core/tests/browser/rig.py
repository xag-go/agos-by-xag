"""The browser tests' rig: the light core (serve_light.py), the real web build's
standalone server in front of it, and Playwright's Chromium.

Environment (all optional):
    AGOS_BROWSER_PORTS   "core,web" ports (default 9611,9612)
    AGOS_WEB_STANDALONE  the web build's standalone app folder (default
                         apps/web/.next/standalone/apps/web after `pnpm --filter @agos/web build`)
    AGOS_BROWSER_OUT     where screenshots, diffs and the rig's logs go (default a temp dir)
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

CORE_DIR = Path(__file__).resolve().parents[2]
REPO = CORE_DIR.parents[1]
WEB_BUILD = REPO / "apps" / "web" / ".next"


@dataclass(frozen=True)
class Rig:
    core: str
    web: str
    state: dict[str, Any]
    out: Path

    @property
    def workspace(self) -> str:
        return str(self.state["workspace"])

    @property
    def flows(self) -> str:
        """The workspace the click tests change (the screens keep `workspace` as seeded)."""
        return str(self.state["flows"])


def ports() -> tuple[int, int]:
    core, web = (int(p) for p in (os.environ.get("AGOS_BROWSER_PORTS") or "9611,9612").split(","))
    return core, web


def out_dir() -> Path:
    given = os.environ.get("AGOS_BROWSER_OUT")
    out = Path(given) if given else Path(tempfile.mkdtemp(prefix="agos-browser-"))
    out.mkdir(parents=True, exist_ok=True)
    return out


def standalone() -> Path:
    """The standalone server's folder, with the static files and public/ beside it
    (next build leaves them out of standalone; `next start` would serve them)."""
    given = os.environ.get("AGOS_WEB_STANDALONE")
    app = Path(given) if given else WEB_BUILD / "standalone" / "apps" / "web"
    if not (app / "server.js").is_file():
        raise RuntimeError(
            f"no web build at {app}: run `pnpm --filter @agos/web build` (or set AGOS_WEB_STANDALONE)"
        )
    if not given:
        if not (app / ".next" / "static").is_dir():
            shutil.copytree(WEB_BUILD / "static", app / ".next" / "static")
        if not (app / "public").is_dir():
            shutil.copytree(REPO / "apps" / "web" / "public", app / "public")
    return app


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait(what: str, check: Any, timeout: float, proc: subprocess.Popen[bytes], log: Path) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{what}: the process ended (rc={proc.returncode}):\n{_tail(log)}")
        with contextlib.suppress(Exception):
            found = check()
            if found:
                return found
        time.sleep(0.3)
    raise RuntimeError(f"{what}: not ready after {timeout:.0f} s:\n{_tail(log)}")


def _tail(log: Path, lines: int = 40) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"


def _spawn(argv: list[str], log: Path, cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    handle: BinaryIO = log.open("ab")
    return subprocess.Popen(  # noqa: S603 - our own interpreter and node on our own files
        argv,
        cwd=cwd,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(10)


def _http_ok(url: str) -> bool:
    with urllib.request.urlopen(url, timeout=5) as answer:  # noqa: S310 - our own local server
        return bool(answer.status < 500)


@contextlib.contextmanager
def light_rig() -> Iterator[Rig]:
    """Start the light core and the web server; stop both (whatever happened)."""
    core_port, web_port = ports()
    for port in (core_port, web_port):
        if not _free(port):
            raise RuntimeError(f"port {port} is in use (AGOS_BROWSER_PORTS picks others)")
    out = out_dir()
    app = standalone()
    state_file = out / "light-rig.json"
    state_file.unlink(missing_ok=True)
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGOS_", "HERMES_"))}
    env |= {
        "AGOS_LIGHT_PORT": str(core_port),
        "AGOS_LIGHT_STATE": str(state_file),
        "TMPDIR": str(tmp),
        "PYTHONPATH": str(CORE_DIR / "src"),
    }
    core_log = out / "core.log"
    core = _spawn(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-s",
            "-p",
            "no:cacheprovider",
            "tests/browser/serve_light.py",
        ],
        core_log,
        CORE_DIR,
        env,
    )
    web: subprocess.Popen[bytes] | None = None
    try:
        _wait(
            "light core",
            lambda: state_file.is_file() and _http_ok(f"http://127.0.0.1:{core_port}/health"),
            120,
            core,
            core_log,
        )
        state = json.loads(state_file.read_text())
        web_env = {k: v for k, v in os.environ.items() if not k.startswith(("AGOS_", "HERMES_"))}
        web_env |= {
            "AGOS_CORE_URL": f"http://127.0.0.1:{core_port}",
            "AGOS_DATA_DIR": state["data_dir"],
            "AGOS_INTERNAL_TOKEN_FILE": state["token_file"],
            "HOSTNAME": "127.0.0.1",
            "PORT": str(web_port),
            "NODE_ENV": "production",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
        web_log = out / "web.log"
        node = shutil.which("node") or "node"
        web = _spawn([node, "server.js"], web_log, app, web_env)
        _wait("web server", lambda: _http_ok(f"http://127.0.0.1:{web_port}/"), 60, web, web_log)
        yield Rig(f"http://127.0.0.1:{core_port}", f"http://127.0.0.1:{web_port}", state, out)
    finally:
        if web is not None:
            _stop(web)
        _stop(core)
