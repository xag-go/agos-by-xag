"""Settings → Hermes settings, what reading the page costs Hermes: nothing more while
its source is unchanged, a row's save reads only that row, the page's Hermes asks run
side by side, and every AGOS write the page reads warms it again behind.

Split out of test_hermes_all_settings.py (the page's rows and writes stay there)."""

import ast
import time
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_hermes_all_settings import _stub_schema
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_all_settings as hall
from agos_core.actions.services.settings import hermes_reads, hermes_writes
from agos_core.engine import hermes_schema as hs

# Moved out of a HERMES_FILES file (conftest.py): it needs the installed Hermes too.
pytestmark = pytest.mark.hermes


def test_the_page_costs_hermes_nothing_more_when_its_source_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermes's Telegram adapter is read for its `extra.*` keys (an AST walk of its
    source, ~0.1 s) only while its files are unchanged: an upgrade shows at once."""
    from agos_core.engine import hermes_schema as hs

    folder = tmp_path / "plugins" / "platforms" / "telegram"
    folder.mkdir(parents=True)
    source = folder / "adapter.py"
    source.write_text("def a(extra):\n    return extra.get('one_key')\n")
    walks: list[int] = []
    real = ast.parse

    def counted(*args: Any, **kw: Any) -> Any:
        walks.append(1)
        return real(*args, **kw)

    monkeypatch.setattr(ast, "parse", counted)  # hermes_schema's own `import ast`
    assert [e.key for e in hs.platform_extras(tmp_path)] == ["one_key"]
    assert [e.key for e in hs.platform_extras(tmp_path)] == ["one_key"]
    assert len(walks) == 1
    source.write_text("def a(extra):\n    return extra.get('another_key')\n")
    assert [e.key for e in hs.platform_extras(tmp_path)] == ["another_key"]
    assert len(walks) == 2


def test_a_row_save_reads_only_that_row_not_the_whole_page(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """C8: saving one Hermes settings row looks up that row (and reads it back after
    the write) without the page's .env rows (each profile's .env probe) or the
    shared home's rows."""
    from agos_core.actions import hermes_all_settings as hall

    client, core, _runner, _home = env
    _stub_schema(core)
    ws(client, "Alpha")
    heavy: list[str] = []
    real_env, real_shared = hall._env_rows, hall.shared_rows

    def env_rows(*args: Any, **kw: Any) -> Any:
        heavy.append("env rows")
        return real_env(*args, **kw)

    def shared(*args: Any, **kw: Any) -> Any:
        heavy.append("shared rows")
        return real_shared(*args, **kw)

    # Patched where their callers look them up (the page's read and its write).
    monkeypatch.setattr(hermes_reads, "_env_rows", env_rows)
    monkeypatch.setattr(hermes_reads, "shared_rows", shared)
    warmed: list[Any] = []
    monkeypatch.setattr(hermes_writes, "warm_after_write", warmed.append)
    r = client.put(
        "/preferences/hermes-settings", json={"key": "checkpoints.enabled", "value": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] is True and r.json()["key"] == "checkpoints.enabled"
    assert heavy == []
    assert warmed == [core]  # the page's warm-up is asked for behind the save
    # The page itself still reads everything.
    client.get("/preferences/hermes-settings")
    assert heavy == ["env rows", "shared rows"]


def test_the_pages_hermes_asks_run_side_by_side(env: Any) -> None:  # noqa: F811
    """Step 41: after a change in Hermes (or right after a start) the page asked
    Hermes one thing after another: every profile as Hermes reads it (one run),
    then each profile's .env probe (two runs each), then the shared home's masker.
    They don't depend on each other, so they now start together (at most four
    Hermes processes at once, as before) and the page waits for the longest only.
    The answer is the same."""
    import threading

    client, core, _runner, _home = env
    _stub_schema(core)
    hs.keep_env(hs.env_vars({"TELEGRAM_HOME_CHANNEL": {"description": "Chat", "category": "x"}}))
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    alone = client.get("/preferences/hermes-settings").json()
    spans: dict[str, list[tuple[float, float]]] = {"reads": [], "probes": []}
    running: list[int] = [0, 0]  # now, most at once
    lock = threading.Lock()
    real_reads = core.engine.as_hermes_reads

    def hermes_start(kind: str, seconds: float) -> None:
        with lock:
            running[0] += 1
            running[1] = max(running)
        started = time.monotonic()
        time.sleep(seconds)
        with lock:
            running[0] -= 1
            spans[kind].append((started, time.monotonic()))

    def reads(homes: list[Any]) -> Any:
        hermes_start("reads", 0.6)
        return real_reads(homes)

    def env_in_use(home: Any) -> dict[str, Any]:
        hermes_start("probes", 0.6)
        return {"used": {}, "yaml": {}}

    core.engine.as_hermes_reads = reads
    core.engine.env_in_use = env_in_use
    started = time.monotonic()
    body = client.get("/preferences/hermes-settings").json()
    took = time.monotonic() - started
    assert len(spans["probes"]) == 2 and len(spans["reads"]) >= 1
    (read_start, read_end) = spans["reads"][0]
    assert any(s < read_end and read_start < e for s, e in spans["probes"])  # side by side
    assert took < 1.5, took  # was 0.6 (reads) + 0.6 (probes) one after the other
    assert running[1] <= 4
    assert body["settings"] == alone["settings"] and body["shared"] == alone["shared"]
    assert {a, b} <= {w["id"] for r in body["settings"] for w in r.get("workspaces") or []}


def test_agos_own_writes_warm_the_page_again_behind(env: Any) -> None:  # noqa: F811
    """Step 41: after AGOS's own save (here a Hermes settings row) the page's next
    view waited for Hermes (every changed profile's probe, ~1-5 s). The save now asks
    the page's Hermes reads again in the background at low priority, so the next
    view is ready; a change made outside AGOS is still asked at the next view (the
    stamps)."""
    import os
    import threading

    from test_settings_read_ahead import _envuse_runtime

    from agos_core.engine.read_cache import ReadCache

    client, core, _runner, _home = env
    _stub_schema(core)
    hs.keep_env(hs.env_vars({"TELEGRAM_HOME_CHANNEL": {"description": "Chat", "category": "x"}}))
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    runs = _envuse_runtime(core)
    answer = core.engine._in_runtime
    nice: list[int] = []

    def in_runtime(home: Path, script: str, tag: str, **kw: Any) -> str:
        nice.append(os.getpriority(os.PRIO_PROCESS, threading.get_native_id()))
        return answer(home, script, tag, **kw)  # type: ignore[no-any-return]

    core.engine._in_runtime = in_runtime
    assert client.get("/preferences/hermes-settings").status_code == 200
    assert ReadCache.settle(10)
    runs.clear()
    nice.clear()
    r = client.put(
        "/preferences/hermes-settings", json={"key": "checkpoints.max_snapshots", "value": 7}
    )
    assert r.status_code == 200, r.text
    assert ReadCache.settle(10)
    assert len(runs) == 4  # both profiles' config.yaml changed: two runs each, behind
    assert min(nice) >= 10, nice  # in the background
    runs.clear()
    body = client.get("/preferences/hermes-settings").json()
    assert runs == []  # ready: the view started no Hermes
    assert {r["key"]: r for r in body["settings"]}["checkpoints.max_snapshots"]["value"] == 7
    # A change made outside AGOS: asked at the next view, as before.
    config = core.engine.profile_home(a) / "config.yaml"
    config.write_text(config.read_text() + "\n# changed in Hermes\n")
    client.get("/preferences/hermes-settings")
    assert len(runs) == 2


def test_every_agos_write_the_page_reads_warms_it_again(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """The writes of AGOS that change what Settings → Hermes settings reads ask for
    its warm-up: a managed-scope write (every General card), a provider's extra keys
    (the managed .env), a workspace's Hermes settings card, a key of Workspace → Keys
    and a provider key of Settings → General (copied into every root's .env)."""

    from agos_core.actions import (
        engine as engine_actions,
    )
    from agos_core.actions import (
        general_sync,
        hermes_channel,
        hermes_managed,
        hermes_settings,
        key_pools,
        tool_keys,
    )
    from agos_core.actions.services.settings import model_keys

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    warmed: list[str] = []
    monkeypatch.setattr(hall, "warm_after_write", lambda _core: warmed.append("asked"))
    hermes_managed.write(core, {"display.compact": "true"})
    assert warmed == ["asked"]
    core.engine.managed_keys = lambda job: {"done": True}
    key_pools._keys(core, {"do": "swap", "base": "OPENAI_API_KEY", "n": [1, 2]})
    assert len(warmed) == 2
    monkeypatch.setattr(hermes_settings, "defaults", lambda _core: {})
    hermes_settings.write(core, a, {"goals.max_turns": "12"})
    assert len(warmed) == 3
    monkeypatch.setattr(hermes_channel, "restart_gateway", lambda *_a, **_k: None)
    monkeypatch.setattr(engine_actions, "refresh_cofounder_view", lambda *_a, **_k: None)
    tool_keys._after_change(core, a)
    assert len(warmed) == 4
    monkeypatch.setattr(general_sync, "sync", lambda _core: None)
    model_keys.to_every_root(core)
    assert len(warmed) == 5
