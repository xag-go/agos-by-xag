"""A throwaway core for API fuzzing: the real app on 127.0.0.1, nothing real behind it.

The core runs in this process on a fresh data dir, with the test suite's fake
Hermes/Docker runner (tests/test_engine_sync.FakeRunner), every real subprocess refused
and every outbound connection refused except to the rig itself. A fuzzed "update",
"backup" or "install" therefore never touches this machine. Used by
tests/security/test_api_fuzz.py; `python tests/security/fuzz_rig.py --port 9732
--token-file F` serves it until stopped (for a hand run of Schemathesis's CLI).

Ports: lane m4's rig range 9730-9739 (9731 pytest, 9732 a hand run).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from test_engine_sync import FakeRunner

from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine import loop_guard, models
from agos_core.hermes_gateway.errors import HermesUnavailable

__all__ = ["Refused", "Rig", "serve"]

MODEL = {"provider": "claude", "mode": "cli", "model": "m", "effort": "high"}


class Refused(OSError):
    """A real subprocess or outbound connection the fuzz rig does not allow."""


class _NoPopen(subprocess.Popen):  # type: ignore[type-arg]
    """subprocess.run/Popen refused (a subclass, so `Popen[bytes]` still reads)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise Refused("the fuzz rig runs no real process")


class _RigRunner(FakeRunner):
    """The suite's fake Hermes, answering `hermes --version` like hermes_cli/banner.py."""

    def run(self, args: Any, *, timeout: float, env: dict[str, str] | None = None) -> str:
        if list(args)[1:] == ["--version"]:
            return "Hermes Agent v0.0.0-fuzz (local 0000000)"
        return super().run(args, timeout=timeout, env=env)


def _no_hermes_python(hermes_bin: str) -> Any:
    # Hermes's own Python (engine/models.hermes_python) is a real process: on the rig
    # it answers what a down Hermes answers (a 503), not "not installed" (a 500 no
    # real install hits). Still the place a real run starts Hermes: an async route
    # that reaches it on the event loop fails here under AGOS_STRICT_LOOP=1.
    loop_guard.off_loop("hermes --print-runtime-command")
    raise HermesUnavailable("fuzz-rig")


@dataclass(frozen=True)
class Rig:
    base: str
    headers: dict[str, str]
    workspace: str


def _settings(tmp: Path) -> Settings:
    hermes_home = tmp / "home" / ".hermes"
    hermes_home.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=tmp / "data",
        internal_token_file=tmp / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp / "home",
            roots_dir=tmp / "data" / "hermes",
        ),
    )


@contextlib.contextmanager
def serve(tmp: Path, port: int) -> Iterator[Rig]:
    """The core on 127.0.0.1:port with one workspace, until the block ends."""
    real_connect = socket.socket.connect
    real_popen = subprocess.Popen

    def only_the_rig(self: socket.socket, address: Any) -> None:
        if isinstance(address, tuple) and tuple(address[:2]) in (
            ("127.0.0.1", port),
            ("localhost", port),
        ):
            return real_connect(self, address)
        raise Refused("the fuzz rig makes no outbound connection")

    settings = _settings(tmp)
    real_runtime = (models._runtime_launcher, models._runtime_argv)
    models._runtime_launcher = models._runtime_argv = _no_hermes_python
    subprocess.Popen = _NoPopen  # type: ignore[misc]
    socket.socket.connect = only_the_rig  # type: ignore[method-assign,assignment]
    try:
        application = create_app(settings, background=False)
        server = uvicorn.Server(
            uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 60
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("the fuzz rig's core did not start")
        core = application.state.core
        assert settings.engine is not None
        core.engine.runner = _RigRunner(settings.engine.hermes_home)
        core.engine.start = lambda workspace_id, **_: None
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        base = f"http://127.0.0.1:{port}"
        headers = {"x-agos-internal": settings.internal_token_file.read_text().strip()}
        made = httpx.post(
            f"{base}/workspaces",
            json={"name": "Fuzz", "defaultModel": MODEL},
            headers=headers,
            timeout=60,
        )
        try:
            yield Rig(base, headers, str(made.json().get("id", "")))
        finally:
            server.should_exit = True
            thread.join(30)
    finally:
        models._runtime_launcher, models._runtime_argv = real_runtime
        subprocess.Popen = real_popen  # type: ignore[misc]
        socket.socket.connect = real_connect  # type: ignore[method-assign]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9732)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with (
        tempfile.TemporaryDirectory(prefix="agos-fuzz-") as tmp,
        serve(Path(tmp), args.port) as rig,
    ):
        args.token_file.write_text(json.dumps({"headers": rig.headers, "workspace": rig.workspace}))
        args.token_file.chmod(0o600)
        print(f"fuzz rig on {rig.base}", flush=True)
        stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
