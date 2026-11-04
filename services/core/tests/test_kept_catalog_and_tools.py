"""Step 41: Hermes's model catalog (every model picker, Settings → Models) and a
workspace's tool check (Capabilities) never make a page wait once Hermes answered:
after their few minutes, or once a file Hermes reads for them changed, the last
answer comes at once and Hermes is asked again behind it. An owner's action
(refresh, AGOS changing the workspace's tools) still asks Hermes now."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from test_library import env, mcp, ws  # noqa: F401 - fixture

from agos_core.config import EngineConfig
from agos_core.engine.models import ModelCatalog
from agos_core.engine.read_cache import ReadCache


def _payload(model: str) -> str:
    return json.dumps(
        {
            "providers": [
                {
                    "slug": "anthropic",
                    "name": "Anthropic",
                    "authenticated": True,
                    "models": [model],
                    "auth": "oauth_external",
                    "keyEnv": "",
                    "efforts": {},
                }
            ],
            "currentEffort": "",
            "keyEnvs": {},
        }
    )


def test_an_old_model_catalog_answers_at_once_and_is_read_again_behind(tmp_path: Path) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()
    engine = EngineConfig(
        hermes_bin="/bin/hermes",
        docker_bin="/bin/docker",
        hermes_home=home,
        profile_prefix="agos-",
        sandbox_image="img:1",
        host_home=tmp_path,
        roots_dir=tmp_path / "roots",
    )
    catalog = ModelCatalog(engine)
    asks: list[str] = []  # each one is a Hermes start (its live flag)
    hold = threading.Event()
    hold.set()

    def run(args: list[str], timeout: float, home: Path | None = None) -> str:
        assert hold.wait(10)
        asks.append(args[-1])
        return _payload(f"claude-{len(asks)}")

    catalog._run = run  # type: ignore[method-assign]
    catalog._python = lambda: "python"  # type: ignore[method-assign]
    catalog.pool = lambda home=None: []  # type: ignore[method-assign]

    def models() -> list[str]:
        return [m["id"] for p in catalog.load()["catalog"] for m in p["models"]]

    assert models() == ["claude-1"] and asks == ["1"]  # the first ask: live
    assert models() == ["claude-1"] and asks == ["1"]  # kept
    # Five minutes later: the last answer at once, Hermes asked again behind it.
    catalog._at -= catalog.ttl_s + 1
    hold.clear()
    assert models() == ["claude-1"]  # did not wait for Hermes
    hold.set()
    assert ReadCache.settle(10)
    assert asks == ["1", "0"]
    assert models() == ["claude-2"]
    # A file Hermes reads for it changed (a login in the shared home): the same.
    (home / "auth.json").write_text("{}")
    assert models() == ["claude-2"]
    assert ReadCache.settle(10)
    assert asks == ["1", "0", "0"]
    assert models() == ["claude-3"]
    assert models() == ["claude-3"] and len(asks) == 3  # nothing changed: kept
    # The owner's action (a key saved, a login): Hermes is asked now, live.
    assert [m["id"] for p in catalog.load(refresh=True)["catalog"] for m in p["models"]] == [
        "claude-4"
    ]
    assert asks[-1] == "1"


def test_an_old_tool_check_answers_at_once_and_is_asked_again_behind(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, core, _runner, _home = env
    w = ws(client, "Alpha")
    mcp(client, w, "crm", {"url": "https://crm.example.com/mcp"})  # one connector on
    home = core.engine.profile_home(w)
    (home / "config.yaml").touch()
    core.engine.forget_tools(w)
    checks: list[str] = []
    hold = threading.Event()
    hold.set()

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert hold.wait(10)
        checks.append(kw["env"]["HERMES_HOME"])
        out = f'AGOS-TOOLS {{"web": {"true" if len(checks) % 2 else "false"}}}\n'
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(core.engine, "_runtime_argv", lambda: ["python", "-c", "run"])
    monkeypatch.setattr(subprocess, "run", fake_run)  # the module hermes.py runs it from
    assert core.engine.tool_readiness(w) == {"web": True} and len(checks) == 1
    assert core.engine.tool_readiness(w) == {"web": True} and len(checks) == 1  # kept
    # Five minutes later: the last answer at once, Hermes asked again behind it.
    for entry in core.engine._tools_seen._entries.values():
        entry.stamp = -1
    hold.clear()
    assert core.engine.tool_readiness(w) == {"web": True}  # did not wait for Hermes
    hold.set()
    assert ReadCache.settle(10)
    assert len(checks) == 2
    assert core.engine.tool_readiness(w) == {"web": False}
    # A file Hermes reads for it changed (the profile's keys): the same, at once.
    (home / ".env").write_text("FIRECRAWL_API_KEY=x\n")
    assert core.engine.tool_readiness(w) == {"web": False}
    assert ReadCache.settle(10)
    assert len(checks) == 3
    assert core.engine.tool_readiness(w) == {"web": True}
    # AGOS changed the workspace's tools (the owner's switch): asked before it shows.
    core.engine.forget_tools(w)
    assert core.engine.tool_readiness(w) == {"web": False} and len(checks) == 4
