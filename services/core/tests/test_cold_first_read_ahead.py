"""Step 38 B: the pages that were slow only on their first ask after a restart
(account limits, channels, a chat's "/" menu, helper models, the model catalog,
a workspace's bots) are asked by the read-ahead after start; the account limits
(numbers that move all the time) also never make the page wait again."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from test_library import env, mcp, ws  # noqa: F401 - fixture

from agos_core.engine import limits, read_ahead
from agos_core.engine.hermes import HermesEngine
from agos_core.engine.read_cache import ReadCache

# Taken before conftest's stand-in replaces it for the tests.
REAL_GATEWAY_STATUS = HermesEngine.gateway_status

COLD_FIRST = (
    "agos_core.api.models:read_ahead",
    "agos_core.engine.limits:read_ahead",
    "agos_core.actions.channels:read_ahead",
    "agos_core.actions.hermes_helper_models:read_ahead",
    "agos_core.actions.hermes_channel:read_ahead",
)


def test_the_cold_first_pages_are_read_ahead_cheapest_first() -> None:
    assert set(COLD_FIRST) <= set(read_ahead.WARMERS)
    order = list(read_ahead.WARMERS)
    slow = order.index("agos_core.actions.hermes_all_settings:read_ahead")
    assert all(order.index(w) < slow for w in COLD_FIRST)
    assert order[-1] == "agos_core.actions.hermes_health:read_ahead"  # doctor: the longest


def test_each_cold_first_warmer_runs_on_a_fresh_core(env: Any) -> None:  # noqa: F811
    """They fill what the pages read and never fail the read-ahead (a Hermes that
    can't answer is logged and the page asks itself later)."""
    client, core, _runner, _home = env
    ws(client, "Alpha")
    menus: list[str] = []

    def menu(workspace_id: str) -> list[Any]:
        menus.append(workspace_id)
        return []

    core.engine.command_menu = menu
    took = read_ahead.run(core, COLD_FIRST)
    assert set(took) == set(COLD_FIRST)
    assert menus  # the root's "/" menu was asked once


def test_old_account_limits_come_at_once_and_are_read_again_behind(
    tmp_path: Path, monkeypatch: Any
) -> None:
    engine = SimpleNamespace(hermes_home=tmp_path)
    reads: list[float] = []

    def now(engine: Any, python: str, max_age: float = 60) -> list[Any]:
        # Like the real _limits_now: numbers younger than max_age are kept.
        hit = limits._cache.get(str(engine.hermes_home))
        if hit and time.monotonic() - hit[0] < max_age:
            return hit[1]
        reads.append(time.monotonic())
        found = [f"limits {len(reads)}"]
        limits._cache[str(engine.hermes_home)] = (time.monotonic(), found)  # type: ignore[assignment]
        return found

    monkeypatch.setattr(limits, "_limits_now", now)
    limits._cache.pop(str(tmp_path), None)
    assert limits.account_limits(engine, "py", kept=True) == ["limits 1"]  # type: ignore[arg-type,comparison-overlap]
    stamp, found = limits._cache[str(tmp_path)]
    limits._cache[str(tmp_path)] = (stamp - 120, found)  # two minutes old
    assert limits.account_limits(engine, "py", kept=True) == ["limits 1"]  # type: ignore[arg-type,comparison-overlap]
    assert ReadCache.settle(10)
    assert len(reads) == 2
    assert limits.account_limits(engine, "py", kept=True) == ["limits 2"]  # type: ignore[arg-type,comparison-overlap]
    # A decision (account_pause) never gets old numbers.
    limits._cache[str(tmp_path)] = (time.monotonic() - 120, ["old"])  # type: ignore[list-item]
    assert limits.account_limits(engine, "py") == ["limits 3"]  # type: ignore[arg-type,comparison-overlap]
    # A login came or went: the next view asks Hermes, not the last numbers.
    limits.forget()
    assert limits.account_limits(engine, "py", kept=True) == ["limits 4"]  # type: ignore[arg-type,comparison-overlap]
    limits._cache.pop(str(tmp_path), None)


def test_a_logout_forgets_the_account_limits(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    from agos_core.actions.services.settings import model_catalog, model_logins

    client, _core, _runner, _home = env
    limits._cache["somewhere"] = (time.monotonic(), [])
    logins = SimpleNamespace(logout=lambda *_args: None)
    monkeypatch.setattr(model_logins, "logins", lambda _core: logins)
    monkeypatch.setattr(model_logins, "provider_of", lambda provider, _core: provider)

    def load(_core: Any, _refresh: bool) -> dict[str, Any]:
        return {"providers": [], "catalog": []}

    monkeypatch.setattr(model_catalog, "load", load)
    assert client.post("/models/providers/anthropic/logout").status_code == 204
    assert "somewhere" not in limits._cache


def test_a_roots_command_menu_never_waits_on_the_minute(env: Any) -> None:  # noqa: F811
    """The "/" menu is kept while the root's config holds; after the minute that
    covers what only Hermes's code adds, the composer gets the kept menu at once
    and Hermes is asked again behind it. A config change is asked for at once."""
    client, core, _runner, _home = env
    workspace_id = ws(client, "Alpha")
    reads: list[int] = []

    def read_menu(home: Path) -> list[dict[str, str]]:
        reads.append(1)
        return [{"command": f"menu{len(reads)}", "description": ""}]

    core.engine._read_menu = read_menu
    assert core.engine.command_menu(workspace_id)[0]["command"] == "menu1"
    assert core.engine.command_menu(workspace_id)[0]["command"] == "menu1"
    assert len(reads) == 1
    for entry in core.engine._menus._entries.values():
        entry.stamp = -1  # a minute ago
    assert core.engine.command_menu(workspace_id)[0]["command"] == "menu1"  # at once
    assert ReadCache.settle(10)
    assert len(reads) == 2
    assert core.engine.command_menu(workspace_id)[0]["command"] == "menu2"
    config = core.engine.profile_home(workspace_id) / "config.yaml"
    config.write_text(config.read_text() + "\n# changed\n")
    assert core.engine.command_menu(workspace_id)[0]["command"] == "menu3"  # asked now


def test_a_pages_lamp_never_waits_while_its_gateway_lives(tmp_path: Path, monkeypatch: Any) -> None:
    """Channels, a workspace's bots and the dashboard asked Hermes's runtime about
    each bot's gateway whenever the last verdict was 2 s old (~1 s a bot). A page's
    lamp now gets the last verdict at once while the gateway process it named lives
    on (asked again behind it); a gateway that died or started is asked about
    before the lamp shows; a decision never gets a kept verdict."""
    monkeypatch.setattr(HermesEngine, "gateway_status", REAL_GATEWAY_STATUS)
    engine = HermesEngine.__new__(HermesEngine)
    engine._gw_seen, engine._gw_asking, engine._gw_lock = {}, set(), threading.Lock()
    asks: list[str] = []
    verdict: dict[str, Any] = {}

    def in_runtime(
        home: Path,
        script: str,
        tag: str,
        *,
        timeout: float = 30,
        extra: dict[str, str] | None = None,
    ) -> str:
        asks.append(tag)
        return json.dumps(verdict)

    engine._in_runtime = in_runtime  # type: ignore[method-assign]

    def older(home: Path) -> None:
        when, found, mark = engine._gw_seen[str(home)]
        engine._gw_seen[str(home)] = (when - 5, found, mark)

    home = tmp_path
    me = os.getpid()
    verdict.update(pid=me, record={"pid": me, "gateway_state": "running"}, live=True, stale=False)
    assert engine.gateway_status(home, kept=True)["stale"] is False
    assert engine.gateway_status(home, kept=True) and len(asks) == 1  # kept 2 s
    older(home)
    verdict["stale"] = True  # what Hermes says now
    assert engine.gateway_status(home, kept=True)["stale"] is False  # at once
    assert ReadCache.settle(10)
    assert len(asks) == 2
    assert engine.gateway_status(home, kept=True)["stale"] is True
    older(home)
    engine.gateway_status(home)  # a decision asks Hermes
    assert len(asks) == 3

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    verdict.update(pid=child.pid, record={"pid": child.pid, "gateway_state": "running"})
    verdict.update(live=True, stale=False)
    assert engine.gateway_status(home, fresh=True)["live"] is True
    child.kill()
    child.wait()
    older(home)
    verdict.update(pid=None, live=False)
    assert engine.gateway_status(home, kept=True)["live"] is False  # never a green lamp
    assert len(asks) == 5
    older(home)
    (home / "gateway.pid").write_text("123")  # a gateway started
    engine.gateway_status(home, kept=True)
    assert len(asks) == 6


def test_the_first_pages_are_asked_beside_the_start_sync(monkeypatch: Any) -> None:
    """Step 41: the model catalog and each workspace's tool check are asked at
    once when the core starts, while the start's sync still runs (it takes
    minutes on a busy server); the rest after it, the first ones again (kept)."""
    import asyncio

    from agos_core.actions.services.system import startup

    assert "agos_core.actions.library:read_ahead_connectors" in read_ahead.AT_START
    assert "agos_core.api.models:read_ahead" in read_ahead.AT_START
    assert set(read_ahead.AT_START) <= set(read_ahead.WARMERS)
    seen: list[str] = []
    syncing = threading.Event()

    def run(_core: Any, warmers: tuple[str, ...] | None = None) -> dict[str, float]:
        seen.append(
            f"read {'start' if warmers == read_ahead.AT_START else 'rest'}"
            f"{' (sync running)' if syncing.is_set() else ''}"
        )
        return {}

    async def sync(_core: Any) -> None:
        syncing.set()
        for _ in range(200):  # the sync waits until the first read ran beside it
            if seen:
                break
            await asyncio.sleep(0.01)
        seen.append("sync done")
        syncing.clear()

    monkeypatch.setattr(read_ahead, "run", run)
    monkeypatch.setattr(startup, "sync_then_serve", sync)
    asyncio.run(startup.serve_then_read_ahead(object()))
    assert seen == ["read start (sync running)", "sync done", "read rest"]


def test_the_capabilities_tool_check_is_read_ahead(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """The warmer asks each workspace's Hermes for its tool check; the page then
    answers from what Hermes said, with no Hermes start of its own."""
    client, core, _runner, _home = env
    w = ws(client, "Alpha")
    mcp(client, w, "crm", {"url": "https://crm.example.com/mcp"})  # one connector on
    (core.engine.profile_home(w) / "config.yaml").touch()
    core.engine._tools_seen.drop()
    checks: list[str] = []

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        checks.append(kw["env"]["HERMES_HOME"])
        out = 'AGOS-TOOLS {"web": true}\n'
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(core.engine, "_runtime_argv", lambda: ["python", "-c", "run"])
    monkeypatch.setattr(subprocess, "run", fake_run)  # the module hermes.py runs it from
    took = read_ahead.run(core, ("agos_core.actions.library:read_ahead_connectors",))
    assert set(took) == {"agos_core.actions.library:read_ahead_connectors"}
    assert checks == [str(core.engine.profile_home(w))]
    assert client.get(f"/workspaces/{w}/connectors").status_code == 200
    assert len(checks) == 1  # kept: the page started no Hermes
