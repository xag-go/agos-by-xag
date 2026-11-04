"""Held-back writes and Learned ask each profile's Hermes again only when what its
script reads changed: its write-approval queue (<home>/pending/), its config's
gates, its skill ledger. AGOS's own approve/reject forgets the profile's list at
once. The read-ahead asks both after a start."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine.hermes import EngineError, HermesEngine

# The engine's own method (conftest stands in for it with plain files).
_SKILL_CHANGES = HermesEngine.skill_changes


def _runtime(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Hermes's runtime as far as the held-writes and ledger scripts go."""
    asked: list[tuple[str, str]] = []

    def runtime(self: Any, home: Path, script: str, tag: str, **_kw: Any) -> str:
        asked.append((tag, str(home)))
        if tag == "AGOS-PENDING":
            n = len(list((home / "pending" / "memory").glob("*.json")))
            return json.dumps({"gates": {"memory": True, "skills": False}, "items": [{}] * n})
        if tag == "AGOS-LEDGER":
            return json.dumps([{"id": "ab12cd", "ts": "t", "actor": "agent"}])
        if tag == "AGOS-DECIDED":
            for held in (home / "pending" / "memory").glob("*.json"):
                held.unlink()
            return json.dumps({"found": True, "gone": True, "text": "ok"})
        raise EngineError("not in this test")

    monkeypatch.setattr(HermesEngine, "_in_runtime", runtime)
    monkeypatch.setattr(HermesEngine, "skill_changes", _SKILL_CHANGES)
    return asked


def _hold(home: Path, pending_id: str) -> None:
    folder = home / "pending" / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pending_id}.json").write_text(json.dumps({"id": pending_id}))


def test_held_writes_ask_hermes_again_only_when_its_queue_changed(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    asked = _runtime(monkeypatch)
    url = f"/workspaces/{a}/held-writes"
    assert client.get(url).status_code == 200
    first = len(asked)
    assert first >= 2  # the Co-Founder and the member
    assert client.get(url).status_code == 200
    assert len(asked) == first
    # Hermes held a write in the Co-Founder's home: only that profile is asked again.
    root = core.engine.profile_home(a)
    _hold(root, "0cd1ed62")
    assert len(client.get(url).json()["items"]) == 1
    assert asked[first:] == [("AGOS-PENDING", str(root))]
    # AGOS's own approve: the list after it is Hermes's, asked again at once.
    out = core.engine.decide_pending(root, "memory", "0cd1ed62", True)
    assert out["gone"]
    assert client.get(url).json()["items"] == []
    assert asked[-1] == ("AGOS-PENDING", str(root))


def test_learned_asks_hermes_again_only_when_a_ledger_changed(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    asked = _runtime(monkeypatch)
    url = f"/workspaces/{a}/learned"
    assert client.get(url).status_code == 200
    first = len(asked)
    assert first >= 2
    assert client.get(url).status_code == 200
    assert len(asked) == first
    ledger = core.engine.profile_home(a) / "skills" / ".curator_ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"id": "ab12cd"}\n')
    assert client.get(url).status_code == 200
    assert asked[first:] == [("AGOS-LEDGER", str(core.engine.profile_home(a)))]


def test_the_read_ahead_asks_held_writes_and_ledgers_before_the_first_page(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    asked = _runtime(monkeypatch)
    from agos_core.engine import read_ahead

    warmers = ("agos_core.actions.held_writes:read_ahead", "agos_core.actions.proactive:read_ahead")
    assert set(warmers) <= set(read_ahead.WARMERS)
    read_ahead.run(core, warmers)
    warmed = len(asked)
    assert warmed >= 4
    assert client.get(f"/workspaces/{a}/held-writes").status_code == 200
    assert client.get(f"/workspaces/{a}/learned").status_code == 200
    assert len(asked) == warmed
