"""Step 38 B: the Settings pages read what Hermes said from memory, kept while what
it comes from holds (engine/read_cache.py), and the read-ahead after start
(engine/read_ahead.py WARMERS) fills exactly what each page reads, one Hermes run
at a time, so the first page after a restart doesn't wait for Hermes either."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_hermes_all_settings import _stub_schema
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import read_ahead


def test_every_warmer_is_a_function_taking_the_core() -> None:
    assert len(set(read_ahead.WARMERS)) == len(read_ahead.WARMERS)
    for spec in read_ahead.WARMERS:
        module, _, name = spec.partition(":")
        found = getattr(importlib.import_module(module), name)
        assert callable(found), spec
        assert list(inspect.signature(found).parameters) == ["core"], spec


def _job(script: str) -> dict[str, Any]:
    """The job a runtime script was given (`job = json.loads('<json>')`)."""
    import ast

    literal = script.split("job = json.loads(", 1)[1].split(")\n", 1)[0]
    found: dict[str, Any] = json.loads(ast.literal_eval(literal))
    return found


def _envuse_runtime(core: Any) -> list[tuple[Path, str]]:
    """Hermes's runtime for the env probe (what its gateway start reports); every
    other runtime script is not part of these tests."""
    runs: list[tuple[Path, str]] = []

    def in_runtime(home: Path, script: str, tag: str, **kw: Any) -> str:
        runs.append((home, tag))
        assert tag == "AGOS-ENVUSE", tag
        if not _job(script).get("diff"):  # the gateway's side
            return json.dumps({"used": {}, "managed": [], "env": {}})
        return json.dumps({})

    core.engine._in_runtime = in_runtime
    return runs


def test_the_hermes_settings_page_is_read_ahead_at_most_four_runs_at_once(env: Any) -> None:  # noqa: F811
    """After the read-ahead, the page asks Hermes nothing: what each profile's
    gateway uses per .env name was asked (two runs per profile) before any page
    came, at most four Hermes processes at once (the page's own limit) and at the
    read-ahead's low priority (nice 10: the owner's pages come first)."""
    import os
    import threading
    import time

    from agos_core.actions import hermes_all_settings as hall

    client, core, _runner, _home = env
    _stub_schema(core)
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    ws(client, "Beta")
    runs = _envuse_runtime(core)
    answer = core.engine._in_runtime
    lock = threading.Lock()
    running, nice = [0, 0], set()

    def in_runtime(home: Path, script: str, tag: str, **kw: Any) -> str:
        with lock:
            running[0] += 1
            running[1] = max(running)
            nice.add(os.getpriority(os.PRIO_PROCESS, threading.get_native_id()))
        time.sleep(0.1)
        with lock:
            running[0] -= 1
        return answer(home, script, tag, **kw)  # type: ignore[no-any-return]

    core.engine._in_runtime = in_runtime
    assert "agos_core.actions.hermes_all_settings:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.hermes_all_settings:read_ahead",))
    homes = {core.engine.profile_home(t.key) for t in hall.targets(core)}
    assert len(homes) == 3 and {h for h, _tag in runs} == homes
    assert len(runs) == 2 * len(homes)
    assert 2 <= running[1] <= 4, running  # side by side, never more than four
    assert min(nice) >= 10, nice  # every Hermes start of the read-ahead: low priority
    runs.clear()
    r = client.get("/preferences/hermes-settings")
    assert r.status_code == 200, r.text
    assert runs == []  # every answer was kept


def test_the_hermes_settings_pages_are_read_ahead_right_after_the_first_pages() -> None:
    """Step 41: the Hermes settings warmer was 17th of 18, so the first view after a
    start waited ~5 s for Hermes. It now comes right after the warmers of the pages
    the owner meets first (Board, Dashboard, a chat and its "/" menu), behind the
    workspace card's settings list (/workspaces/{ws}/hermes-settings: Hermes's
    defaults) and the helper models' read of every profile (the same Hermes runs
    the page needs), before the per-workspace lists and the long checks."""
    order = list(read_ahead.WARMERS)
    first_pages = [
        "agos_core.actions.kanban_board:read_ahead",
        "agos_core.actions.services.system.dashboard:read_ahead",
        "agos_core.actions.access:read_ahead",
        "agos_core.actions.hermes_channel:read_ahead",
    ]
    after = order.index(first_pages[-1])
    assert all(order.index(w) <= after for w in first_pages)
    assert order[after + 1 : after + 4] == [
        "agos_core.actions.hermes_settings:read_ahead",
        "agos_core.actions.hermes_helper_models:read_ahead",
        "agos_core.actions.hermes_all_settings:read_ahead",
    ]
    assert order[-1] == "agos_core.actions.hermes_health:read_ahead"


def test_the_workspace_cards_settings_list_is_read_ahead(env: Any) -> None:  # noqa: F811
    """/workspaces/{ws}/hermes-settings shows Hermes's own defaults (its settings
    list, one Hermes run kept while Hermes's defaults file holds): asked by the
    read-ahead, so the card never starts Hermes on its first view."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    asked: list[int] = []

    def schema() -> list[Any]:
        asked.append(1)
        return []

    core.engine.config_schema = schema
    read_ahead.run(core, ("agos_core.actions.hermes_settings:read_ahead",))
    assert asked == [1]
    assert client.get(f"/workspaces/{a}/hermes-settings").status_code == 200
