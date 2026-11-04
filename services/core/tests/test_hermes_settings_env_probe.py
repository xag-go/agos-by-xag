"""Settings → Hermes settings, its ".env vs config.yaml" probe (env_probe_rig): which
of Hermes's env settings the gateway really uses, asked with the managed scope, kept
on what the files hold, shared by callers asking together, at most four Hermes runs
at once, and what a refusal or a brand-new root answers.

Split out of test_hermes_all_settings.py (the page's rows and writes stay there)."""

import json
import time
from pathlib import Path
from typing import Any

import pytest
from env_probe_rig import (
    NOT_SET_UP,
    _env_probe_engine,
    _gateway_run,
    _one_after_the_other,
    _side,
    _side_kind,
    _yaml_run,
)
from test_library import env, ws  # noqa: F401 - fixture

# Moved out of a HERMES_FILES file (conftest.py): it needs the installed Hermes too.
pytestmark = pytest.mark.hermes


def test_env_probe_runs_with_the_managed_scope_and_follows_its_files(tmp_path: Path) -> None:
    """NB-6: the ".env vs config.yaml" probe runs Hermes's gateway start WITH the
    managed scope (as the gateway's unit has it); its YAML side gets a scope holding
    only the managed config.yaml; the cache follows the managed files too."""
    from agos_core.engine import hermes as engine_mod

    assert '"HERMES_MANAGED_DIR"' in engine_mod._ENV_IN_USE  # kept in the scrubbed env
    assert "load_managed_env" in engine_mod._ENV_IN_USE
    engine, home, managed, calls = _env_probe_engine(tmp_path)
    probe = engine_mod.HermesEngine.env_in_use
    found = probe(engine, home)
    assert found["managed"] == ["TERMINAL_TIMEOUT"] and found["yaml"]
    # YAML side: a throwaway home holding only config.yaml, a throwaway scope holding
    # only the managed config.yaml (no .env).
    yaml_run, gateway_run = _yaml_run(calls), _gateway_run(calls)
    assert yaml_run["home_files"] == ["config.yaml"] and yaml_run["scope_files"] == ["config.yaml"]
    assert yaml_run["job"]["home"] != str(home)
    assert gateway_run["home"] == home and gateway_run["extra"] is None  # the real scope
    probe(engine, home)
    assert len(calls) == 2  # cached
    time.sleep(0.01)
    (managed / ".env").write_text("TERMINAL_TIMEOUT=400\n")
    probe(engine, home)
    # A managed change is seen at once; the managed .env is only the gateway's side
    # (the YAML side's scope holds the managed config.yaml alone).
    assert len(calls) == 3 and not calls[2]["job"].get("diff")
    (managed / "config.yaml").write_text("terminal:\n  timeout: 400\n")
    probe(engine, home)
    assert len(calls) == 5


def test_env_probe_never_starts_hermes_in_a_fresh_home(tmp_path: Path) -> None:
    """Step 38: a Hermes process started with a brand-new HERMES_HOME is a data root
    of its own (hermes_constants.get_default_hermes_root), so Hermes's launch first
    builds a whole dependency environment there (hermes_cli/venv_sync.py
    prepare_launch → _prepare_borrowed_launch: `uv venv`, `uv sync`, ~400 MB, ~50 s
    calm, minutes busy). Both runs start in the profile's own home, whose root's
    environment its gateway already runs on; the YAML side's throwaway home and
    scope are named in the job, and Hermes's own start is pointed at them inside
    the process (Hermes reads HERMES_HOME / HERMES_MANAGED_DIR when asked)."""
    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, calls = _env_probe_engine(tmp_path)
    engine_mod.HermesEngine.env_in_use(engine, home)
    assert [c["home"] for c in calls] == [home, home]
    assert _yaml_run(calls)["extra"] is None  # no other scope at process start either
    assert _yaml_run(calls)["job"]["home"] and _yaml_run(calls)["job"]["scope"]
    script = engine_mod._ENV_IN_USE
    switch = script.index('os.environ["HERMES_HOME"] = job["home"]')
    assert switch < script.index("start = dict(os.environ)") < script.index("import gateway.run")
    assert 'os.environ["HERMES_MANAGED_DIR"] = job["scope"]' in script
    # Hermes said which home it read: a Hermes that bound the home earlier fails the
    # probe instead of reporting the profile's .env as config.yaml's.
    assert "get_hermes_home" in script and "get_managed_dir" in script


def test_env_probe_keys_on_what_the_files_hold(tmp_path: Path) -> None:
    """The same text written again (a Hermes `config set` that changed nothing, a
    copy) keeps Hermes's answer; another text asks again."""
    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, calls = _env_probe_engine(tmp_path)
    probe = engine_mod.HermesEngine.env_in_use
    probe(engine, home)
    time.sleep(0.01)
    (home / "config.yaml").write_text("model: x\n")  # same text, new mtime
    (home / ".env").write_text("")  # empty = missing for Hermes, but not the same file
    probe(engine, home)
    assert len(calls) == 3  # a new .env file: the gateway's side asked again
    assert not calls[2]["job"].get("diff")  # (the YAML side never reads .env)
    (home / ".env").write_text("")
    probe(engine, home)
    assert len(calls) == 3  # rewritten with the same text: kept
    (home / "config.yaml").write_text("model: y\n")
    probe(engine, home)
    assert len(calls) == 5  # both sides read config.yaml


def test_env_probe_callers_together_share_one_ask(tmp_path: Path) -> None:
    """The page asks every profile at once and the read-ahead may be asking the same
    one: one pair of Hermes runs per profile, the others wait for it."""
    import threading

    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, calls = _env_probe_engine(tmp_path)
    slow = engine._in_runtime
    gate = threading.Event()

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        gate.wait(5)
        return slow(h, script, tag, **kw)  # type: ignore[no-any-return]

    engine._in_runtime = in_runtime
    got: list[Any] = []
    threads = [
        threading.Thread(
            target=lambda: got.append(engine_mod.HermesEngine.env_in_use(engine, home))
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    time.sleep(0.05)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(got) == 4 and len(calls) == 2


def test_env_probe_runs_its_two_hermes_runs_side_by_side(tmp_path: Path) -> None:
    """Step 41: the probe's YAML side and the gateway's side ran one after the other
    (the second was given the first's names): ~2.3 s of the page's wait after one
    profile changed. They now start at once (the gateway's side reports every UPPER
    name its start left, AGOS keeps the YAML side's), and the answer is the one the
    two runs one after the other gave."""
    import threading

    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, calls = _env_probe_engine(tmp_path)
    answer = engine._in_runtime
    both = threading.Barrier(2, timeout=5)

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        both.wait()  # breaks (and fails the probe) unless both runs are in flight
        return answer(h, script, tag, **kw)  # type: ignore[no-any-return]

    engine._in_runtime = in_runtime
    found = engine_mod.HermesEngine.env_in_use(engine, home)
    assert len(calls) == 2
    # One after the other: the gateway's values of the YAML side's names and the
    # .env's names, sorted; the YAML side's diff; the managed .env's names.
    assert json.dumps(found) == json.dumps(
        {
            "used": {"TELEGRAM_REACTIONS": "true", "TERMINAL_TIMEOUT": "300"},
            "yaml": {"TERMINAL_TIMEOUT": "300", "TELEGRAM_REACTIONS": "false"},
            "managed": ["TERMINAL_TIMEOUT"],
        }
    )


def test_settings_reads_start_at_most_four_hermes_at_once(tmp_path: Path) -> None:
    """Each probe's two runs start at once, and the page asks four profiles at once:
    still at most four Hermes processes (100-200 MB each) for these reads, whoever
    asks (the page, the read-ahead, a warm-up after a save)."""
    import threading

    from agos_core.engine import hermes as engine_mod

    engine, _home, _managed, _calls = _env_probe_engine(tmp_path)
    answer = engine._in_runtime
    lock = threading.Lock()
    running = [0, 0]

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        with lock:
            running[0] += 1
            running[1] = max(running)
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        return answer(h, script, tag, **kw)  # type: ignore[no-any-return]

    engine._in_runtime = in_runtime
    homes = []
    for n in range(6):
        h = tmp_path / f"p{n}"
        h.mkdir()
        (h / "config.yaml").write_text(f"model: m{n}\n")
        homes.append(h)
    threads = [
        threading.Thread(target=engine_mod.HermesEngine.env_in_use, args=(engine, h)) for h in homes
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert 2 <= running[1] <= 4, running


@pytest.mark.parametrize("second", ["yaml", "gateway"])
def test_env_probe_in_a_brand_new_root_gets_hermess_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, second: str
) -> None:
    """A brand-new root (or a profile home outside ~/.hermes) has no dependency
    environment yet: the first Hermes start builds it (hermes_cli/venv_sync.py
    prepare_launch, seconds to minutes) and a start made meanwhile is refused at once.
    The probe's two runs started together, so the page got that refusal instead of
    Hermes's answer. The refused run now asks again once, after the other run ended:
    the answer the two runs one after the other gave, from three Hermes runs, kept."""
    import threading

    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, _calls = _env_probe_engine(tmp_path)
    answer = engine._in_runtime
    lock = threading.Lock()
    setting_up, refused = threading.Event(), threading.Event()
    ready: list[bool] = []
    runs: list[str] = []

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        side = _side(script)
        if side == second and not ready:
            setting_up.wait(5)  # this run starts while the other one sets the root up
        with lock:
            runs.append(side)
            if setting_up.is_set() and not ready:
                refused.set()
                raise engine_mod.EngineError(NOT_SET_UP)
            first = not ready
            setting_up.set()
        if first:
            refused.wait(5)  # the setup outlasts the start made meanwhile
            ready.append(True)
        return answer(h, script, tag, **kw)  # type: ignore[no-any-return]

    engine._in_runtime = in_runtime
    found = engine_mod.HermesEngine.env_in_use(engine, home)
    assert json.dumps(found) == _one_after_the_other(tmp_path, monkeypatch)
    assert len(runs) == 3 and runs.count(second) == 2, runs
    engine_mod.HermesEngine.env_in_use(engine, home)
    assert len(runs) == 3  # Hermes's answer is kept, not its refusal


def test_env_probe_runs_both_refused_ask_again_one_after_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both runs refused (another start, e.g. a sibling profile's probe, sets the
    root up): each asks again once, one after the other, so the first of them can set
    the root up and the other finds it."""
    import threading

    from agos_core.engine import hermes as engine_mod

    engine, home, _managed, _calls = _env_probe_engine(tmp_path)
    answer = engine._in_runtime
    lock = threading.Lock()
    both = threading.Barrier(2, timeout=5)
    runs: list[str] = []
    running = [0, 0]

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        with lock:
            runs.append(_side(script))
            asked = len(runs)
        if asked <= 2:
            both.wait()  # both in flight while the other start sets the root up
            raise engine_mod.EngineError(NOT_SET_UP)
        with lock:
            running[0] += 1
            running[1] = max(running)
        time.sleep(0.1)
        with lock:
            running[0] -= 1
        return answer(h, script, tag, **kw)  # type: ignore[no-any-return]

    engine._in_runtime = in_runtime
    found = engine_mod.HermesEngine.env_in_use(engine, home)
    assert json.dumps(found) == _one_after_the_other(tmp_path, monkeypatch)
    assert len(runs) == 4 and sorted(runs[2:]) == ["gateway", "yaml"], runs
    assert running[1] == 1  # the second asks went one after the other


@pytest.mark.parametrize("refused", ["yaml", "gateway"])
def test_env_probe_raises_other_errors_and_a_second_refusal_as_hermes_said(
    tmp_path: Path, refused: str
) -> None:
    """Only that refusal is asked again, and only once: any other error of a run is
    raised at once (no other run), and a run Hermes refuses twice raises the refusal."""
    from agos_core.engine import hermes as engine_mod
    from agos_core.engine import hermes_contract as hc

    # The line AGOS looks for is Hermes's own, checked on every Hermes upgrade.
    assert engine_mod.HERMES_SETTING_UP in NOT_SET_UP
    assert f'"{engine_mod.HERMES_SETTING_UP}"' in {u.text for u in hc.CONTRACT}
    engine, home, _managed, calls = _env_probe_engine(tmp_path)
    answer = engine._in_runtime
    said = {"error": "Hermes didn't answer: boom"}

    def in_runtime(h: Path, script: str, tag: str, **kw: Any) -> str:
        out: str = answer(h, script, tag, **kw)
        if _side(script) == refused:
            raise engine_mod.EngineError(said["error"])
        return out

    engine._in_runtime = in_runtime
    with pytest.raises(engine_mod.EngineError, match="boom"):
        engine_mod.HermesEngine.env_in_use(engine, home)
    assert len(calls) == 2
    said["error"] = NOT_SET_UP
    engine._env_use.drop()
    engine._env_yaml.drop()
    with pytest.raises(engine_mod.EngineError, match="no dependency environment is committed"):
        engine_mod.HermesEngine.env_in_use(engine, home)
    assert len(calls) == 2 + 3
    assert [_side_kind(c) for c in calls[2:]].count(refused) == 2
