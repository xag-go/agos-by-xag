"""The cage is required by default (audit F9): a public install must be safe with
nothing to configure.

Before: AGOS_SANDBOXD defaulted to "auto", which on a machine without a working
bwrap (not installed, or stopped by the kernel) started every gateway uncaged, with
the real Docker socket, and only logged a line. Now an unset AGOS_SANDBOXD (and the
old "auto"/"on" values) means "required": no working bwrap = the gateway does not
start, with the plain code `cage_refused` (docs/errors.md). Only the owner's own
AGOS_SANDBOXD=off runs gateways uncaged, and then Settings → Server & backup and
`agos doctor` say so. A machine where bwrap works (the owner's live server: cage.ok
on every gateway) is unchanged: the same caged drop-in as before."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_cage import _caged_engine, _dropin
from test_wall import HERMES_UNIT, _Runner, _volumes

from agos_core import config
from agos_core.api import error_bodies
from agos_core.domain.errors import TEXTS, ErrorCode
from agos_core.engine import cage, root_unit, sandbox_broker
from agos_core.hermes_gateway.errors import CageRefused, EngineError, HermesFailed, HermesTimeout


class _Bwrap(_Runner):
    """bwrap's probe answers `outcome`: "ok", "fail" (refused) or "timeout"."""

    def __init__(self, outcome: str) -> None:
        super().__init__()
        self.outcome = outcome

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        if list(args)[:1] == [cage.BWRAP]:
            if self.outcome == "fail":
                raise HermesFailed("bwrap failed", exit_code=1, reason="uid map")
            if self.outcome == "timeout":
                raise HermesTimeout("bwrap timed out", started=True)
            return ""
        return super().run(args, timeout=timeout, env=env)


@pytest.fixture(autouse=True)
def _fresh_cage_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage, "_told_missing", [])
    monkeypatch.setattr(cage, "_told_at", {})


def _bwrap(monkeypatch: pytest.MonkeyPatch, *, installed: bool) -> None:
    monkeypatch.setattr(cage, "available", lambda: installed)


# ---- the switch -------------------------------------------------------------------
def test_unset_means_required_and_only_off_turns_the_cage_off() -> None:
    assert config._sandboxd({}) == "required"
    assert config._sandboxd({"AGOS_SANDBOXD": ""}) == "required"
    # The old values keep working, and none of them can fail open any more.
    for value in ("auto", "on", "required", " Required "):
        assert config._sandboxd({"AGOS_SANDBOXD": value}) == "required", value
    assert config._sandboxd({"AGOS_SANDBOXD": "off"}) == "off"
    with pytest.raises(config.ConfigError):
        config._sandboxd({"AGOS_SANDBOXD": "maybe"})


# ---- fake bwrap: present, absent, broken ------------------------------------------
def test_present_and_working_bwrap_cages_exactly_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's live server: bwrap works, so nothing changes for him."""
    _bwrap(monkeypatch, installed=True)
    body = _dropin(tmp_path, "required", _Bwrap("ok"))
    assert '"bwrap"' in body and "KillMode=control-group" in body
    assert (tmp_path / "data" / "system" / "cage.ok").is_file()


@pytest.mark.parametrize(
    ("installed", "outcome", "why"),
    [
        (False, "ok", "not installed"),
        (True, "fail", "can't run here"),
        (True, "timeout", "didn't finish"),
    ],
)
def test_no_working_bwrap_refuses_with_the_code_and_never_uncages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    installed: bool,
    outcome: str,
    why: str,
) -> None:
    _bwrap(monkeypatch, installed=installed)
    engine = _caged_engine(tmp_path, "required", _Bwrap(outcome))
    with caplog.at_level(logging.ERROR, logger="agos"), pytest.raises(CageRefused) as refused:
        engine.sandboxd_on()
    error = refused.value
    assert isinstance(error, EngineError)  # every `except EngineError` keeps working
    assert error.code == "cage_refused"
    assert "cage_refused" in str(error) and why in str(error)
    assert "AGOS_SANDBOXD=off" in str(error)  # the way out on purpose is named
    # Told where the owner looks (System Log, Settings → Errors): an agos.* ERROR.
    told = [r for r in caplog.records if "cage_refused" in r.getMessage()]
    assert told and told[0].levelno == logging.ERROR and told[0].name.startswith("agos.")


def test_a_gateway_start_without_bwrap_refuses_and_writes_no_uncaged_dropin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bwrap(monkeypatch, installed=False)
    runner = _Runner()
    engine = _caged_engine(tmp_path, "required", runner)
    _volumes(engine.root("alpha"), [f"{tmp_path / 'files'}:/workspace"])
    root_unit.remember(engine.root("alpha"), "hermes-gw-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(HERMES_UNIT)
    with pytest.raises(CageRefused, match="cage_refused"):
        engine.start("alpha", wait_s=0)
    assert not (unit.with_name(unit.name + ".d") / "agos-runtime.conf").exists()
    started = [c for c in runner.calls if c[-2:] == ["gateway", "start"]]
    assert not started  # Hermes was never asked to start the gateway
    with pytest.raises(CageRefused):
        sandbox_broker.cage_argv(engine, "alpha")
    with pytest.raises(CageRefused):
        engine.walled("alpha", ["/bin/hermes", "cron", "list"])


def test_off_on_purpose_runs_uncaged_and_says_so_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _bwrap(monkeypatch, installed=False)
    with caplog.at_level(logging.WARNING, logger="agos"):
        body = _dropin(tmp_path, "off", _Runner())
        _caged_engine(tmp_path, "off", _Runner()).sandboxd_on()
    assert '"bwrap"' not in body and "wall.py" in body
    told = [r for r in caplog.records if "AGOS_SANDBOXD=off" in r.getMessage()]
    assert len(told) == 1 and told[0].name.startswith("agos.")


# ---- the state Settings and agos doctor show --------------------------------------
def test_the_cage_state_without_running_bwrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bwrap(monkeypatch, installed=True)
    assert sandbox_broker.state(_caged_engine(tmp_path, "off", _Bwrap("ok"))) == "off"
    runner = _Bwrap("ok")
    engine = _caged_engine(tmp_path, "required", runner)
    assert sandbox_broker.state(engine) == "unchecked"
    engine.sandboxd_on()
    assert sandbox_broker.state(engine) == "ok"
    broken = _caged_engine(tmp_path, "required", _Bwrap("fail"))
    with pytest.raises(CageRefused):
        broken.sandboxd_on()
    assert sandbox_broker.state(broken) == "refused"
    _bwrap(monkeypatch, installed=False)
    assert sandbox_broker.state(_caged_engine(tmp_path, "required", _Bwrap("ok"))) == "refused"


# ---- the API answer ---------------------------------------------------------------
def test_a_refused_cage_answers_with_its_code_and_what_to_do() -> None:
    assert ErrorCode.CAGE_REFUSED.value == "cage_refused"
    assert "agos doctor" in TEXTS[ErrorCode.CAGE_REFUSED].what_to_do
    app = FastAPI()
    for exc, handler in error_bodies.error_handlers().items():
        app.add_exception_handler(exc, handler)

    @app.get("/start")
    async def start() -> None:
        raise CageRefused("Workspace isolation can't be built (cage_refused): bwrap is missing")

    answer = TestClient(app, raise_server_exceptions=False).get("/start")
    assert answer.status_code == 503
    body = answer.json()
    assert body["code"] == "cage_refused"
    assert body["help"] == TEXTS[ErrorCode.CAGE_REFUSED].what_to_do
    assert "bwrap" in body["detail"]


# ---- Settings → Server & backup and agos doctor -----------------------------------
class _Core:
    def __init__(self, engine: Any) -> None:
        self.engine = engine


def test_settings_warns_in_the_existing_attention_lines_when_the_cage_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.actions import isolation

    _bwrap(monkeypatch, installed=True)
    off = _Core(_caged_engine(tmp_path, "off", _Bwrap("ok")))
    assert isolation.warnings(off) == [isolation.OFF_WARNING]
    assert "AGOS_SANDBOXD=off" in isolation.OFF_WARNING
    working = _Core(_caged_engine(tmp_path, "required", _Bwrap("ok")))
    working.engine.sandboxd_on()
    assert isolation.warnings(working) == []  # the owner's live server: nothing shown
    broken = _Core(_caged_engine(tmp_path, "required", _Bwrap("fail")))
    with pytest.raises(CageRefused):
        broken.engine.sandboxd_on()
    assert isolation.warnings(broken) == [isolation.REFUSED_WARNING]
    assert "cage_refused" in isolation.REFUSED_WARNING
    assert isolation.warnings(_Core(None)) == []


def test_settings_reads_the_warnings_without_running_bwrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.actions import isolation

    _bwrap(monkeypatch, installed=True)
    runner = _Bwrap("ok")
    isolation.warnings(_Core(_caged_engine(tmp_path, "required", runner)))
    assert not [c for c in runner.calls if c[:1] == [cage.BWRAP]]


def test_the_server_page_lists_the_isolation_warning_with_the_backup_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agos_core.actions import backups, isolation, ops_watch

    monkeypatch.setattr(ops_watch, "backup_warnings", lambda core: ["no backup"])
    monkeypatch.setattr(isolation, "warnings", lambda core: [isolation.OFF_WARNING])
    assert backups._warnings(object()) == [isolation.OFF_WARNING, "no backup"]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mode", "installed", "outcome", "said"),
    [
        ("required", True, "ok", "- cage: ok"),
        ("required", False, "ok", "- cage: REFUSED (cage_refused)"),
        ("required", True, "fail", "- cage: REFUSED (cage_refused)"),
        ("off", True, "ok", "- cage: OFF"),
    ],
)
def test_agos_doctor_reports_the_cage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    installed: bool,
    outcome: str,
    said: str,
) -> None:
    from agos_core.actions import isolation

    _bwrap(monkeypatch, installed=installed)
    lines = isolation.report_lines(_Core(_caged_engine(tmp_path, mode, _Bwrap(outcome))))
    text = "\n".join(lines)
    assert lines[0] == "### Workspace isolation (the gateways' cage)"
    assert said in text
    assert f"- mode: {mode}" in text
    assert f"- bwrap: {'installed' if installed else 'missing'}" in text
    assert "- gateways caged: 0 of 0" in text


def test_doctor_counts_only_gateways_that_still_have_a_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live has leftover drop-ins of deleted workspaces beside its caged gateways."""
    from agos_core.actions import isolation

    _bwrap(monkeypatch, installed=True)
    _dropin(tmp_path, "required", _Bwrap("ok"))  # one caged gateway with its unit
    units = tmp_path / ".config" / "systemd" / "user"
    gone = units / "hermes-gw-gone.service.d"
    gone.mkdir(parents=True)
    (gone / "agos-runtime.conf").write_text(f"ExecStart=x {tmp_path / 'data' / 'hermes'}/agos-b\n")
    lines = isolation.report_lines(_Core(_caged_engine(tmp_path, "required", _Bwrap("ok"))))
    assert "- gateways caged: 1 of 1" in lines
