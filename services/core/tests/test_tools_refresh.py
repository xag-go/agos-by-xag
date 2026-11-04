"""Hermes's list of tools is asked once at start, then again only when it is old or
the installed Hermes changed (F13): the automation loop no longer asks a second
time right after the start sync did (a Hermes runtime start + every workspace's
tools re-applied, ~13 s per restart on live)."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.actions.services.automation import sync_loop as automations
from agos_core.engine import hermes_tools


@pytest.fixture
def core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    src = tmp_path / "hermes-agent"
    (src / ".git").mkdir(parents=True)
    (src / ".git" / "HEAD").write_text("aaaa\n")
    (src / "pyproject.toml").write_text('version = "0.0.0"\n')
    asked: list[str] = []

    def catalog() -> list[dict[str, Any]]:
        asked.append("catalog")
        return [{"key": "web", "label": "Web", "about": "", "providers": []}]

    engine = SimpleNamespace(settings=SimpleNamespace(hermes_src=src), tools_catalog=catalog)
    monkeypatch.setattr(hermes_tools, "_current", {"list": hermes_tools.FALLBACK})
    monkeypatch.setattr(automations, "_tools_at", None)
    return SimpleNamespace(engine=engine, asked=asked, src=src)


def test_a_list_read_at_start_is_not_asked_again_by_the_loop(core: Any) -> None:
    assert hermes_tools.due(core)  # never read in this process
    assert hermes_tools.refresh(core)  # the start sync's read
    assert not hermes_tools.due(core)
    assert not automations._tools_due(core)  # the loop's first pass: nothing to ask


def test_an_old_list_or_a_new_hermes_is_asked_again(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hermes_tools.refresh(core)
    (core.src / ".git" / "HEAD").write_text("bbbbbbbb\n")  # `hermes update` moved it
    assert hermes_tools.due(core)
    assert automations._tools_due(core)
    assert not automations._tools_due(core)  # once per look, not every 20 s pass
    assert hermes_tools.refresh(core)
    assert not hermes_tools.due(core)
    later = time.monotonic() + hermes_tools.REFRESH_SECONDS + 1
    monkeypatch.setattr(time, "monotonic", lambda: later)
    assert hermes_tools.due(core)


def test_a_failed_start_read_is_asked_again_by_the_loop(core: Any) -> None:
    core.engine.tools_catalog = lambda: []  # Hermes didn't answer
    assert not hermes_tools.refresh(core)
    assert automations._tools_due(core)


def test_a_machine_booted_minutes_ago_is_asked_too(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clock is monotonic (counts from boot): a core started 2 min after a boot
    (a fresh server, a CI runner) still asks when the start read failed."""
    monkeypatch.setattr(time, "monotonic", lambda: 120.0)
    core.engine.tools_catalog = lambda: []
    assert not hermes_tools.refresh(core)
    assert automations._tools_due(core)
    assert not automations._tools_due(core)  # then once per TOOLS_LOOK_S
