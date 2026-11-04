"""Hermes never starts on the core's event loop (engine/loop_guard.py), kept by the
suite itself: strict mode is on for every test, a GET route without an await runs
in FastAPI's threadpool, an async route that starts Hermes fails, and the
background loops hand their Hermes work to a thread."""

from __future__ import annotations

import ast
import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agos_core.config import EngineConfig
from agos_core.engine import loop_guard
from agos_core.engine.hermes import HermesEngine

API = Path(__file__).resolve().parents[1] / "src" / "agos_core" / "api"
VERBS = {"get", "post", "put", "delete", "patch"}

# Answered on the event loop on purpose: /health does no work at all, and it is
# how a blocked loop is told apart from a busy threadpool.
ON_THE_LOOP = {("app.py", "health")}

Route = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, set[str]]


def _routes() -> list[Route]:
    found: list[Route] = []
    for path in sorted(API.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            verbs = {
                d.func.attr
                for d in node.decorator_list
                if isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in VERBS
            }
            if verbs:
                found.append((path.name, node, verbs))
    return found


def _awaits(node: ast.AST) -> bool:
    """The route itself awaits (a function defined inside it doesn't count)."""
    todo = list(ast.iter_child_nodes(node))
    while todo:
        child = todo.pop()
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(child, ast.Await | ast.AsyncFor | ast.AsyncWith):
            return True
        todo.extend(ast.iter_child_nodes(child))
    return False


def test_a_read_without_await_runs_off_the_event_loop() -> None:
    """An `async def` GET with no await runs its whole read ON the loop: every page
    and gateway call waits while it reads Hermes. A plain `def` runs in FastAPI's
    threadpool."""
    routes = _routes()
    assert len(routes) > 200  # the scan sees the API
    on_loop = [
        f"{file}:{node.name}"
        for file, node, verbs in routes
        if "get" in verbs
        and isinstance(node, ast.AsyncFunctionDef)
        and not _awaits(node)
        and (file, node.name) not in ON_THE_LOOP
    ]
    assert on_loop == []


def test_the_suite_runs_with_the_strict_loop_guard() -> None:
    assert os.environ.get("AGOS_STRICT_LOOP") == "1"


class _Runner:
    """Hermes's CLI as the tests fake it: the guard sits above the runner."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        self.calls.append(list(args))
        return "[]"

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        raise AssertionError("no gateway here")


def test_an_async_route_that_starts_hermes_fails(tmp_path: Path) -> None:
    runner = _Runner()
    engine = HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        runner,
        egress=False,
    )
    app = FastAPI()

    @app.get("/on-the-loop")
    async def on_the_loop() -> str:
        return engine._hermes("a", "kanban", "list", "--json")

    @app.get("/in-a-thread")
    def in_a_thread() -> str:
        return engine._hermes("a", "kanban", "list", "--json")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/in-a-thread").status_code == 200
        assert client.get("/on-the-loop").status_code == 500
    # Hermes ran once, from the thread; the loop never started it.
    assert runner.calls == [["/bin/hermes", "kanban", "list", "--json"]]
    assert loop_guard.broken == ["hermes kanban"]
    loop_guard.broken.clear()


class _Stop(Exception):
    pass


def test_the_trash_purge_runs_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """The six-hourly purge removes Hermes's profiles, sandboxes and big folders: a
    job (agos_core/background/schedule.py) the job loop runs in a thread."""
    from types import SimpleNamespace

    from agos_core.background import schedule, trash
    from agos_core.db.connection import open_database
    from agos_core.jobs import recurring
    from agos_core.jobs import runner as jobs_loop

    purged: list[object] = []

    def purge_expired(core: object) -> list[str]:
        loop_guard.off_loop("hermes profile delete")
        purged.append(core)
        return []

    async def sleep(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(recurring, "EVERY", {})
    monkeypatch.setattr(jobs_loop, "HANDLERS", {})
    schedule.register()
    monkeypatch.setattr(trash, "purge_expired", purge_expired)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    core = SimpleNamespace(db=open_database(":memory:"), engine=None)
    with pytest.raises(_Stop):
        asyncio.run(jobs_loop.run_forever(core))
    assert purged == [core]


def test_an_answer_started_from_a_thread_still_starts_on_the_loop() -> None:
    """A chat action runs in a thread (its reads may start Hermes); a room's answer
    it starts still begins on the loop at once, not at the next tick."""
    from agos_core.actions import chat

    class _Core:
        db = object()  # the chat state is kept per database

    core = _Core()
    ran: list[bool] = []

    async def answer() -> None:
        ran.append(loop_guard.on_loop())

    def action() -> None:
        assert not loop_guard.on_loop()
        chat._spawn(core, answer())  # type: ignore[arg-type]

    async def route() -> None:
        await chat.in_thread(action)
        for _ in range(20):
            if ran:
                break
            await asyncio.sleep(0)

    try:
        asyncio.run(route())
    finally:
        chat._STATES.pop(id(core.db), None)
    assert ran == [True]
