"""The cage is never turned off by accident (review M1; audit F9 made every mode but
"off" required, so "auto" here reads as required).

Before: one failed bwrap probe (a timeout, a fork error under TasksMax) was kept as
"bwrap can't run here" for the engine's whole life, and every gateway drop-in was
rewritten without the cage, so the next gateway start held the real Docker socket.
Now only a success is remembered, a refusal is asked again after a backoff, a
timeout proves nothing, and once bwrap ran on this machine (the cage.ok marker, or a
caged drop-in already written) a later failure refuses to start gateways instead of
starting them uncaged."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from test_cage import _caged_engine, _dropin
from test_wall import _Runner

from agos_core.engine import cage, sandbox_broker
from agos_core.hermes_gateway.errors import EngineError, HermesFailed, HermesTimeout


class _Bwrap(_Runner):
    """A runner whose bwrap probe follows a script: "ok", "fail" (non-zero exit) or
    "timeout"; the last entry repeats."""

    def __init__(self, *outcomes: str) -> None:
        super().__init__()
        self.outcomes = list(outcomes)
        self.probes = 0

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        if list(args)[:1] == [cage.BWRAP]:
            self.probes += 1
            outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
            if outcome == "fail":
                raise HermesFailed("bwrap failed", exit_code=1, reason="uid map")
            if outcome == "timeout":
                raise HermesTimeout("bwrap timed out", started=True)
            return ""
        return super().run(args, timeout=timeout, env=env)


@pytest.fixture(autouse=True)
def _bwrap_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage, "available", lambda: True)
    monkeypatch.setattr(cage, "_told_missing", [])
    monkeypatch.setattr(cage, "_told_at", {})


def _marker(tmp_path: Path) -> Path:
    return tmp_path / "data" / "system" / "cage.ok"


def test_a_timed_out_probe_proves_nothing_and_is_asked_again(tmp_path: Path) -> None:
    runner = _Bwrap("timeout", "ok")
    engine = _caged_engine(tmp_path, "auto", runner)
    # Unknown, and nothing proven yet: behave like `on` for this call (no uncaged start).
    with pytest.raises(EngineError, match="bwrap"):
        engine.sandboxd_on()
    assert engine.sandboxd_on() is True
    assert runner.probes == 2
    # The first success is remembered for the engine and on this machine.
    assert _marker(tmp_path).is_file()
    assert engine.sandboxd_on() is True and runner.probes == 2


def test_a_refused_probe_is_asked_again_after_the_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(sandbox_broker, "_clock", lambda: now[0])
    runner = _Bwrap("fail", "ok")
    engine = _caged_engine(tmp_path, "auto", runner)
    with pytest.raises(EngineError, match="cage_refused"):
        engine.sandboxd_on()  # never ran here: refused all the same (audit F9)
    now[0] += 10
    with pytest.raises(EngineError):
        engine.sandboxd_on()
    assert runner.probes == 1  # within the backoff
    now[0] += sandbox_broker.RETRY_AFTER
    assert engine.sandboxd_on() is True and runner.probes == 2
    assert _marker(tmp_path).is_file()


def test_once_bwrap_ran_here_a_later_failure_refuses_instead_of_uncaging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    body = _dropin(tmp_path, "auto", _Bwrap("ok"))
    assert '"bwrap"' in body and _marker(tmp_path).is_file()
    # A later core start (a new engine) whose probe fails: a refusal, never an uncaged
    # gateway. The drop-in written while bwrap worked stays as it is.
    for outcome in ("fail", "timeout"):
        broken = _caged_engine(tmp_path, "auto", _Bwrap(outcome))
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="agos"):
            with pytest.raises(EngineError, match="bwrap"):
                broken.sandboxd_on()
            with pytest.raises(EngineError):
                sandbox_broker.cage_argv(broken, "alpha")
            broken.refresh_dropin("alpha")
        told = [r for r in caplog.records if "won't start" in r.getMessage()]
        assert told and told[0].levelno == logging.ERROR and told[0].name.startswith("agos.")
        conf = next(
            (tmp_path / ".config" / "systemd" / "user").glob("*.service.d/agos-runtime.conf")
        )
        assert '"bwrap"' in conf.read_text(), outcome
    # The owner can still turn the cage off on purpose.
    assert _caged_engine(tmp_path, "off", _Bwrap("fail")).sandboxd_on() is False


def test_a_caged_dropin_counts_as_proof_without_the_marker(tmp_path: Path) -> None:
    """An install from before the marker: its gateways' drop-ins already carry bwrap."""
    _dropin(tmp_path, "auto", _Bwrap("ok"))
    _marker(tmp_path).unlink()
    with pytest.raises(EngineError, match="bwrap"):
        _caged_engine(tmp_path, "auto", _Bwrap("fail")).sandboxd_on()


def test_a_marker_from_another_machine_proves_nothing(tmp_path: Path) -> None:
    """A backup restored on a new server brings the old one's cage.ok along."""
    marker = _marker(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text("another-machine-id\n")
    with pytest.raises(EngineError) as refused:
        _caged_engine(tmp_path, "auto", _Bwrap("fail")).sandboxd_on()
    assert "worked on this server before" not in str(refused.value)
