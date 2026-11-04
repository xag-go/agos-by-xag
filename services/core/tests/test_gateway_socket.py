"""A gateway's lamp asks Hermes's gateway control socket first (S4): the running
gateway answers `status` itself (gateway/control_socket.py, protocol 1), so no Hermes
runtime starts while it answers; no socket, no answer or `ok: false` = Hermes's
state files, read in its runtime, as before."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agos_core.config import EngineConfig
from agos_core.engine.hermes import HermesEngine


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HermesEngine:
    monkeypatch.undo()  # the engine's own gateway_status, not conftest's stand-in
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
        ),
        egress=False,
    )


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A socket path must fit sun_path (~100 bytes): the test's own tmp dir is too
    deep, so Hermes's own way is used, a short path named in gateway.sock.path."""
    base = os.environ.get("XDG_RUNTIME_DIR") or None
    folder = Path(tempfile.mkdtemp(prefix="agos-gw-", dir=base))
    yield folder
    for p in folder.iterdir():
        p.unlink()
    folder.rmdir()


class _Server:
    """A gateway's control socket: one JSON line in, one out, then it closes.

    `close()` wakes the accept thread with shutdown() and waits for it before the fd
    is closed: a thread still in accept() on a closed fd takes whatever socket gets
    that fd number next (seen on a 2-CPU CI runner: it took the fake Telegram's HTTP
    connections in later tests and reset them)."""

    def __init__(self, path: Path, answer: dict[str, Any], heard: list[dict[str, Any]]) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(path))
        self.sock.listen(4)
        self.answer, self.heard = answer, heard
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                line = conn.makefile("rb").readline()
                if not line:
                    continue
                self.heard.append(json.loads(line))
                conn.sendall(json.dumps(self.answer).encode() + b"\n")

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)
        self.thread.join(timeout=5)
        assert not self.thread.is_alive(), "the socket's accept thread didn't stop"
        self.sock.close()


def _serve(path: Path, answer: dict[str, Any], heard: list[dict[str, Any]]) -> _Server:
    return _Server(path, answer, heard)


def _home(engine: HermesEngine, sock: Path) -> Path:
    home = engine.settings.roots_dir / "agos-a"
    home.mkdir(parents=True)
    (home / "gateway.sock.path").write_text(str(sock))
    return home


def _no_runtime(engine: HermesEngine, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ran: list[str] = []

    def runtime(_home: Path, script: str, *_a: Any, **_k: Any) -> str:
        ran.append(script)
        return json.dumps({"pid": None, "record": None, "live": False, "stale": True})

    monkeypatch.setattr(engine, "_in_runtime", runtime)
    return ran


def test_a_gateway_that_answers_its_socket_starts_no_hermes_runtime(
    engine: HermesEngine, short_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _no_runtime(engine, monkeypatch)
    record = {"pid": 4242, "gateway_state": "running", "active_agents": 0, "updated_at": "x"}
    heard: list[dict[str, Any]] = []
    server = _serve(
        short_dir / "g.sock",
        {
            "ok": True,
            "protocol": 1,
            "id": 1,
            "result": {**record, "protocol": 1, "answered_at": 1.0, "answering_pid": 4242},
        },
        heard,
    )
    try:
        verdict = engine.gateway_status(_home(engine, short_dir / "g.sock"), fresh=True)
    finally:
        server.close()
    assert heard == [{"verb": "status", "id": 1, "protocol": 1}]
    assert verdict == {"pid": 4242, "record": record, "live": True, "stale": False}
    assert ran == []


@pytest.mark.parametrize(
    "answer",
    [
        {"ok": False, "error": "unknown verb: 'status'", "protocol": 1},
        {"ok": True, "protocol": 2, "result": {"answering_pid": 7, "pid": 7}},
        # The record it holds is not its own: Hermes's state files decide.
        {"ok": True, "protocol": 1, "result": {"answering_pid": 7, "pid": 8}},
    ],
)
def test_an_answer_that_doesnt_fit_asks_hermes_state_files(
    engine: HermesEngine,
    short_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
) -> None:
    ran = _no_runtime(engine, monkeypatch)
    server = _serve(short_dir / "g.sock", answer, [])
    try:
        verdict = engine.gateway_status(_home(engine, short_dir / "g.sock"), fresh=True)
    finally:
        server.close()
    assert len(ran) == 1 and verdict["live"] is False


def test_no_socket_or_a_dead_one_asks_hermes_state_files(
    engine: HermesEngine, short_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = _no_runtime(engine, monkeypatch)
    home = engine.settings.roots_dir / "agos-b"
    home.mkdir(parents=True)
    engine.gateway_status(home, fresh=True)  # no socket at all
    dead = short_dir / "dead.sock"
    left = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    left.bind(str(dead))  # a socket file no gateway listens on (it died)
    left.close()
    engine.gateway_status(_home(engine, dead), fresh=True)
    assert len(ran) == 2
