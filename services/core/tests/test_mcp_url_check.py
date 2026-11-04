"""A remote MCP server's URL is refused when its name can't be resolved (security audit
4.5 / F10): one that resolves only later could point at 127.0.0.1, where each
workspace's local MCP servers listen."""

import socket
from typing import Any

import pytest

from agos_core.engine import library


def test_an_unresolvable_server_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(*_: Any, **__: Any) -> Any:
        raise socket.gaierror("no such name")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)
    with pytest.raises(library.LibraryError, match="can't find the server"):
        library.check_mcp({"url": "https://mcp.nowhere-agos-test.net/mcp"})
    # Only the URL's shape is read when nothing is resolved on purpose.
    clean = library.check_mcp({"url": "https://mcp.nowhere-agos-test.net/mcp"}, resolve=False)
    assert clean["url"] == "https://mcp.nowhere-agos-test.net/mcp"


def test_private_and_public_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = {"inside.agos-test.net": "10.1.2.3", "outside.agos-test.net": "93.184.215.14"}

    def dns(host: str, *_: Any, **__: Any) -> Any:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with pytest.raises(library.LibraryError, match="local network"):
        library.check_mcp({"url": "https://inside.agos-test.net/mcp"})
    assert library.check_mcp({"url": "https://outside.agos-test.net/mcp"})["transport"] == "http"
