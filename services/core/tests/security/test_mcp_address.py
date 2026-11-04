"""MCP servers are checked where Hermes connects from (this machine), not only when saved.

Hermes's MCP client runs on the host, so an entry in a workspace's config.yaml whose URL is
on this computer or the local network reaches services the workspace must never touch.
"""

from collections.abc import Callable
from typing import Any

import pytest

from agos_core.security import mcp_address as ma


def _resolver(table: dict[str, list[str]]) -> Callable[[str], list[str] | None]:
    def resolve(host: str) -> list[str] | None:
        return table.get(host)

    return resolve


NO_DNS = _resolver({})


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9000/mcp",
        "http://[::1]:9000/mcp",
        "http://10.1.2.3/mcp",
        "http://172.17.0.1/mcp",
        "http://192.168.1.10/mcp",
        "http://169.254.169.254/latest",
        "http://100.100.1.1/mcp",  # Tailscale (CGNAT)
        "http://0.0.0.0:8000/mcp",
        "http://[fe80::1]/mcp",
        "http://[fd00::5]/mcp",
        "http://[::ffff:127.0.0.1]/mcp",
        "http://localhost:3000/mcp",
        "http://printer.local/mcp",
        "http://metadata.google.internal/mcp",
        "http://host.docker.internal/mcp",
    ],
)
def test_a_remote_server_on_this_machine_or_the_lan_is_refused(url: str) -> None:
    assert ma.refusal(url, local=False, resolve=NO_DNS) is not None


def test_a_name_that_resolves_to_a_private_address_is_refused() -> None:
    resolve = _resolver({"evil.example.com": ["93.184.216.34", "127.0.0.1"]})
    assert ma.refusal("https://evil.example.com/mcp", local=False, resolve=resolve) is not None


def test_a_public_server_is_kept() -> None:
    resolve = _resolver({"mcp.example.com": ["93.184.216.34"]})
    assert ma.refusal("https://mcp.example.com/mcp", local=False, resolve=resolve) is None


def test_a_name_that_cannot_be_resolved_now_is_kept() -> None:
    # Offline for a moment: the owner's servers are not switched off for it.
    assert ma.refusal("https://mcp.example.com/mcp", local=False, resolve=NO_DNS) is None


@pytest.mark.parametrize("url", ["ftp://mcp.example.com/x", "file:///etc/passwd", "", "https://"])
def test_anything_but_an_http_url_is_refused(url: str) -> None:
    assert ma.refusal(url, local=False, resolve=NO_DNS) is not None


def test_a_server_the_owner_marked_local_may_use_its_relay_on_loopback() -> None:
    assert ma.refusal("http://127.0.0.1:41234/mcp", local=True, resolve=NO_DNS) is None


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.10:41234/mcp", "http://169.254.169.254/", "https://mcp.example.com/mcp"],
)
def test_a_local_server_may_only_point_at_loopback(url: str) -> None:
    resolve = _resolver({"mcp.example.com": ["93.184.216.34"]})
    assert ma.refusal(url, local=True, resolve=resolve) is not None


def test_entries_are_switched_off_not_dropped() -> None:
    servers: dict[str, dict[str, Any]] = {
        "good": {"url": "https://mcp.example.com/mcp"},
        "bad": {"url": "http://127.0.0.1:8080/mcp", "headers": {"X": "y"}},
        "relay": {"url": "http://127.0.0.1:41234/mcp"},
    }
    resolve = _resolver({"mcp.example.com": ["93.184.216.34"]})
    out = ma.with_private_off(servers, local={"relay"}, resolve=resolve)
    assert ma.with_private_off(servers, resolve=resolve)["relay"]["enabled"] is False  # unmarked
    assert out["good"] == {"url": "https://mcp.example.com/mcp"}
    assert out["relay"] == {"url": "http://127.0.0.1:41234/mcp"}
    assert out["bad"]["enabled"] is False
    assert out["bad"]["url"] == "http://127.0.0.1:8080/mcp"
    assert "enabled" not in servers["bad"]  # the caller's dict is not changed


def test_a_command_entry_runs_on_this_machine_and_is_refused() -> None:
    # Hermes runs a top-level `command` on the host; AGOS's own local servers run in
    # the workspace's container and reach Hermes through a loopback relay URL.
    servers = {"stdio": {"command": "npx", "args": ["some-mcp"]}}
    assert ma.refused(servers, local=set(), resolve=NO_DNS) == {
        "stdio": "runs a command on this computer"
    }


def test_switched_off_entries_are_not_checked() -> None:
    servers = {"bad": {"url": "http://127.0.0.1:8080/mcp", "enabled": False}}
    assert ma.refused(servers, local=set(), resolve=NO_DNS) == {}


def test_marked_local_reads_the_owner_mark_or_the_relay_header() -> None:
    assert ma.marked_local("x", {"url": "http://127.0.0.1:1/mcp", "agos": {"command": "npx a"}})
    relay = {"url": "http://127.0.0.1:1/mcp", "headers": ma.relay_header("google")}
    assert ma.marked_local("app-google", relay)  # engine/apps: `app-google` relays "google"
    # Another server's relay header does not mark this one.
    assert not ma.marked_local("other", relay)
    assert not ma.marked_local("x", {"url": "http://127.0.0.1:1/mcp"})


def test_the_resolver_gives_up_after_its_timeout() -> None:
    import threading

    gate = threading.Event()

    def slow(host: str) -> list[str]:
        gate.wait(5)
        return ["127.0.0.1"]

    try:
        assert ma.resolve_host("slow.example.com", timeout=0.05, lookup=slow) is None
    finally:
        gate.set()


def test_one_entry_is_checked_even_when_switched_off() -> None:
    # `hermes mcp test` connects to an entry whatever its `enabled`.
    off = {"url": "http://10.0.0.7/mcp", "enabled": False}
    assert ma.entry_refusal("lan", off, resolve=NO_DNS) is not None
    relay = {"url": "http://127.0.0.1:41000/mcp", "headers": ma.relay_header("files")}
    assert ma.entry_refusal("files", relay, resolve=NO_DNS) is None
