"""The sandbox broker's test rig (tests/test_sandboxd*.py): a fake Docker daemon on a
unix socket, the real agos-sandboxd in-process in front of it, a workspace policy and
a Hermes-shaped create body. Moved out of test_sandboxd.py (the 800-line limit)."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import urllib.parse
from collections.abc import Awaitable, Callable
from pathlib import Path

from agos_core.engine import sandboxd
from agos_core.engine.sandboxd import Policy

LABEL = "agos-alpha-0123456789ab"
OWN_ID = "aa" * 32
FOREIGN_ID = "bb" * 32
BARE_ID = "cc" * 32  # a container with no hermes-profile label at all
NEW_ID = "dd" * 32
LEGACY_ID = "ee" * 32  # this workspace's Hermes label, created before the broker
SPOOF_ID = "ff" * 32  # this workspace's Hermes label, created later NOT through its socket
NAMES = {
    "own": OWN_ID,
    "foreign": FOREIGN_ID,
    "bare": BARE_ID,
    "c-new": NEW_ID,
    "legacy": LEGACY_ID,
    "spoof": SPOOF_ID,
}
PROFILE = "agos-alpha"  # the rig's policy file name: the broker's owner label value
OWNED = {"hermes-profile": LABEL, "agos-sandboxd-owner": PROFILE}
IMAGE_ID = "sha256:" + "12" * 32
IMAGES = {
    "agos-sandbox:desktop": IMAGE_ID,
    "agos-sandbox:1": "sha256:" + "34" * 32,
    IMAGE_ID: IMAGE_ID,
    "docker.io/library/agos-sandbox:desktop": IMAGE_ID,
    "ubuntu:latest": "sha256:" + "56" * 32,
}
BROKER_SINCE = 1767225600.0  # 2026-01-01: when the broker took this workspace over


def _policy(tmp_path: Path, **extra: object) -> Policy:
    for folder in ("files", "root", "shared"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {
        "labels": [LABEL],
        "images": ["agos-sandbox:1", "agos-sandbox:desktop"],
        "networks": ["agos-net-agos-alpha", "none"],
        "binds_rw": [str(tmp_path / "root"), str(tmp_path / "files")],
        "binds_ro": [str(tmp_path / "shared")],
        "legacy_before": BROKER_SINCE,
    }
    data.update(extra)
    target = tmp_path / "pol.json"
    target.write_text(json.dumps(data))
    return sandboxd.load_policy(target)


def _create_body(tmp_path: Path, **over: object) -> dict[str, object]:
    files = tmp_path / "files"
    files.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {
        "Image": "agos-sandbox:desktop",
        "Labels": {"hermes-agent": "1", "hermes-profile": LABEL, "hermes-task-id": "t"},
        "HostConfig": {
            "Binds": [f"{files}:/workspace"],
            "NetworkMode": "agos-net-agos-alpha",
            "CapDrop": ["ALL"],
            "CapAdd": ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"],
            "SecurityOpt": ["no-new-privileges"],
            "Privileged": False,
            "PidsLimit": 2048,
            "ShmSize": 1073741824,
            "Tmpfs": {"/tmp": "rw,nosuid,size=512m"},  # noqa: S108 - container spec
        },
    }
    body.update(over)
    return body


class FakeDocker:
    """Just enough of the Docker API: inspect by label map, create echo, exec hijack.
    It records every request head it got and how many connections it was opened."""

    def __init__(self, labels: dict[str, dict[str, str] | None]) -> None:
        self.labels = labels  # full id -> its labels (None = no labels at all)
        self.created: list[dict[str, object]] = []
        self.requests: list[str] = []
        self.heads: list[bytes] = []
        self.bodies: list[bytes] = []
        self.connections = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                try:
                    raw = await reader.readuntil(b"\r\n\r\n")
                except (asyncio.IncompleteReadError, ConnectionError):
                    return
                self.heads.append(raw)
                head = raw.decode().split("\r\n")
                method, target, _ = head[0].split(" ")
                headers = {
                    ln.partition(":")[0].lower(): ln.partition(":")[2].strip()
                    for ln in head[1:]
                    if ln
                }
                body = b""
                if headers.get("transfer-encoding") == "chunked":
                    while size := int((await reader.readuntil(b"\r\n"))[:-2], 16):
                        body += (await reader.readexactly(size + 2))[:-2]
                    await reader.readexactly(2)
                elif length := int(headers.get("content-length", 0) or 0):
                    body = await reader.readexactly(length)
                self.bodies.append(body)
                self.requests.append(f"{method} {target.split('?')[0]}")
                await self.respond(method, target, headers, body, reader, writer)
                if headers.get("connection", "").lower() == "close":
                    return
        finally:
            writer.close()

    async def respond(self, method, target, headers, body, reader, writer) -> None:  # type: ignore[no-untyped-def]
        path = urllib.parse.unquote(target.split("?")[0])
        if path == "/_ping":
            return self.json(writer, 200, "OK", raw=b"OK")
        if path.endswith("/version"):
            return self.json(writer, 200, {"Version": "29.0", "ApiVersion": "1.51"})
        if path.endswith("/containers/create"):
            self.created.append(json.loads(body))
            return self.json(writer, 201, {"Id": NEW_ID, "Warnings": []})
        if m := re.fullmatch(r"(?:/v[0-9.]+)?/images/(.+)/json", path):
            if m.group(1) not in IMAGES:
                return self.json(writer, 404, {"message": "No such image"})
            return self.json(writer, 200, {"Id": IMAGES[m.group(1)]})
        if found := self._inspect(path):
            cid, labels = found
            if cid is None:
                return self.json(writer, 404, {"message": "No such container"})
            created = (
                "2020-01-01T00:00:00.123456789Z" if cid == LEGACY_ID else "2026-06-01T10:00:00Z"
            )
            config: dict[str, object] = {"Labels": labels or {}}
            return self.json(writer, 200, {"Id": cid, "Created": created, "Config": config})
        if path.endswith("/exec/e-own/json"):
            return self.json(writer, 200, {"ID": "e-own", "ContainerID": OWN_ID})
        if path.endswith("/exec/e-foreign/json"):
            return self.json(writer, 200, {"ID": "e-foreign", "ContainerID": FOREIGN_ID})
        if path.endswith("/exec") and method == "POST":
            return self.json(writer, 201, {"Id": "e-own"})
        if path.endswith("/exec/e-own/start"):
            writer.write(b"HTTP/1.1 101 UPGRADED\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n")
            await writer.drain()
            piece = await reader.read(64)
            writer.write(b"ECHO:" + piece)
            await writer.drain()
            writer.write_eof()
            return None
        if path.endswith("/containers/json"):
            return self.json(writer, 200, [])
        if path.endswith(f"/containers/{OWN_ID}/logs"):
            writer.write(
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n"
            )
            return None
        if path.endswith(f"/containers/{OWN_ID}/archive") and method == "PUT":
            return self.json(writer, 200, None, raw=b"")
        if re.search(r"/containers/[0-9a-f]{64}/(start|stop|wait|kill)$", path) or (
            method == "DELETE" and re.search(r"/containers/[0-9a-f]{64}$", path)
        ):
            return self.json(writer, 204, None, raw=b"")
        return self.json(writer, 500, {"message": f"fake docker has no {method} {path}"})

    def _inspect(self, path: str) -> tuple[str | None, dict[str, str] | None] | None:
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[-3] == "containers" and parts[-1] == "json":
            ref = NAMES.get(parts[-2], parts[-2])
            if ref not in self.labels:
                return None, None
            return ref, self.labels[ref]
        return None

    def json(self, writer, status, payload, raw: bytes | None = None) -> None:  # type: ignore[no-untyped-def]
        body = raw if raw is not None else json.dumps(payload).encode()
        label = {200: "OK", 201: "Created", 204: "No Content", 404: "Not Found"}.get(status, "X")
        head = f"HTTP/1.1 {status} {label}\r\nContent-Type: application/json\r\n"
        if status != 204:
            head += f"Content-Length: {len(body)}\r\n"
        writer.write(head.encode() + b"\r\n" + (body if status != 204 else b""))


async def _read_response(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """One response as the proxy frames it (the WIP helper read until EOF and hung
    on the proxy's kept-alive connections): headers, then Content-Length or
    chunked body; streams without framing read to EOF as before."""
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    head = raw.decode("latin-1")
    status = int(head.split(" ", 2)[1])
    headers = {
        ln.partition(":")[0].strip().lower(): ln.partition(":")[2].strip()
        for ln in head.split("\r\n")[1:]
        if ":" in ln
    }
    if status in (204, 304) or 100 <= status < 200:
        return status, b""
    if "chunked" in headers.get("transfer-encoding", "").lower():
        payload = b""
        while True:
            size_line = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=5)
            size = int(size_line.strip().split(b";")[0], 16)
            piece = await asyncio.wait_for(reader.readexactly(size + 2), timeout=5)
            if size == 0:
                return status, payload
            payload += piece[:-2]
    length = headers.get("content-length")
    if length and length.isdigit():
        return status, await asyncio.wait_for(reader.readexactly(int(length)), timeout=5)
    return status, await asyncio.wait_for(reader.read(), timeout=5)


async def _request(
    sock: Path, method: str, target: str, body: bytes | None = None
) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_unix_connection(str(sock))
    try:
        head = f"{method} {target} HTTP/1.1\r\nHost: docker\r\n"
        if body is not None:
            head += f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        writer.write(head.encode() + b"\r\n" + (body or b""))
        await writer.drain()
        return await _read_response(reader)
    finally:
        writer.close()


class Rig:
    def __init__(self, base: Path, fake: FakeDocker, daemon: sandboxd.Sandboxd, sock: Path) -> None:
        self.base, self.fake, self.daemon, self.sock = base, fake, daemon, sock


async def _rig(scenario: Callable[[Rig], Awaitable[None]], tmp_path: Path) -> None:
    base = Path(tempfile.mkdtemp(prefix="agos-sbd-"))
    server = None
    daemon = None
    try:
        fake = FakeDocker(
            labels={
                OWN_ID: OWNED,
                FOREIGN_ID: {"hermes-profile": "beta-label", "agos-sandboxd-owner": "agos-beta"},
                BARE_ID: None,
                NEW_ID: OWNED,
                LEGACY_ID: {"hermes-profile": LABEL},
                SPOOF_ID: {"hermes-profile": LABEL},
            }
        )
        docker_sock = base / "real.sock"
        server = await asyncio.start_unix_server(fake.handle, path=str(docker_sock))
        daemon = sandboxd.Sandboxd(
            sockets_dir=base / "s",
            policies_dir=base / "p",
            docker_socket=docker_sock,
            events_file=base / "events.jsonl",
        )
        (base / "p").mkdir()
        policy = _policy(tmp_path)
        (base / "p" / f"{PROFILE}.policy.json").write_text((tmp_path / "pol.json").read_text())
        assert policy.labels == frozenset([LABEL])
        await daemon.rescan()
        await scenario(Rig(base, fake, daemon, base / "s" / PROFILE / "docker.sock"))
    finally:
        # Never wait_closed(): a kept-alive connection would hold it open forever.
        if daemon is not None:
            daemon.close()
        if server is not None:
            server.close()
        await asyncio.sleep(0)
        shutil.rmtree(base, ignore_errors=True)
