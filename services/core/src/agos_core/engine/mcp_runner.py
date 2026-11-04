"""Local (command) MCP servers, each in its own container per workspace.

A server like `npx -y @modelcontextprotocol/server-filesystem /workspace` speaks
MCP over stdin/stdout. It must never run on this machine, so for every
workspace that turns one on AGOS starts:

- `agos-mcp-<profile>-<name>`: the workspace's sandbox image, on the workspace's
  INTERNAL network behind the egress proxy (public internet only), with only
  that workspace's files at /workspace, no secrets but the server's own key.
  `supergateway` turns the command's stdio into MCP over HTTP on port 8000.
- `agos-mcp-link-<profile>-<name>`: a tiny relay that publishes that port on
  127.0.0.1 of this machine (nowhere else), so the workspace's Hermes reaches
  it as a normal remote server at http://127.0.0.1:<port>/mcp, with the relay's
  own bearer token (`relay_token`): any other caller on this machine gets 401.

Fail closed: if the containers can't start, the server stays out of the
profile's config (the agent doesn't get its tools).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import shlex
import tempfile
from collections.abc import Callable
from pathlib import Path

from agos_core.engine import network as net

SUPERGATEWAY = "supergateway@4.1.0"
INNER_PORT = 8000
LABEL = "agos-mcp=1"
SPEC_VERSION = "2"  # bump when the way servers start changes (they get restarted)

# Start: run the server once with no input so its packages download ONE time
# (npx/uvx caches break when several copies install together), then serve it.
# Stateful = one server process per MCP session, not one per request.
_START = (
    'timeout 300 sh -c "$AGOS_MCP_COMMAND" </dev/null >/dev/null 2>&1; '
    f'exec npx -y {SUPERGATEWAY} --stdio "$AGOS_MCP_COMMAND" '
    f"--outputTransport streamableHttp --stateful --port {INNER_PORT}"
)

Docker = Callable[..., str]

# A one-file relay (stdlib only) for the link container. Each connection's first
# request must carry the relay's bearer (`Authorization: Bearer <token>`, the token from
# its env file, never argv): anything else on 127.0.0.1 (another workspace's Hermes, a
# DNS-rebinding MCP URL, a local process) gets 401 and nothing reaches the server.
# After the check the bytes are piped as they are (keep-alive requests ride the same
# checked connection). No token = every connection refused (fail closed). The whole
# header must come within AGOS_RELAY_HEAD_S (10 s), and at most 128 connections are
# served at once (a slow drip can't hold threads open: review L12).
_RELAY = """
import hmac, os, socket, sys, threading, time
target = (sys.argv[1], int(sys.argv[2]))
want = os.environ.get("AGOS_RELAY_TOKEN", "").encode()
head_s = float(os.environ.get("AGOS_RELAY_HEAD_S") or 10)
slots = threading.BoundedSemaphore(128)
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((sys.argv[4] if len(sys.argv) > 4 else "0.0.0.0", int(sys.argv[3] if len(sys.argv) > 3 else sys.argv[2])))
srv.listen(64)
def pipe(a, b):
    try:
        while (d := a.recv(65536)):
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
def allowed(head):
    for line in head.split(b"\\r\\n")[1:]:
        key, _, value = line.partition(b":")
        if key.strip().lower() == b"authorization":
            scheme, _, given = value.strip().partition(b" ")
            return bool(want) and scheme.lower() == b"bearer" and hmac.compare_digest(given.strip(), want)
    return False
def serve(c):
    end = time.monotonic() + head_s
    head = b""
    try:
        while b"\\r\\n\\r\\n" not in head and len(head) < 65536:
            left = end - time.monotonic()
            if left <= 0:
                raise OSError("header too slow")
            c.settimeout(left)
            d = c.recv(65536)
            if not d:
                break
            head += d
    except OSError:
        c.close(); return
    if not allowed(head.split(b"\\r\\n\\r\\n", 1)[0]):
        try: c.sendall(b"HTTP/1.1 401 Unauthorized\\r\\nContent-Length: 0\\r\\nConnection: close\\r\\n\\r\\n")
        except OSError: pass
        c.close(); return
    try:
        u = socket.create_connection(target, timeout=10); u.settimeout(None)
        u.sendall(head)
    except OSError:
        c.close(); return
    c.settimeout(None)
    threading.Thread(target=pipe, args=(c, u), daemon=True).start()
    pipe(u, c)
def run(c):
    try:
        serve(c)
    finally:
        slots.release()
while True:
    c, _ = srv.accept()
    if not slots.acquire(blocking=False):
        c.close(); continue
    threading.Thread(target=run, args=(c,), daemon=True).start()
"""
RELAY_ENV = "AGOS_RELAY_TOKEN"


def relay_token(secret: str, profile: str, name: str) -> str:
    """The relay's bearer: per relay, stable across restarts (Hermes's config names it
    by env var), and no relay's token tells another's (HMAC of AGOS's own secret)."""
    if not secret:
        raise ValueError("No secret to make the MCP relay's token from.")
    digest = hmac.new(secret.encode(), f"mcp-relay:{profile}:{name}".encode(), hashlib.sha256)
    return digest.hexdigest()


def _auth_label(token: str) -> str:
    """The link's label: its token and its relay script (a changed relay is made again)."""
    return hashlib.sha256((token + _RELAY).encode()).hexdigest()[:16]


def server_name(profile: str, name: str) -> str:
    return f"agos-mcp-{profile}-{name}"


def link_name(profile: str, name: str) -> str:
    return f"agos-mcp-link-{profile}-{name}"


def check_command(command: str) -> list[str]:
    """The command as argv (no shell). Refuses empty or unparsable commands."""
    try:
        argv = shlex.split(command)
    except ValueError as error:
        raise ValueError("The command has an unclosed quote.") from error
    if not argv:
        raise ValueError("Give the command that starts the server.")
    return argv


def _running(docker: Docker, name: str) -> bool:
    out = docker("ps", "-q", "--filter", f"name=^{name}$", "--filter", "status=running")
    return bool(out.strip())


def _remove(docker: Docker, name: str) -> None:
    with contextlib.suppress(Exception):
        docker("rm", "-f", name)


def _spec_label(argv: list[str], env_key: str, has_secret: bool, zone: str = "") -> str:
    spec: list[object] = [SPEC_VERSION, argv, env_key, has_secret]
    if zone:  # a new timezone makes a new container
        spec.append(zone)
    return json.dumps(spec)


def ensure(
    docker: Docker,
    *,
    profile: str,
    name: str,
    command: str,
    files_dir: Path,
    image: str,
    env_key: str = "",
    secret: str | None = None,
    zone: str = "",
    token: str = "",
) -> str:
    """Both containers run (recreated when the command changed). Returns the
    URL for the profile's `mcp_servers.<name>.url`. `zone`: the owner's timezone,
    the server's `TZ` (like the sandbox's, engine/rules.py sandbox_env). `token`: the
    relay's bearer (`relay_token`); Hermes sends it, nothing else gets through."""
    if not token:
        raise ValueError("A local MCP relay needs its token.")
    argv = check_command(command)
    server, link = server_name(profile, name), link_name(profile, name)
    spec = _spec_label(argv, env_key, bool(secret), zone)
    if _running(docker, server):
        current = docker(
            "inspect", "-f", '{{index .Config.Labels "agos-mcp-spec"}}', server
        ).strip()
        if current != spec:
            _remove(docker, link)
            _remove(docker, server)
    if not _running(docker, server):
        _remove(docker, server)
        proxy = net.proxy_url()
        env = {
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "NO_PROXY": net.NO_PROXY,
            "no_proxy": net.NO_PROXY,
            "npm_config_proxy": proxy,
            "npm_config_https_proxy": proxy,
            "npm_config_update_notifier": "false",
        }
        if zone:
            env["TZ"] = zone
        if secret and env_key:
            env[env_key] = secret
        env["AGOS_MCP_COMMAND"] = shlex.join(argv)
        # Values go through a 0600 file, never the command line.
        fd, env_path = tempfile.mkstemp(prefix="agos-mcp-", suffix=".env")
        try:
            with os.fdopen(fd, "w") as handle:
                for key, value in env.items():
                    handle.write(f"{key}={value}\n")
            docker(
                "run",
                "-d",
                "--name",
                server,
                "--restart",
                "unless-stopped",
                "--label",
                LABEL,
                "--label",
                f"agos-profile={profile}",
                "--label",
                f"agos-mcp-spec={spec}",
                "--network",
                net.network_name(profile),
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "1g",
                "--pids-limit",
                "512",
                "--env-file",
                env_path,
                "-v",
                f"{files_dir}:/workspace",
                "-w",
                "/workspace",
                "--entrypoint",
                "sh",
                image,
                "-c",
                _START,
                timeout=180,
            )
        finally:
            with contextlib.suppress(OSError):
                Path(env_path).unlink()
    auth = _auth_label(token)
    if _running(docker, link):
        # A relay made before its bearer (or with another one) is made again.
        held = docker("inspect", "-f", '{{index .Config.Labels "agos-mcp-auth"}}', link).strip()
        if held != auth:
            _remove(docker, link)
    if not _running(docker, link):
        _remove(docker, link)
        _start_link(docker, profile, link, server, image, token, auth)
        docker("network", "connect", net.network_name(profile), link)
    port = docker("port", link, f"{INNER_PORT}/tcp").strip().splitlines()[0].rsplit(":", 1)[-1]
    return f"http://127.0.0.1:{int(port)}/mcp"


def _start_link(
    docker: Docker, profile: str, link: str, server: str, image: str, token: str, auth: str
) -> None:
    """The relay container; its token goes through a 0600 env file, never argv."""
    fd, env_path = tempfile.mkstemp(prefix="agos-mcp-link-", suffix=".env")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(f"{RELAY_ENV}={token}\n")
        docker(
            "run",
            "-d",
            "--name",
            link,
            "--restart",
            "unless-stopped",
            "--label",
            LABEL,
            "--label",
            f"agos-profile={profile}",
            "--label",
            f"agos-mcp-auth={auth}",
            "--network",
            "bridge",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "64m",
            "--env-file",
            env_path,
            "-p",
            f"127.0.0.1::{INNER_PORT}",
            image,
            "python3",
            "-c",
            _RELAY,
            server,
            str(INNER_PORT),
            timeout=120,
        )
    finally:
        with contextlib.suppress(OSError):
            Path(env_path).unlink()


def remove(docker: Docker, profile: str, name: str) -> None:
    for container in (link_name(profile, name), server_name(profile, name)):
        _remove(docker, container)


def running_names(docker: Docker, profile: str) -> set[str]:
    """Local MCP servers that have containers for this profile."""
    out = docker(
        "ps",
        "-a",
        "--filter",
        f"label={LABEL}",
        "--filter",
        f"label=agos-profile={profile}",
        "--format",
        "{{.Names}}",
    )
    prefix = f"agos-mcp-{profile}-"
    return {n[len(prefix) :] for n in out.split() if n.startswith(prefix)}


def remove_all(docker: Docker, profile: str) -> None:
    for name in running_names(docker, profile):
        remove(docker, profile, name)
