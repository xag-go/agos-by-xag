"""Local MCP relays on 127.0.0.1 need their own bearer (security audit F10, 4.5).

A local MCP server runs in the workspace's container; a relay publishes it on
127.0.0.1 for that workspace's Hermes. Before, anything on this machine (another
workspace's Hermes, a DNS-rebinding MCP URL) could connect. Now each connection's
first request must carry `Authorization: Bearer <the relay's token>`.
"""

import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from agos_core.engine import mcp_runner


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


_SEEN: list[str] = []


class _Upstream(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        _SEEN.append(self.rfile.read(length).decode())
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def relay() -> Iterator[tuple[int, str]]:
    """The real relay script, in front of a small HTTP server."""
    upstream = HTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    port, token = _free_port(), "t0ken-" + "a" * 40
    env = {**os.environ, mcp_runner.RELAY_ENV: token}
    up = str(upstream.server_address[1])
    proc = subprocess.Popen(  # noqa: S603 - our own relay script
        [sys.executable, "-c", mcp_runner._RELAY, "127.0.0.1", up, str(port), "127.0.0.1"],
        env=env,
    )
    for _ in range(100):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)
    try:
        yield port, token
    finally:
        proc.kill()
        proc.wait()
        upstream.shutdown()
        upstream.server_close()


def _call(port: int, auth: str | None) -> bytes:
    head = f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 4\r\n"
    if auth is not None:
        head += f"Authorization: {auth}\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall((head + "Connection: close\r\n\r\nping").encode())
        got = b""
        while chunk := s.recv(65536):
            got += chunk
    return got


def test_the_relay_refuses_a_call_without_its_token(relay: tuple[int, str]) -> None:
    port, token = relay
    _SEEN.clear()
    assert _call(port, None).startswith(b"HTTP/1.1 401")
    assert _call(port, "Bearer wrong").startswith(b"HTTP/1.1 401")
    assert _call(port, token).startswith(b"HTTP/1.1 401")  # no scheme
    assert _SEEN == []  # nothing reached the server
    answer = _call(port, f"Bearer {token}")
    assert answer.startswith(b"HTTP/1.0 200") or answer.startswith(b"HTTP/1.1 200")
    assert _SEEN == ["ping"]


def test_a_relay_with_no_token_refuses_everything() -> None:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != mcp_runner.RELAY_ENV}
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", mcp_runner._RELAY, "127.0.0.1", "9", str(port), "127.0.0.1"],
        env=env,
    )
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        assert _call(port, "Bearer ").startswith(b"HTTP/1.1 401")
    finally:
        proc.kill()
        proc.wait()


def test_each_relay_has_its_own_stable_token() -> None:
    a = mcp_runner.relay_token("secret", "agos-w1", "notes")
    assert a == mcp_runner.relay_token("secret", "agos-w1", "notes")
    assert a != mcp_runner.relay_token("secret", "agos-w2", "notes")
    assert a != mcp_runner.relay_token("secret", "agos-w1", "other")
    with pytest.raises(ValueError):
        mcp_runner.relay_token("", "agos-w1", "notes")


def _docker(calls: list[tuple[str, ...]], envs: list[str], running: set[str], label: str = ""):  # type: ignore[no-untyped-def]
    def docker(*args: str, **_: Any) -> str:
        calls.append(args)
        if args[0] == "run" and "--env-file" in args:
            envs.append(Path(args[args.index("--env-file") + 1]).read_text())
        if args[0] == "ps":
            name = next(a.split("^", 1)[1].rstrip("$") for a in args if a.startswith("name=^"))
            return "id\n" if name in running else ""
        if args[0] == "inspect":
            return label
        if args[0] == "rm":
            running.discard(args[-1])
        if args[0] == "port":
            return "127.0.0.1:49000\n"
        return ""

    return docker


def test_the_relay_gets_its_token_by_file_and_old_relays_are_made_again(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    envs: list[str] = []
    token = mcp_runner.relay_token("secret", "agos-w1", "notes")
    kw: dict[str, Any] = {
        "profile": "agos-w1",
        "name": "notes",
        "command": "npx -y notes-mcp",
        "files_dir": tmp_path,
        "image": "agos-sandbox:1",
    }
    with pytest.raises(ValueError):
        mcp_runner.ensure(_docker(calls, envs, set()), **kw)  # no token: never unguarded
    url = mcp_runner.ensure(_docker(calls, envs, set()), **kw, token=token)
    assert url == "http://127.0.0.1:49000/mcp"
    link = next(a for a in calls if a[0] == "run" and "agos-mcp-link-agos-w1-notes" in a)
    assert all(token not in part for part in link)  # never in argv
    assert f"agos-mcp-auth={mcp_runner._auth_label(token)}" in link
    assert any(f"{mcp_runner.RELAY_ENV}={token}" in e for e in envs)
    # A relay made before the token (no label) is removed and made again.
    calls.clear()
    server, old_link = "agos-mcp-agos-w1-notes", "agos-mcp-link-agos-w1-notes"
    spec = mcp_runner._spec_label(["npx", "-y", "notes-mcp"], "", False)
    docker = _docker(calls, envs, {server, old_link}, label="")

    def with_spec(*args: str, **k: Any) -> str:
        if args[0] == "inspect" and args[-1] == server:
            calls.append(args)
            return spec
        return str(docker(*args, **k))

    mcp_runner.ensure(with_spec, **kw, token=token)
    assert ("rm", "-f", old_link) in calls
    assert any(a[0] == "run" and old_link in a for a in calls)


def test_a_slow_header_is_cut_at_the_relays_deadline() -> None:
    """Review L12 (slowloris): a byte now and then no longer keeps a connection (and
    its thread) open: the whole header must come within the relay's deadline."""
    port = _free_port()
    env = {**os.environ, mcp_runner.RELAY_ENV: "t" * 40, "AGOS_RELAY_HEAD_S": "1"}
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", mcp_runner._RELAY, "127.0.0.1", "9", str(port), "127.0.0.1"],
        env=env,
    )
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            started = time.monotonic()
            cut = False
            for byte in b"POST /mcp HTTP/1.1\r\nHost: x\r\nX-Slow: " + b"a" * 40:
                try:
                    s.sendall(bytes([byte]))
                    time.sleep(0.15)
                except OSError:
                    cut = True
                    break
                s.settimeout(0.01)
                try:
                    if s.recv(1) == b"":
                        cut = True
                        break
                except TimeoutError:
                    pass
                except OSError:
                    cut = True
                    break
            assert cut, "the relay kept a dripping header open"
            assert time.monotonic() - started < 4
    finally:
        proc.kill()
        proc.wait()
