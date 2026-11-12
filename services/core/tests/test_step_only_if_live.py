"""Real Hermes: a skipped automation step makes ZERO model calls.

A throwaway Hermes root with the agos-guard plugin and a scripted model (tests/e2e/
fake_llm.py, every request it gets is one log line). A card keyed like an automation's
step, the run's "Only if" file beside the board (as engine/automation_run.py writes
it), then Hermes's own dispatcher pass (`hermes kanban dispatch`) spawns the card's
real worker (`hermes -p default chat -q ...`). Its first turn's pre_llm_call hook
closes the card `agos-skipped: ...` and the model log stays empty; the same card
whose line holds is worked by the model as before. Twice: with this Hermes's veto,
and as an older Hermes without it (live's 0.22.2: the worker ends itself)."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import hermes_ready_home

from agos_core.engine import step_conditions
from agos_core.engine.guard_files import PLUGIN_SOURCE

HERE = Path(__file__).resolve().parent
HERMES = shutil.which("hermes")
# Real Hermes: out of the CI run (-m "not hermes"), like the files in conftest HERMES_FILES.
pytestmark = [pytest.mark.hermes, pytest.mark.skipif(HERMES is None, reason="needs Hermes")]

LINES = {"s2": [{"field": "payload.sheet", "op": "is", "values": ["Ideas-Inspiration"]}]}


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


OLD_HERMES = (
    "import sys\n"
    "def register(ctx):\n"
    "    # As on a Hermes before the pre_llm_call veto (live's 0.22.2): the plugin takes\n"
    "    # its other way out (the done card's worker ends itself).\n"
    "    gates = [m for n, m in list(sys.modules.items()) if n.endswith('step_gate')]\n"
    "    assert gates, 'agos-guard step_gate not loaded'\n"
    "    for gate in gates:\n"
    "        gate._veto_supported = lambda: False\n"
)


@pytest.fixture(params=["veto", "old hermes"])
def root(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[tuple[Path, Path, dict[str, str]]]:
    # The root lives OUTSIDE ~/.hermes: Hermes reads a home inside it as the machine's
    # own root (get_default_hermes_root), so its board would be the real one and the
    # machine's gateway would work the test's card.
    home = Path.home() / ".cache" / "agos-tests" / f"only-if-{uuid.uuid4().hex[:10]}"
    home.mkdir(parents=True)
    hermes_ready_home(home)
    shutil.copytree(
        PLUGIN_SOURCE, home / "plugins" / "agos-guard", ignore=shutil.ignore_patterns("__pycache__")
    )
    enabled = ["agos-guard"]
    if request.param == "old hermes":
        sim = home / "plugins" / "old-hermes"
        sim.mkdir()
        (sim / "plugin.yaml").write_text('name: old-hermes\nversion: "1.0"\ndescription: test\n')
        (sim / "__init__.py").write_text(OLD_HERMES)
        enabled.append("old-hermes")
    port, log = _port(), tmp_path / "llm.jsonl"
    log.touch()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "fakellm", "default": "fake-model"},
                "providers": {
                    "fakellm": {
                        "base_url": f"http://127.0.0.1:{port}/v1",
                        "api_key": "fake",
                        "api_mode": "chat_completions",
                    }
                },
                "terminal": {"backend": "local", "cwd": str(tmp_path)},
                "plugins": {"enabled": enabled},
            }
        )
    )
    llm = subprocess.Popen(  # noqa: S603 - the tests' own fake model
        [sys.executable, str(HERE / "e2e" / "fake_llm.py"), str(port), str(log)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # A clean Hermes environment: none of the caller's own Hermes session (a CI
    # runner, or an agent's terminal) leaks into the throwaway root's processes.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES", "_HERMES"))}
    env["HERMES_HOME"] = env["HERMES_KANBAN_HOME"] = str(home)
    try:
        yield home, log, env
    finally:
        llm.terminate()
        llm.wait(10)
        _stop_hermes_of(home)
        for _ in range(10):  # a worker ending late may still write its session
            shutil.rmtree(home, ignore_errors=True)
            time.sleep(1)
            if not home.exists():
                break


def _stop_hermes_of(home: Path) -> None:
    """Every Hermes process of the throwaway root (the per-root gateway Hermes starts
    to host its Kanban workers) ends with the test."""
    import signal

    mark = f"HERMES_HOME={home}".encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if mark in (proc / "environ").read_bytes().split(b"\0"):
                os.kill(int(proc.name), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            continue
    time.sleep(1)


def _hermes(env: dict[str, str], *args: str, timeout: float = 180) -> str:
    assert HERMES is not None
    done = subprocess.run(  # noqa: S603 - Hermes's own CLI
        [HERMES, *args], capture_output=True, text=True, env=env, timeout=timeout, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:] + done.stdout[-2000:]
    return done.stdout


def _card(env: dict[str, str], card: str) -> dict[str, Any]:
    out = _hermes(env, "kanban", "show", card, "--json")
    data = json.loads(out[out.find("{") :])
    return dict(data.get("task") or data)


def _step(home: Path, env: dict[str, str], sheet: str) -> str:
    """One automation step's card, its saved lines and its run's delivery beside the
    board (as AGOS's save and the run script write them)."""
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    step_conditions.keep_saved(
        home / "kanban.db", 9, [{"key": k, "only_if": v} for k, v in LINES.items()]
    )
    runs = home / "agos-automations" / "9.runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run}.only-if.json").write_text(
        json.dumps({"values": {}, "payloads": [{"sheet": sheet}]})
    )
    out = _hermes(
        env,
        "kanban",
        "create",
        "Inspiration Watcher: Grow the brand voice",
        "--json",
        "--body",
        "Run media_intake.py --kinds ideas,scripts and work its queue.",
        "--assignee",
        "default",
        "--idempotency-key",
        f"agos-automation:9:{run}:webhook:s2",
    )
    data = json.loads(out[out.find("{") :])
    card = str((data.get("task") or data)["id"])
    # On this root's own board, never the machine's (checked before anything starts it).
    with contextlib.closing(sqlite3.connect(f"file:{home / 'kanban.db'}?mode=ro", uri=True)) as db:
        assert db.execute("SELECT 1 FROM tasks WHERE id = ?", (card,)).fetchone(), card
    return card


def _worked(env: dict[str, str], card: str, wait_s: float = 240) -> dict[str, Any]:
    """Hermes's dispatcher starts the card's worker; the card once it is done."""
    _hermes(env, "kanban", "dispatch", "--max", "1")
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        task = _card(env, card)
        if task.get("status") == "done":
            time.sleep(3)  # the worker's last moments (a model call would land now)
            return task
        time.sleep(2)
    raise AssertionError(f"card {card} not done: {_card(env, card)}")


def _calls(log: Path) -> int:
    return len([line for line in log.read_text().splitlines() if line.strip()])


def test_a_skipped_step_makes_no_model_call(root: tuple[Path, Path, dict[str, str]]) -> None:
    home, log, env = root
    card = _step(home, env, "Editing-Inspiration")
    task = _worked(env, card)
    result = str(task.get("result") or "")
    assert result == (
        "agos-skipped: Only if sheet is one of Ideas-Inspiration (this run: Editing-Inspiration)"
    ), task
    assert _calls(log) == 0  # not one request reached the model


def test_the_same_step_with_work_runs_as_before(root: tuple[Path, Path, dict[str, str]]) -> None:
    home, log, env = root
    card = _step(home, env, "Ideas-Inspiration")
    _hermes(env, "kanban", "dispatch", "--max", "1")
    end = time.monotonic() + 180
    while _calls(log) == 0 and time.monotonic() < end:
        time.sleep(2)
    try:
        assert _calls(log) >= 1  # the worker's model works the step, as before
        assert not str(_card(env, card).get("result") or "").startswith("agos-skipped")
    finally:
        _hermes(env, "kanban", "archive", card)  # no retry of the scripted model's reply
