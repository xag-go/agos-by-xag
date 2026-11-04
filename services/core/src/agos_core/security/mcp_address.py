"""Where a workspace's MCP servers may point, checked where Hermes connects from.

Hermes's MCP client runs on this machine (not in the workspace's sandbox), so a server
URL on loopback, the LAN, link-local (cloud metadata), Tailscale (CGNAT) or Docker's
host names would let a workspace reach this computer's own services. The library
refuses such URLs when the owner saves a server (engine/library.check_mcp); this module
is the same rule applied again when AGOS writes the servers into Hermes's config
(actions/services/library/apply) and when a root's gateway starts
(engine/hermes/mcp_guard), so an entry written into config.yaml by any other path, or a
name that now resolves to a private address, is switched off before Hermes uses it.

"Marked local" = a server the owner added as a local command (it runs in the
workspace's container and Hermes reaches it through AGOS's relay on 127.0.0.1, with the
relay's own bearer): only loopback is allowed for it.

Owns: The address rule (`blocked`), the per-URL and per-entry verdicts (`refusal`,
`entry_refusal`, also used before `hermes mcp test`), switching refused
entries off (`with_private_off`), and the bounded DNS lookup it uses.

Must not: Write Hermes's config, import engine/actions (this is a bottom layer), or
fail on a name that can't be resolved right now (an offline moment must not switch the
owner's servers off; the gateway-start re-check runs again on the next start).
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
from collections.abc import Callable, Collection, Mapping
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "BLOCKED_NETS",
    "blocked",
    "entry_refusal",
    "marked_local",
    "refusal",
    "refused",
    "relay_header",
    "resolve_host",
    "with_private_off",
]

BLOCKED_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)
_LOCAL_NAMES = ("localhost", "host.docker.internal", "gateway.docker.internal")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".arpa")
_RELAY_ENV = "AGOS_MCP__RELAY_"  # engine/library.env_name(actions/mcp_relays.RELAY + name)
_APP_PREFIX = "app-"  # engine/apps.SERVER_PREFIX: `app-google` is relayed as "google"
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agos-mcp-dns")

Resolve = Callable[[str], "list[str] | None"]


def blocked(address: str) -> bool:
    """The address is on this machine, a private/link-local/CGNAT network or reserved."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in BLOCKED_NETS if net.version == ip.version)


def _lookup(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def resolve_host(
    host: str, *, timeout: float = 2.0, lookup: Callable[[str], list[str]] = _lookup
) -> list[str] | None:
    """The host's addresses, or None when it can't be resolved within `timeout`."""
    future = _POOL.submit(lookup, host)
    try:
        return future.result(timeout=timeout) or None
    except (concurrent.futures.TimeoutError, OSError, UnicodeError):
        return None


def _ip_literal(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        return None


def refusal(url: str, *, local: bool, resolve: Resolve | None = None) -> str | None:
    """Why Hermes must not connect to this MCP URL, or None when it may."""
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host:
        return "is not an http(s) URL"
    literal = _ip_literal(host)
    if local:
        if literal is not None and ipaddress.ip_address(literal).is_loopback:
            return None
        return "is a local server but its address is not this computer's relay"
    if host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES):
        return "is on this computer or the local network"
    lookup = resolve or resolve_host  # read at call time (tests replace it)
    addresses = [literal] if literal is not None else (lookup(host) or [])
    if any(blocked(a) for a in addresses):
        return "is on this computer or the local network"
    return None


def relay_header(name: str) -> dict[str, str]:
    """The header AGOS gives a relayed server's entry (actions/mcp_relays.header)."""
    return {"Authorization": f"Bearer ${{{_RELAY_ENV}{re.sub(r'[^A-Z0-9]', '_', name.upper())}}}"}


def marked_local(name: str, entry: Mapping[str, Any]) -> bool:
    """The owner added it as a local command (AGOS's part says so), or it carries its
    own relay's header (an app server AGOS relays, e.g. Google)."""
    mine = entry.get("agos")
    if isinstance(mine, Mapping) and str(mine.get("command") or "").strip():
        return True
    headers = entry.get("headers")
    return headers in (relay_header(name), relay_header(name.removeprefix(_APP_PREFIX)))


def _enabled(entry: Mapping[str, Any]) -> bool:
    value = entry.get("enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "off", "0")
    return value is not False


def entry_refusal(
    name: str, entry: Mapping[str, Any], *, resolve: Resolve | None = None
) -> str | None:
    """Why Hermes must not connect to this one entry, switched on or not (`hermes mcp
    test` connects to an entry whatever its `enabled`), or None when it may."""
    return refused({name: {**entry, "enabled": True}}, resolve=resolve).get(name)


def refused(
    servers: Mapping[str, Mapping[str, Any]],
    *,
    local: Collection[str] | None = None,
    resolve: Resolve | None = None,
) -> dict[str, str]:
    """{name: why} for every switched-on entry Hermes must not connect to. `local`:
    the names allowed on loopback (default: the ones `marked_local`)."""
    if local is None:
        local = [name for name, entry in servers.items() if marked_local(name, entry)]
    out: dict[str, str] = {}
    for name, entry in servers.items():
        if not isinstance(entry, Mapping) or not _enabled(entry):
            continue
        if entry.get("command") and not entry.get("url"):
            out[name] = "runs a command on this computer"
            continue
        why = refusal(str(entry.get("url") or ""), local=name in local, resolve=resolve)
        if why is not None:
            out[name] = why
    return out


def with_private_off(
    servers: Mapping[str, Mapping[str, Any]],
    *,
    local: Collection[str] | None = None,
    resolve: Resolve | None = None,
) -> dict[str, dict[str, Any]]:
    """The servers, with every refused one switched off (kept, so the owner still
    sees it and its settings; Hermes skips a server whose `enabled` is false)."""
    bad = refused(servers, local=local, resolve=resolve)
    return {
        name: ({**entry, "enabled": False} if name in bad else dict(entry))
        for name, entry in servers.items()
    }
