"""Hermes's real sandboxed-browser command reaches the workspace's broker from inside
the cage (engine/cage.py write_docker_config).

Hermes's tools/browser_tool_session `_sandbox_wrap` turns every agent-browser call
into `docker exec -i <container> ...` and runs it with an env of PATH and HOME only,
so the cage's DOCKER_HOST never reaches that docker CLI (live, 2026-11-03: "Cannot
connect to the Docker daemon at unix:///var/run/docker.sock" for every browser
call). This test asks the real Hermes code for that command and its env, then runs
exactly that inside the cage against a fake daemon behind the real broker."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sandboxd_rig import OWN_ID, OWNED
from test_cage import _restricted
from test_cage_docker_config import _behind_broker, _short_dir
from test_hermes_env_lock import _hermes_python

from agos_core.engine import cage

pytestmark = pytest.mark.hermes  # runs Hermes's own code, like conftest.py HERMES_FILES

# Hermes's own `_sandbox_wrap` with its sandbox lookups stubbed (a docker backend
# whose container is argv[1], a screen on :20): prints the command and its env.
_WRAP = """
import json, sys
from tools import browser_tool_session as bts
from tools.bot_desktop import placement, runtime as rt, sandbox_host
from tools.environments import streams
from tools.environments.docker import DockerEnvironment

env = object.__new__(DockerEnvironment)
env._container_id = sys.argv[1]
env._docker_exe = sys.argv[2]
env.get_temp_dir = lambda: "/tmp"
placement.resolve = lambda *a, **k: type("P", (), {"where": placement.TERMINAL})()
rt._sandbox_env = lambda create=False: env
rt.published_env = lambda *a, **k: {"DISPLAY": ":20"}
sandbox_host.browser_profile_dir = lambda e: "/home/agent/.hermes/bot-desktop/browser-profile"
sandbox_host._user_for = lambda e: None
streams.run_in = lambda *a, **k: None
browser_env = {"PATH": "/usr/bin:/bin", "DOCKER_HOST": "unix:///cage/docker.sock", "HOME": "/x"}
wrapped, host_env = bts._sandbox_wrap(
    [bts._SANDBOX_AGENT_BROWSER, "open", "https://example.com"], browser_env, "/tmp/s")
print(json.dumps({"wrapped": wrapped, "host_env": host_env}))
"""


@pytest.mark.skipif(
    _restricted or shutil.which("docker") is None, reason="needs bwrap and the docker CLI"
)
def test_hermes_browser_docker_exec_reaches_the_own_broker_inside_the_cage(
    tmp_path: Path,
) -> None:
    python = _hermes_python()
    if python is None:
        pytest.skip("no Hermes install on this machine")
    docker = shutil.which("docker") or "docker"
    home = tmp_path / "home"
    (home / ".docker").mkdir(parents=True)
    asked = subprocess.run(  # noqa: S603 - Hermes's own runtime, fixed script
        [python, "-c", _WRAP, OWN_ID, docker],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "HERMES_HOME": str(tmp_path / "hh"),
            "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
        },
        check=False,
    )
    assert asked.returncode == 0, asked.stderr[-2000:]
    got = json.loads(asked.stdout.strip().splitlines()[-1])
    wrapped, host_env = got["wrapped"], got["host_env"]
    # The cause, pinned: Hermes drops DOCKER_HOST for the browser's docker CLI.
    assert wrapped[:4] == [docker, "exec", "-i", OWN_ID]
    assert set(host_env) == {"PATH", "HOME"} and host_env["HOME"] == str(home)

    short = _short_dir()
    own = short / "sockets" / "agos-alpha"
    own.mkdir(parents=True)
    config = cage.write_docker_config(short / "cfg", own / "docker.sock", home / ".docker" / "x")
    prefix = cage.argv(
        socket_dir=own, runtime_dir=short, family=short / "sockets",
        docker_config=(config, home / ".docker"),
    )  # fmt: skip

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - bwrap + Hermes's docker exec argv
            [*prefix, *wrapped],
            capture_output=True,
            text=True,
            timeout=30,
            env=host_env,
            input="ping",
            check=False,
        )

    try:
        done = _behind_broker(short, tmp_path, run, labels={OWN_ID: OWNED})
    finally:
        shutil.rmtree(short, ignore_errors=True)
    assert isinstance(done, subprocess.CompletedProcess)
    assert "Cannot connect to the Docker daemon" not in done.stderr, done.stderr
    # The broker passed the exec into the fake daemon: its hijacked stream answers a
    # raw "ECHO:...", which the CLI (no tty: multiplexed frames) reads as stream
    # number ord("E") = 69. Any refusal or a dead socket would say otherwise.
    assert "ECHO:" in done.stdout or "unrecognized stream: 69" in done.stderr, (
        done.returncode,
        done.stdout,
        done.stderr,
    )
