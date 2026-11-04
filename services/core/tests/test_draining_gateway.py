"""A gateway draining for a restart (Hermes keeps it up to agent.restart_drain_timeout)
takes no more AGOS work: the outbox rows it would take are sent by the gateway after
it, not held until the claim runs out (H: gateway/status.py read_runtime_status)."""

import os
import sys
import types
from typing import Any

from agos_core.hermes_plugin.agos_guard import bridge as plugin


def _status(monkeypatch: Any, state: dict[str, Any]) -> None:
    fake = types.ModuleType("gateway.status")
    fake.read_runtime_status = lambda: state  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.status", fake)


def test_a_draining_gateway_takes_no_outbox(monkeypatch: Any) -> None:
    asked: list[str] = []
    monkeypatch.setattr(plugin, "bridge", lambda: object())
    monkeypatch.setitem(plugin._ctx, "native", object())
    monkeypatch.setattr(plugin, "post", lambda path, *_a, **_k: asked.append(path))
    _status(monkeypatch, {"pid": os.getpid(), "gateway_state": "draining"})
    assert plugin._serving() is False
    assert plugin._send_once() is False
    assert asked == []


def test_the_serving_gateway_and_another_pids_state(monkeypatch: Any) -> None:
    _status(monkeypatch, {"pid": os.getpid(), "gateway_state": "running"})
    assert plugin._serving() is True
    # The file names the next gateway (or an old one): this process still serves.
    _status(monkeypatch, {"pid": os.getpid() + 1, "gateway_state": "draining"})
    assert plugin._serving() is True
