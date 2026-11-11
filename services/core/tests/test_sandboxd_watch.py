"""The broker's refused sandbox starts reach the owner as errors (engine/sandboxd_watch.py).

Live 2026-11-04..08: the broker refused every member sandbox and nobody saw it; the
agent only got "docker run ... exit status 125"."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from agos_core.engine import sandboxd_watch


def _event(profile: str, detail: str, kind: str = "denied") -> str:
    return json.dumps({"ts": 1.0, "profile": profile, "event": kind, "detail": detail}) + "\n"


REFUSED = "POST /containers/create: network 'agos-net-agos-alpha--a-scout' is not this workspace's"


def test_a_refused_start_is_an_error_of_its_workspace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(_event("agos-beta", REFUSED))  # before the first round: not told
    assert sandboxd_watch.report_new(tmp_path, "agos-") == 0
    with events.open("a") as handle:
        handle.write(_event("agos-alpha", REFUSED))
        handle.write(_event("agos-alpha", REFUSED))
        handle.write(_event("agos-alpha", "DELETE /containers/hermes-1a2b3c4d: no such container"))
        handle.write(_event("agos-alpha", "/run/x.sock", kind="serving"))
        handle.write("not json\n")
    with caplog.at_level(logging.ERROR, logger="agos.sandbox"):
        assert sandboxd_watch.report_new(tmp_path, "agos-") == 2
    errors = [r for r in caplog.records if r.name == "agos.sandbox"]
    assert len(errors) == 1  # once per workspace and reason per round
    assert errors[0].levelno == logging.ERROR
    assert getattr(errors[0], "agos_workspace", None) == "alpha"
    assert "agos-net-agos-alpha--a-scout" in errors[0].getMessage()
    assert "2 time" in errors[0].getMessage()
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="agos.sandbox"):
        assert sandboxd_watch.report_new(tmp_path, "agos-") == 0  # nothing new
    assert not caplog.records


def test_a_half_written_line_waits_and_a_cut_file_reads_from_the_start(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("")
    sandboxd_watch.report_new(tmp_path, "agos-")  # first round: marks the end
    line = _event("agos-alpha", REFUSED)
    events.write_text(line[:20])
    assert sandboxd_watch.report_new(tmp_path, "agos-") == 0
    events.write_text(line)
    assert sandboxd_watch.report_new(tmp_path, "agos-") == 1
    events.write_text(line)  # replaced by a shorter file: the old offset is past its end
    (tmp_path / sandboxd_watch.OFFSET_NAME).write_text("99999\n")
    assert sandboxd_watch.report_new(tmp_path, "agos-") == 1


def test_no_events_file_is_nothing_to_tell(tmp_path: Path) -> None:
    assert sandboxd_watch.report_new(tmp_path / "missing", "agos-") == 0


def test_the_check_runs_every_minute_on_the_job_loop() -> None:
    from agos_core.background import schedule
    from agos_core.jobs import recurring, runner

    schedule.register()
    assert schedule.DENIALS in runner.HANDLERS
    assert recurring.EVERY[schedule.DENIALS].interval.total_seconds() == 60
