"""A turn's end reaches AGOS even when AGOS's core restarts right then (every ship
restarts it while the gateways keep running): what didn't get through is sent again,
in order, so the AGOS turn closes with its answer instead of staying "running"."""

import threading
from typing import Any

import pytest

from agos_core.hermes_plugin.agos_guard import bridge


@pytest.fixture(autouse=True)
def agos_here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bridge, "bridge", lambda: {"core": "http://127.0.0.1:1", "workspace": "w", "key": "k"}
    )
    monkeypatch.setattr(bridge, "ENDS_RETRY_S", (0, 0, 0, 0, 0))


def _drain() -> None:
    for t in threading.enumerate():
        if t.name == "agos-turn-ends":
            t.join(timeout=5)


def test_turn_ends_wait_for_agos_and_arrive_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, int]] = []
    down = {"left": 3}  # AGOS restarting: its next 3 calls get no answer

    def post(path: str, body: dict[str, Any], *_: Any) -> dict[str, Any] | None:
        if down["left"] > 0:
            down["left"] -= 1
            return None
        sent.append((path, int(body["turnId"])))
        return {}

    monkeypatch.setattr(bridge, "post", post)
    bridge._tell_surely("turn-finish", {"turnId": 7, "text": "Salam!"})
    bridge._tell_surely("turn-end", {"turnId": 7, "reason": "text_response(x)"})
    _drain()
    # The answer first, then how it ended: the AGOS turn closes with its answer.
    assert sent == [("turn-finish", 7), ("turn-end", 7)]
    assert bridge._ends_backlog == [] and bridge._ends_sending is False


def test_one_try_when_agos_answers_and_none_without_agos(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def answered(path: str, body: dict[str, Any], *_: Any) -> dict[str, Any]:
        calls.append(path)
        return {}

    monkeypatch.setattr(bridge, "post", answered)
    bridge._tell_surely("turn-end", {"turnId": 1, "reason": ""})
    assert calls == ["turn-end"] and bridge._ends_backlog == []

    def unanswered(path: str, body: dict[str, Any], *_: Any) -> None:
        calls.append(path)

    monkeypatch.setattr(bridge, "post", unanswered)
    monkeypatch.setattr(bridge, "bridge", lambda: None)  # not an AGOS gateway: nothing to wait for
    bridge._tell_surely("turn-stop", {"turnId": 2, "reason": "Stop requested"})
    _drain()
    assert calls == ["turn-end", "turn-stop"] and bridge._ends_backlog == []
