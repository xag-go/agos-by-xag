"""Settings → General → Hermes update: the check is Hermes's own `update --plan`
answer, "do the update" runs docs/hermes-upgrade.md's tested order, and a failure
puts the old release back only while no gateway ran the new code."""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import hermes_update as actions
from agos_core.actions.errors import ActionError
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine import hermes_update as engine_update
from agos_core.engine.hermes import EngineError, HermesEngine

BANNER = "Hermes Agent v{v} (2026.9.24) · stable · local {sha}"
PLAN = "Update plan:\n  Install: git (v{v} @ {sha})\n  Profiles: default\n"
MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


class Recorder:
    """Answers `hermes`/`git` the way engine/hermes_update runs them, and keeps
    every call (the order is the test's assertion)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.current = ("0.22.2", "d923a5eb487a17c0a68801bba9ef0f56c81040a8")
        self.offered = ("0.22.3", "feedc0ffee487a17c0a68801bba9ef0f56c81040")
        self.update_lands_on: tuple[str, str] | None = None  # None: lands on offered
        self.log = "aaaa111 One fix\nbbbb222 One feature"

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        args = list(args)
        self.calls.append(args)
        if args[1:] == ["--version"]:
            return BANNER.format(v=self.current[0], sha=self.current[1])
        if args[1:4] == ["update", "--plan", "--channel"]:
            return PLAN.format(v=self.offered[0], sha=self.offered[1][:8])
        if args[1:3] == ["update", "--channel"]:
            self.current = self.update_lands_on or self.offered
            return "updated"
        if args[1:3] == ["pm", "repair"]:
            self.current = self.offered
            return "repaired"
        if args[0] == "git":
            verb = args[3]
            if verb == "rev-parse":
                return self.offered[1]
            if verb == "log":
                return self.log
            if verb == "checkout":
                self.current = self.offered if args[-1] == self.offered[1] else self.current
                return ""
            return ""
        return ""

    def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:  # pragma: no cover
        raise AssertionError("the update spawns nothing")


def _engine(tmp_path: Path) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "roots",
            gateway_supervisor="spawn",
            hermes_src=tmp_path / "hermes-src",
        ),
        runner=Recorder(),
    )


def test_the_check_says_up_to_date_when_the_plan_names_the_installed_release(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    engine.runner.offered = engine.runner.current  # type: ignore[attr-defined]
    found = engine_update.check(engine)
    assert found.target is None and found.fits is None


def test_the_check_reads_the_release_its_fit_and_its_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)
    monkeypatch.setattr("agos_core.engine.hermes_contract.check", lambda tree: [])
    monkeypatch.setattr("agos_core.engine.hermes_contract.report", lambda f, t: "all ok")
    found = engine_update.check(engine)
    assert found.target == engine_update.Release("0.22.3", "feedc0ff")
    assert found.fits is True and found.news == ["One fix", "One feature"]
    worktrees = [c for c in engine.runner.calls if c[0] == "git" and c[3] == "worktree"]  # type: ignore[attr-defined]
    assert [c[4] for c in worktrees] == ["add", "remove", "prune"]  # made, then gone


def test_a_release_agos_does_not_fit_is_told_with_the_checkers_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(tmp_path)

    class Broken:
        ok = False

    monkeypatch.setattr("agos_core.engine.hermes_contract.check", lambda tree: [Broken()])
    monkeypatch.setattr("agos_core.engine.hermes_contract.report", lambda f, t: "FAIL one")
    found = engine_update.check(engine)
    assert found.fits is False and "FAIL one" in found.report


def test_a_channel_that_moved_on_lands_pinned_on_the_checked_release(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    runner: Any = engine.runner
    runner.update_lands_on = ("0.22.4", "0123456789abcdef0123456789abcdef01234567")
    engine_update.install(engine, engine_update.Release("0.22.3", runner.offered[1][:8]))
    flat = [" ".join(c) for c in runner.calls]
    assert any("checkout --detach" in c for c in flat)
    assert any("pm repair" in c for c in flat)
    assert runner.current == runner.offered


@pytest.fixture
def app(tmp_path: Path) -> Iterator[tuple[TestClient, Any, str]]:
    hermes_home = tmp_path / ".hermes"
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    application = create_app(settings, background=False)
    with TestClient(application) as client:
        core = application.state.core
        core.engine.runner = FakeRunner(hermes_home)
        core.engine.is_running = lambda workspace_id: False
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        yield client, core, ws


def _fresh_check(core: Any, *, fits: bool = True) -> None:
    set_setting(
        core.db,
        actions.KEY_CHECK,
        {
            "at": actions._now(),
            "current": {"version": "0.22.2", "sha": "d923a5eb487a"},
            "target": {"version": "0.22.3", "sha": "feedc0ff"},
            "fits": fits,
            "report": "",
            "news": ["One fix"],
        },
    )


def test_do_the_update_wants_a_fresh_fitting_check_first(app: Any) -> None:
    client, core, _ws = app
    assert client.post("/hermes-update/run").status_code == 400  # never checked
    _fresh_check(core, fits=False)
    with pytest.raises(ActionError, match="doesn't fit"):
        actions.start_update(core)
    _fresh_check(core)
    check = get_setting(core.db, actions.KEY_CHECK, None)
    check["at"] = "2026-01-01T00:00:00+00:00"
    set_setting(core.db, actions.KEY_CHECK, check)
    with pytest.raises(ActionError, match="old"):
        actions.start_update(core)


def _wait_phase(core: Any, *phases: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = get_setting(core.db, actions.KEY_STATE, None)
        if isinstance(state, dict) and state.get("phase") in phases:
            return state
        time.sleep(0.05)
    raise AssertionError(f"never reached {phases}: {get_setting(core.db, actions.KEY_STATE, None)}")


def test_the_update_runs_the_tested_order_and_reports(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, ws = app
    order: list[str] = []

    def fake_backups(e: Any, homes: Any, into: Any) -> list[Path]:
        order.append("backups")
        return []

    monkeypatch.setattr(engine_update, "backup_roots", fake_backups)
    monkeypatch.setattr(engine_update, "install", lambda e, t: order.append("install"))
    monkeypatch.setattr(
        engine_update, "prepare_home", lambda e, home: order.append(f"prepare {home.name}")
    )
    monkeypatch.setattr(core.engine, "stop", lambda w, **_: order.append(f"stop {w}"))
    monkeypatch.setattr(core.engine, "serve", lambda w, **_: order.append(f"serve {w}"))
    _fresh_check(core)
    actions.start_update(core)
    state = _wait_phase(core, "done", "failed")
    assert state["phase"] == "done", state
    assert order[0] == "backups" and order[1] == f"stop {ws}" and order[2] == "install"
    assert order[3] == "prepare .hermes"  # the shared home first
    assert order[-1] == f"serve {ws}"  # gateways come back last
    assert state["report"]["to"] == "0.22.3" and state["report"]["workspaces"] == 1
    assert get_setting(core.db, actions.KEY_CHECK, None) is None  # spent
    assert client.get("/hermes-update").json()["state"]["phase"] == "done"


def test_a_failure_before_any_gateway_puts_the_old_release_back(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, core, ws = app
    order: list[str] = []
    monkeypatch.setattr(engine_update, "backup_roots", lambda e, homes, into: [])
    monkeypatch.setattr(engine_update, "install", lambda e, t: order.append("install"))

    def boom(engine: Any, home: Path) -> None:
        raise EngineError("that home didn't prepare")

    monkeypatch.setattr(engine_update, "prepare_home", boom)
    monkeypatch.setattr(
        engine_update, "roll_back_code", lambda e, before: order.append(f"back {before.version}")
    )
    monkeypatch.setattr(core.engine, "stop", lambda w, **_: None)
    monkeypatch.setattr(core.engine, "serve", lambda w, **_: order.append(f"serve {w}"))
    _fresh_check(core)
    actions.start_update(core)
    state = _wait_phase(core, "done", "failed")
    assert state["phase"] == "failed" and state["rolled_back"] is True
    assert "that home didn't prepare" in state["error"]
    assert order == ["install", "back 0.22.2", f"serve {ws}"]  # old code, gateways back


def test_one_update_at_a_time(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _client, core, _ws = app
    set_setting(core.db, actions.KEY_STATE, {"phase": "install"})
    with pytest.raises(ActionError, match="already running"):
        actions.start_update(core)
    with pytest.raises(ActionError, match="running"):
        actions.run_check(core)
