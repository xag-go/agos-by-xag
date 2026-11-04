"""Step 38 B: Settings → Backups never waits for the walk of AGOS's data folder
(every file stat'ed: 13-15 s cold on live, the Hermes roots' installs included).
The size is kept in memory and walked again behind the page at most every few
minutes; the read-ahead after start makes the first walk."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from test_library import env  # noqa: F401 - fixture

from agos_core.actions import backups
from agos_core.engine import read_ahead
from agos_core.engine.read_cache import ReadCache


def _walks(monkeypatch: Any) -> list[str]:
    walked: list[str] = []

    def size(path: Path) -> int:
        walked.append(str(path))
        return 5_000_000 * len(walked)

    monkeypatch.setattr(backups, "_dir_size", size)
    backups._SIZE.drop()
    return walked


def test_the_page_gets_the_last_size_at_once_and_it_is_walked_again_behind_it(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, _core, _runner, _home = env
    walked = _walks(monkeypatch)
    first = client.get("/backups").json()
    assert first["dataSizeMb"] == 5.0
    assert client.get("/backups").json()["dataSizeMb"] == 5.0
    assert len(walked) == 1
    monkeypatch.setattr(backups, "_SIZE_EVERY_S", 0.001)  # minutes later
    started = time.monotonic()
    assert client.get("/backups").json()["dataSizeMb"] == 5.0  # the last size
    assert time.monotonic() - started < 2
    assert ReadCache.settle(10)
    assert len(walked) == 2
    monkeypatch.setattr(backups, "_SIZE_EVERY_S", 600)
    assert client.get("/backups").json()["dataSizeMb"] == 10.0
    assert ReadCache.settle(10)


def test_the_read_ahead_makes_the_first_walk(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    walked = _walks(monkeypatch)
    assert "agos_core.actions.backups:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.backups:read_ahead",))
    assert len(walked) == 1
    assert client.get("/backups").status_code == 200
    assert len(walked) == 1
