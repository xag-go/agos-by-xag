"""AGOS egress proxy: the only way out of a workspace's sandbox.

Sandboxes sit on an internal Docker network with no route to anything. This
proxy (on that network and on the normal bridge) forwards HTTP and HTTPS
(CONNECT) to the public internet only. Destinations that resolve to loopback,
private, link-local, CGNAT (Tailscale), multicast or reserved addresses, or to
Docker's host names, are refused. The address is resolved once and the
connection goes to exactly that address, so DNS rebinding can't slip through.

Standard library only; runs as `python egress_proxy.py` in any Python image.
"""

import asyncio
import contextlib
import ipaddress
import os
import socket
import sys

LISTEN_PORT = int(os.environ.get("AGOS_EGRESS_PORT", "8888"))
ALLOWED_PORTS = {int(p) for p in os.environ.get("AGOS_EGRESS_PORTS", "80,443").split(",") if p}
BLOCKED_HOSTS = {
    "host.docker.internal",
    "gateway.docker.internal",
    "localhost",
    "kubernetes.docker.internal",
    "metadata.google.internal",
}
MAX_HEADER = 64 * 1024


def public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in ipaddress.ip_network("100.64.0.0/10")
        or ip in ipaddress.ip_network("192.0.0.0/24")
        or ip in ipaddress.ip_network("198.18.0.0/15")
    )


async def resolve(host: str, port: int) -> str | None:
    """One public address for host, or None (refused)."""
    name = host.strip("[]").lower().rstrip(".")
    if name in BLOCKED_HOSTS or name.endswith((".local", ".internal", ".lan", ".home")):
        return None
    if port not in ALLOWED_PORTS:
        return None
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(name, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addresses = [str(info[4][0]) for info in infos]
    if not addresses or not all(public(a) for a in addresses):
        return None  # any private answer: refuse the whole name
    return addresses[0]


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(OSError):
            writer.close()


async def refuse(writer: asyncio.StreamWriter, why: str) -> None:
    body = f"Blocked by AGOS: {why}\n".encode()
    writer.write(
        b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\nConnection: close\r\n\r\n"
        + body
    )
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        return
    if len(head) > MAX_HEADER:
        await refuse(writer, "request too large")
        return
    first, _, rest = head.partition(b"\r\n")
    try:
        method, target, version = first.decode("latin-1").split(" ", 2)
    except ValueError:
        await refuse(writer, "bad request")
        return
    if method.upper() == "CONNECT":
        host, _, port_text = target.rpartition(":")
        port = int(port_text) if port_text.isdigit() else 443
        address = await resolve(host, port)
        if address is None:
            log("deny", method, target)
            await refuse(writer, f"{host} is not a public internet address")
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout=15
            )
        except (TimeoutError, OSError):
            await refuse(writer, "could not connect")
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        log("allow", method, target)
        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
        return
    # Plain HTTP: absolute-form URL.
    if not target.lower().startswith("http://"):
        await refuse(writer, "only http:// and https:// are allowed")
        return
    hostport = target[7:].split("/", 1)[0]
    path = "/" + target[7:].split("/", 1)[1] if "/" in target[7:] else "/"
    host, _, port_text = hostport.rpartition(":") if ":" in hostport else (hostport, "", "80")
    port = int(port_text) if port_text.isdigit() else 80
    address = await resolve(host, port)
    if address is None:
        log("deny", method, target)
        await refuse(writer, f"{host} is not a public internet address")
        return
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 15)
    except (TimeoutError, OSError):
        await refuse(writer, "could not connect")
        return
    up_writer.write(f"{method} {path} {version}\r\n".encode("latin-1") + rest)
    await up_writer.drain()
    log("allow", method, target)
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


def log(verdict: str, method: str, target: str) -> None:
    print(f"{verdict} {method} {target[:200]}", flush=True)


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", LISTEN_PORT, limit=MAX_HEADER)  # noqa: S104
    print(f"agos egress proxy on :{LISTEN_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
