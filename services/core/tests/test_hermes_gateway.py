"""The Hermes Gateway (ADR 0024): every Hermes call through the Runner gets typed
errors, a circuit breaker per workspace root, one retry for idempotent reads whose
process could not start, and one log record (no argument values)."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from agos_core.hermes_gateway import breaker as breaker_module
from agos_core.hermes_gateway.errors import (
    EngineError,
    HermesFailed,
    HermesTimeout,
    HermesUnavailable,
)
from agos_core.hermes_gateway.runner import GatewayRunner, SubprocessRunner

ROOT_A = "/data/hermes/agos-a"
ROOT_B = "/data/hermes/agos-b"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Scripted:
    """A fake runner whose answers are scripted per call (an exception or stdout)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[list[str]] = []
        self.spawned: list[list[str]] = []
        self.flag = "fake's own"

    def run(self, args: Sequence[str], *, timeout: float, env: dict[str, str] | None = None) -> str:
        self.calls.append(list(args))
        answer = self.answers.pop(0) if self.answers else "ok"
        if isinstance(answer, BaseException):
            raise answer
        return str(answer)

    def spawn(
        self, args: Sequence[str], *, log_file: Path, env: dict[str, str] | None = None
    ) -> None:
        self.spawned.append(list(args))


def _down() -> HermesTimeout:
    return HermesTimeout("hermes did not answer", started=True)


def _home(root: str, member: str | None = None) -> dict[str, str]:
    return {"HERMES_HOME": f"{root}/profiles/{member}" if member else root}


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    tick = Clock()
    monkeypatch.setattr(breaker_module, "BREAKERS", breaker_module.Breakers(clock=tick))
    return tick


def test_three_timeouts_open_the_roots_circuit_and_it_then_fails_fast(clock: Clock) -> None:
    inner = Scripted(_down(), _down(), _down())
    gw = GatewayRunner(inner)
    for _ in range(3):
        with pytest.raises(HermesTimeout):
            gw.run(["hermes", "kanban", "edit", "1"], timeout=60, env=_home(ROOT_A))
    with pytest.raises(HermesUnavailable) as caught:
        gw.run(["hermes", "kanban", "edit", "1"], timeout=60, env=_home(ROOT_A))
    assert caught.value.code == "HERMES_UNAVAILABLE"
    assert isinstance(caught.value, EngineError)
    assert len(inner.calls) == 3  # the fourth never started Hermes


def test_a_member_home_counts_as_its_root_and_another_root_is_not_affected(
    clock: Clock,
) -> None:
    inner = Scripted(_down(), _down(), _down())
    gw = GatewayRunner(inner)
    for member in ("m1", "m2", None):
        with pytest.raises(HermesTimeout):
            gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A, member))
    with pytest.raises(HermesUnavailable):
        gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A, "m3"))
    assert gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_B)) == "ok"


def test_a_refusal_is_an_answer_and_never_opens_the_circuit(clock: Clock) -> None:
    refusals = [HermesFailed("hermes failed", exit_code=1, reason="no") for _ in range(5)]
    inner = Scripted(*refusals)
    gw = GatewayRunner(inner)
    for _ in range(5):
        with pytest.raises(HermesFailed):
            gw.run(["hermes", "kanban", "edit", "1"], timeout=60, env=_home(ROOT_A))
    assert gw.run(["hermes", "kanban", "edit", "1"], timeout=60, env=_home(ROOT_A)) == "ok"


def test_a_plain_engine_error_from_a_fake_does_not_open_the_circuit(clock: Clock) -> None:
    inner = Scripted(*(EngineError("hermes failed") for _ in range(4)))
    gw = GatewayRunner(inner)
    for _ in range(4):
        with pytest.raises(EngineError):
            gw.run(["hermes", "x"], timeout=60, env=_home(ROOT_A))
    assert gw.run(["hermes", "x"], timeout=60, env=_home(ROOT_A)) == "ok"


def test_after_the_cool_down_one_probe_passes_and_success_closes_the_circuit(
    clock: Clock,
) -> None:
    inner = Scripted(_down(), _down(), _down(), "back")
    gw = GatewayRunner(inner)
    for _ in range(3):
        with pytest.raises(HermesTimeout):
            gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    clock.now += breaker_module.OPEN_FOR_S - 1
    with pytest.raises(HermesUnavailable):
        gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    clock.now += 2
    assert gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A)) == "back"
    assert gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A)) == "ok"


def test_a_failed_probe_opens_the_circuit_again_at_once(clock: Clock) -> None:
    inner = Scripted(_down(), _down(), _down(), _down())
    gw = GatewayRunner(inner)
    for _ in range(3):
        with pytest.raises(HermesTimeout):
            gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    clock.now += breaker_module.OPEN_FOR_S + 1
    with pytest.raises(HermesTimeout):
        gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    with pytest.raises(HermesUnavailable):
        gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    assert len(inner.calls) == 4


def test_while_the_probe_runs_other_calls_fail_fast(clock: Clock) -> None:
    breakers = breaker_module.BREAKERS
    for _ in range(3):
        breakers.failed(ROOT_A)
    clock.now += breaker_module.OPEN_FOR_S + 1
    assert breakers.allow(ROOT_A) is True  # the probe
    assert breakers.allow(ROOT_A) is False  # a second caller while it runs
    breakers.answered(ROOT_A)
    assert breakers.allow(ROOT_A) is True


def test_recovery_commands_pass_an_open_circuit_and_a_success_closes_it(clock: Clock) -> None:
    inner = Scripted(_down(), _down(), _down(), "repaired")
    gw = GatewayRunner(inner)
    for _ in range(3):
        with pytest.raises(HermesTimeout):
            gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A))
    assert gw.run(["hermes", "pm", "repair"], timeout=60, env=_home(ROOT_A)) == "repaired"
    assert gw.run(["hermes", "status"], timeout=60, env=_home(ROOT_A)) == "ok"


def test_docker_calls_are_never_counted_as_hermes(clock: Clock) -> None:
    inner = Scripted(_down(), _down(), _down(), _down())
    gw = GatewayRunner(inner)
    for _ in range(4):
        with pytest.raises(HermesTimeout):
            gw.run(["/bin/docker", "ps"], timeout=60, env=None)
    assert gw.run(["hermes", "status"], timeout=60, env=None) == "ok"


def test_an_idempotent_read_whose_process_could_not_start_is_tried_once_more(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.hermes_gateway import runner as runner_module

    monkeypatch.setattr(runner_module, "RETRY_PAUSE_S", 0.0)
    inner = Scripted(HermesTimeout("hermes did not answer", started=False), "[]")
    gw = GatewayRunner(inner)
    assert gw.run(["hermes", "kanban", "list", "--json"], timeout=60, env=_home(ROOT_A)) == "[]"
    assert len(inner.calls) == 2


def test_a_write_is_never_retried(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.hermes_gateway import runner as runner_module

    monkeypatch.setattr(runner_module, "RETRY_PAUSE_S", 0.0)
    inner = Scripted(HermesTimeout("hermes did not answer", started=False), "done")
    gw = GatewayRunner(inner)
    with pytest.raises(HermesTimeout):
        gw.run(["hermes", "config", "set", "k", "v"], timeout=60, env=_home(ROOT_A))
    assert len(inner.calls) == 1


def test_a_timed_out_read_is_not_retried(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.hermes_gateway import runner as runner_module

    monkeypatch.setattr(runner_module, "RETRY_PAUSE_S", 0.0)
    inner = Scripted(_down(), "[]")
    gw = GatewayRunner(inner)
    with pytest.raises(HermesTimeout):
        gw.run(["hermes", "kanban", "list"], timeout=60, env=_home(ROOT_A))
    assert len(inner.calls) == 1


def test_each_call_is_logged_with_its_words_duration_and_exit_but_no_values(
    clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "sk-live-0123456789abcdef"  # noqa: S105 - a fake key
    inner = Scripted("ok", HermesFailed("hermes failed", exit_code=2, reason=""))
    gw = GatewayRunner(inner)
    caplog.set_level(logging.DEBUG, logger="agos.hermes_gateway")
    gw.run(["/opt/bin/hermes", "config", "set", "OPENAI_API_KEY", secret], timeout=60)
    with pytest.raises(HermesFailed):
        gw.run(["hermes", "-p", "member-x", "kanban", "edit", "1", secret], timeout=60)
    records = [r for r in caplog.records if r.name == "agos.hermes_gateway"]
    assert len(records) == 2
    first, second = (vars(r)["hermes"] for r in records)
    assert first["command"] == "hermes config set (+2 args)"
    assert first["exit_code"] == 0 and first["outcome"] == "ok"
    assert isinstance(first["duration_s"], float)
    assert second["command"] == "hermes kanban edit (+4 args)"
    assert second["exit_code"] == 2 and second["outcome"] == "refused"
    assert secret not in caplog.text and "member-x" not in caplog.text
    assert "OPENAI_API_KEY" not in caplog.text


def test_a_walled_command_is_logged_by_the_hermes_words_after_the_wall(
    clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    gw = GatewayRunner(Scripted("ok"))
    caplog.set_level(logging.DEBUG, logger="agos.hermes_gateway")
    walled = ["/usr/bin/python3", "-I", "/x/wall.py", "--rw", "/secret/dir", "--"]
    gw.run([*walled, "/bin/hermes", "skills", "list"], timeout=60, env=_home(ROOT_A))
    (record,) = [r for r in caplog.records if r.name == "agos.hermes_gateway"]
    assert vars(record)["hermes"]["command"] == "walled hermes skills list"
    assert "/secret/dir" not in caplog.text


def test_spawn_passes_through(clock: Clock) -> None:
    inner = Scripted()
    GatewayRunner(inner).spawn(["hermes", "gateway", "run"], log_file=Path("/dev/null"))
    assert inner.spawned == [["hermes", "gateway", "run"]]


def test_the_wrapper_reads_and_writes_the_fakes_own_attributes(clock: Clock) -> None:
    inner = Scripted()
    gw = GatewayRunner(inner)
    assert gw.flag == "fake's own"
    gw.flag = "changed"
    assert inner.flag == "changed"
    assert gw.inner is inner


def test_the_engine_wraps_every_runner_it_gets(tmp_path: Path, clock: Clock) -> None:
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import HermesEngine

    settings = EngineConfig(
        hermes_bin="/bin/hermes",
        docker_bin="/bin/docker",
        hermes_home=tmp_path / ".hermes",
        profile_prefix="agos-",
        sandbox_image="img:1",
        host_home=tmp_path,
        roots_dir=tmp_path / "roots",
    )
    first = Scripted()
    engine = HermesEngine(settings, runner=first)
    assert isinstance(engine.runner, GatewayRunner) and engine.runner.inner is first
    second = Scripted()
    engine.runner = second  # what the tests' fixtures do
    assert isinstance(engine.runner, GatewayRunner) and engine.runner.inner is second
    wrapped = engine.runner
    engine.runner = wrapped
    assert engine.runner is wrapped  # never wrapped twice
    real = HermesEngine(settings).runner
    assert isinstance(real, GatewayRunner) and isinstance(real.inner, SubprocessRunner)


def test_the_real_runner_raises_typed_errors(tmp_path: Path) -> None:
    with pytest.raises(HermesFailed) as refused:
        SubprocessRunner().run([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert refused.value.exit_code == 3 and refused.value.code == "HERMES_FAILED"
    with pytest.raises(HermesTimeout) as missing:
        SubprocessRunner().run([str(tmp_path / "no-such-hermes"), "status"], timeout=30)
    assert missing.value.started is False
    assert str(missing.value) == "no-such-hermes did not answer"
    assert missing.value.code == "HERMES_TIMEOUT"


def test_the_old_names_still_import_from_the_engine() -> None:
    from agos_core.engine import hermes

    assert hermes.EngineError is EngineError
    assert hermes.SubprocessRunner is SubprocessRunner
    assert hermes.Runner is not None and hermes.refusal_line is not None


def test_the_cli_names_forward_to_the_engines_own_methods() -> None:
    from agos_core.hermes_gateway import cli as hermes_cli

    seen: list[tuple[Any, ...]] = []

    class Engine:
        def _hermes(self, ws: str, *args: str, timeout: float = 60) -> str:
            seen.append(("cli", ws, args, timeout))
            return "out"

        def walled_cli(self, key: str, *args: str, timeout: float = 60) -> str:
            seen.append(("walled", key, args, timeout))
            return "walled"

        def config_writes(self, ws: str, commands: Any) -> list[str]:
            seen.append(("writes", ws, commands))
            return ["k"]

        def managed_write(self, sets: Any, unsets: Any) -> None:
            seen.append(("managed", sets, unsets))

    engine: Any = Engine()
    assert hermes_cli.cli(engine, "ws", "kanban", "list", timeout=5) == "out"
    assert hermes_cli.walled_cli(engine, "ws--m", "skills", "list") == "walled"
    assert hermes_cli.config_writes(engine, "ws", [("config", "unset", "k")]) == ["k"]
    hermes_cli.managed_write(engine, [("a", "b")], [])
    assert seen == [
        ("cli", "ws", ("kanban", "list"), 5),
        ("walled", "ws--m", ("skills", "list"), 60),
        ("writes", "ws", [("config", "unset", "k")]),
        ("managed", [("a", "b")], []),
    ]


def test_a_runtime_run_answers_with_its_exit_and_is_logged(
    clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    from agos_core.hermes_gateway import process

    caplog.set_level(logging.DEBUG, logger="agos.hermes_gateway")
    done = process.run_process(
        [sys.executable, "-c", "import sys; print('hi'); sys.exit(4)"],
        timeout=30,
        env=_home(ROOT_A),
    )
    assert done.returncode == 4 and done.stdout.strip() == "hi"
    (record,) = [r for r in caplog.records if r.name == "agos.hermes_gateway"]
    assert vars(record)["hermes"]["exit_code"] == 4
    assert "import sys" not in caplog.text


def test_a_runtime_run_on_an_open_circuit_fails_fast_as_an_os_error(clock: Clock) -> None:
    from agos_core.hermes_gateway import process

    for _ in range(3):
        breaker_module.BREAKERS.failed(ROOT_A)
    with pytest.raises(OSError) as caught:  # what the callers already catch
        process.run_process([sys.executable, "-c", "pass"], timeout=30, env=_home(ROOT_A))
    assert isinstance(caught.value, HermesUnavailable)


def test_a_runtime_run_that_times_out_counts_against_its_root(clock: Clock) -> None:
    import subprocess

    from agos_core.hermes_gateway import process

    for _ in range(3):
        with pytest.raises(subprocess.TimeoutExpired):
            process.run_process(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.05,
                env=_home(ROOT_A),
            )
    assert breaker_module.BREAKERS.is_open(ROOT_A)


def test_a_spawned_process_is_handed_back(clock: Clock) -> None:
    import subprocess

    from agos_core.hermes_gateway import process

    proc = process.spawn_process(
        [sys.executable, "-c", "print('up')"], env=_home(ROOT_A), stdout=subprocess.PIPE, text=True
    )
    out, _ = proc.communicate(timeout=30)
    assert out.strip() == "up"


def test_a_hermes_database_opens_read_only(tmp_path: Path) -> None:
    import sqlite3

    from agos_core.hermes_gateway import hermes_db

    path = tmp_path / "kanban.db"
    with sqlite3.connect(path) as made:
        made.execute("CREATE TABLE tasks (id TEXT)")
        made.execute("INSERT INTO tasks VALUES ('t1')")
    db = hermes_db.connect_ro(path, timeout=2)
    try:
        assert db.execute("SELECT id FROM tasks").fetchall() == [("t1",)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("INSERT INTO tasks VALUES ('t2')")
    finally:
        db.close()


def test_a_missing_hermes_database_is_never_made(tmp_path: Path) -> None:
    import sqlite3

    from agos_core.hermes_gateway import hermes_db

    with pytest.raises(sqlite3.Error):
        hermes_db.connect_ro(tmp_path / "state.db")
    assert not (tmp_path / "state.db").exists()
