"""A token, key or nonce the caller sends is compared in constant time, and one with a
character outside ASCII is simply wrong: a refusal (401 / False), never a
`TypeError` from `hmac.compare_digest` that the API answers with a 500 (audit F4)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agos_core.actions import mcp_tools, owner_gate, security_events
from agos_core.actions.services.channel import gateway_platform
from agos_core.api import deps
from agos_core.domain.secrets import same_secret

ODD = "tok\u00e9n"  # é: a str compare_digest refuses to compare


def test_same_secret_is_a_plain_yes_or_no() -> None:
    assert same_secret("abc", "abc")
    assert not same_secret("abc", "abd")
    assert not same_secret(ODD, "token")
    assert same_secret(ODD, ODD)
    assert not same_secret("", "")  # nothing held or nothing given is never a match
    assert not same_secret(None, "abc") and not same_secret("abc", None)


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(security_events, "record", lambda *a, **k: None)
    app = FastAPI()
    app.state.core = SimpleNamespace(internal_token="right-token")

    @app.get("/x", dependencies=[Depends(deps.require_internal)])
    def x() -> str:
        return "ok"

    return app


def test_a_non_ascii_internal_token_is_refused_not_a_crash(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/x", headers={"x-agos-internal": "right-token"}).status_code == 200
        odd = client.get("/x", headers={"x-agos-internal": ODD.encode("latin-1")})
        assert odd.status_code == 401
        assert client.get("/x", headers={"x-agos-internal": "wrong"}).status_code == 401


def test_a_non_ascii_bridge_key_is_refused() -> None:
    core: Any = SimpleNamespace(internal_token="right-token")
    good = gateway_platform.bridge_key(core, "w1")
    assert gateway_platform.key_ok(core, "w1", good)
    assert not gateway_platform.key_ok(core, "w1", ODD)
    assert not gateway_platform.key_ok(core, "w1", "")


def test_a_non_ascii_mcp_token_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_tools, "token", lambda core, ws: {"token": "held"})
    assert mcp_tools.allowed(None, "w1", "held")  # type: ignore[arg-type]
    assert not mcp_tools.allowed(None, "w1", ODD)  # type: ignore[arg-type]


def test_a_non_ascii_nonce_is_refused() -> None:
    owner_gate._asked("w1", "a", "k", "nonce")
    assert not owner_gate._was_asked("w1", "a", "k", ODD, True)
