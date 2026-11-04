"""A stand-in engine for HermesEngine.env_in_use (the ".env vs config.yaml" probe) and
the helpers test_hermes_all_settings.py reads its two Hermes runs with."""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agos_core.engine import hermes as engine_mod
from agos_core.engine.read_cache import ReadCache

__all__ = [
    "NOT_SET_UP",
    "_env_probe_engine",
    "_gateway_run",
    "_one_after_the_other",
    "_side",
    "_side_kind",
    "_yaml_run",
]


def _env_probe_engine(tmp_path: Path) -> tuple[Any, Path, Path, list[dict[str, Any]]]:
    """A stand-in engine for HermesEngine.env_in_use: its runtime records each run
    (the home the process starts in, the job, what the throwaway home and scope
    hold) and answers like Hermes's gateway start would (_ENV_IN_USE: the YAML side's
    diff, or the gateway's side: each .env name's value, the managed .env's names
    and every UPPER name left in the environment)."""
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "config.yaml").write_text("terminal:\n  timeout: 300\n")
    (managed / ".env").write_text("TERMINAL_TIMEOUT=300\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n")
    calls: list[dict[str, Any]] = []
    # The gateway's environment after its start, and the names its .env holds.
    gateway = {"TERMINAL_TIMEOUT": "300", "TELEGRAM_REACTIONS": "true", "PATH": "/bin"}

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        literal = script.split("job = json.loads(", 1)[1].split(")\n", 1)[0]
        job = json.loads(ast.literal_eval(literal))
        seen: dict[str, Any] = {"home": h, "job": job, "extra": kw.get("extra")}
        for side in ("home", "scope"):
            if job.get(side):
                seen[f"{side}_files"] = sorted(p.name for p in Path(job[side]).iterdir())
        calls.append(seen)
        if job.get("diff"):
            return json.dumps({"TERMINAL_TIMEOUT": "300", "TELEGRAM_REACTIONS": "false"})
        names = set(job.get("names") or []) | {"TERMINAL_TIMEOUT"}
        return json.dumps(
            {
                "used": {k: gateway.get(k) for k in sorted(names)},
                "managed": ["TERMINAL_TIMEOUT"],
                "env": {k: v for k, v in gateway.items() if k.isupper()},
            }
        )

    engine: Any = engine_mod.HermesEngine.__new__(engine_mod.HermesEngine)
    engine.settings = SimpleNamespace(managed_home=managed)
    engine._env_use = ReadCache("test-env-in-use")
    engine._env_yaml = ReadCache("test-env-in-use-yaml")
    engine._settings_slots = threading.BoundedSemaphore(4)
    engine._probe_runs = engine_mod._ProbeRuns()
    engine._in_runtime = in_runtime
    return engine, home, managed, calls


def _yaml_run(calls: list[dict[str, Any]]) -> dict[str, Any]:
    (found,) = [c for c in calls if c["job"].get("diff")]
    return found


def _gateway_run(calls: list[dict[str, Any]]) -> dict[str, Any]:
    (found,) = [c for c in calls if not c["job"].get("diff")]
    return found


# What Hermes's launcher says (its last stderr line, as _in_runtime raises it) when it
# starts in a data root whose dependency environment is not committed yet while
# another start is setting it up (hermes_bootstrap.py:613 activate_dependencies →
# pm/environments.py:446 _require_own_dependencies; printed at hermes_bootstrap.py:619).
NOT_SET_UP = (
    "Hermes didn't answer: hermes: no dependency environment is committed for this "
    "install; run `hermes pm repair`"
)


def _side(script: str) -> str:
    literal = script.split("job = json.loads(", 1)[1].split(")\n", 1)[0]
    return "yaml" if json.loads(ast.literal_eval(literal)).get("diff") else "gateway"


def _one_after_the_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """The probe's answer from its two runs one after the other (before Step 41), in a
    root that is set up."""

    def one_after_the_other(first: Any, second: Any) -> tuple[Any, Any]:
        value = first()
        return value, second()

    old = tmp_path / "one-after-the-other"
    old.mkdir()
    engine, home, _managed, _calls = _env_probe_engine(old)
    with monkeypatch.context() as m:
        m.setattr(engine_mod, "_side_by_side", one_after_the_other)
        return json.dumps(engine_mod.HermesEngine.env_in_use(engine, home))


def _side_kind(call: dict[str, Any]) -> str:
    return "yaml" if call["job"].get("diff") else "gateway"
