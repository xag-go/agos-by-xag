"""Step 41: Settings → Connectors and each workspace's Apps page show whether
Hermes's Nous apps are open: a script in Hermes's runtime (its Nous login, and
Nous's portal when the login's token is old). It was kept five minutes and then
asked again while the page waited. Now the page gets the last answer at once and
Hermes is asked again behind it; a login or logout in Hermes (its auth.json) is
asked at once, `fresh` asks now, and the read-ahead asks first after a start."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agos_core.actions import apps
from agos_core.actions.services.connector import nous_apps as connector_nous_apps
from agos_core.engine import read_ahead
from agos_core.engine.read_cache import ReadCache

SIGN_IN = (False, "Sign in to Nous Portal first.")


class FakeCore:
    """What nous_status reads of the core (a plain class: it is weak-referenced)."""

    def __init__(self, home: Path) -> None:
        self.engine = SimpleNamespace(settings=SimpleNamespace(host_home=home))


def test_the_apps_pages_never_wait_on_hermes_for_nous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[float] = []
    answer: list[tuple[bool, str | None]] = [SIGN_IN]
    gate = threading.Event()
    gate.set()

    def ask(core: Any) -> tuple[bool, str | None]:
        asked.append(time.monotonic())
        assert gate.wait(10), "Hermes never answered"
        return answer[0]

    monkeypatch.setattr(connector_nous_apps, "_ask_nous", ask)
    core = cast(Any, FakeCore(tmp_path))
    assert "agos_core.actions.apps:read_ahead_nous" in read_ahead.WARMERS
    apps.read_ahead_nous(core)  # after the start: Hermes asked before any page
    assert len(asked) == 1
    assert apps.nous_status(core) == SIGN_IN
    assert apps.nous_status(core) == SIGN_IN
    assert len(asked) == 1  # kept: no Hermes start for the pages
    # Five minutes later Hermes is slow (the stand-in waits until let go): the page
    # gets the last answer at once, Hermes asked again behind it.
    answer[0] = (True, None)
    gate.clear()
    for entry in apps._nous_kept(core)._entries.values():
        entry.stamp = -1
    started = time.monotonic()
    assert apps.nous_status(core) == SIGN_IN
    assert time.monotonic() - started < 2
    gate.set()
    assert ReadCache.settle(10)
    assert apps.nous_status(core) == (True, None)
    assert len(asked) == 2
    # A login or logout in Hermes (its auth.json changed): asked at once.
    answer[0] = SIGN_IN
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / "auth.json").write_text("{}")
    assert apps.nous_status(core) == SIGN_IN
    assert len(asked) == 3
    # fresh (a login flow, the Co-Founder's check): Hermes asked now.
    answer[0] = (True, None)
    assert apps.nous_status(core, fresh=True) == (True, None)
    assert len(asked) == 4
    assert apps.nous_status(core) == (True, None)
    assert len(asked) == 4


def test_no_engine_no_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector_nous_apps, "_ask_nous", lambda core: pytest.fail("Hermes asked"))
    assert apps.nous_status(cast(Any, SimpleNamespace(engine=None))) == (
        False,
        "The engine is off.",
    )
