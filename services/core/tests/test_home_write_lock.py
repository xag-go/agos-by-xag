"""Hermes's `config set` rewrites the whole config.yaml with no lock across processes
(hermes_cli/config.py set_config_value -> atomic_config_replace; only .env has one),
so two AGOS writes on one home at once could lose one of them. AGOS runs every
Hermes command that can write a home's config one at a time per home (a thread lock
plus a file lock other processes can take too)."""

import fcntl
import threading
import time
from pathlib import Path
from typing import Any

from agos_core.config import EngineConfig
from agos_core.engine import hermes as engine_module
from agos_core.engine.hermes import HermesEngine


class _SlowRunner:
    """Simulates `hermes config set`: read the file, wait, write it back whole."""

    def __init__(self) -> None:
        self.overlap = 0
        self.active = 0
        self.guard = threading.Lock()

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        home = Path(env["HERMES_HOME"])
        writes = args[1:3] in (["config", "set"], ["config", "unset"])
        if writes:
            with self.guard:
                self.active += 1
                self.overlap = max(self.overlap, self.active)
            cfg = home / "config.yaml"
            have = cfg.read_text() if cfg.exists() else ""
            time.sleep(0.02)
            cfg.write_text(have + f"{args[3]}: {args[4]}\n")
            with self.guard:
                self.active -= 1
        return ""

    def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
        return None


def _engine(tmp_path: Path, runner: Any) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "data" / "hermes",
            runtime_dir=tmp_path / ".hermes" / "tools",
        ),
        runner=runner,
    )


def test_writes_on_one_home_never_overlap_and_none_is_lost(tmp_path: Path) -> None:
    runner = _SlowRunner()
    engine = _engine(tmp_path, runner)
    home = engine.profile_home("alpha")
    home.mkdir(parents=True)
    threads = [
        threading.Thread(target=engine._hermes, args=("alpha", "config", "set", f"k{i}", "v"))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    text = (home / "config.yaml").read_text()
    assert runner.overlap == 1
    assert all(f"k{i}: v" in text for i in range(8)), text


def test_another_process_holding_the_homes_lock_is_waited_for(tmp_path: Path) -> None:
    runner = _SlowRunner()
    engine = _engine(tmp_path, runner)
    home = engine.profile_home("alpha")
    home.mkdir(parents=True)
    lock = home / engine_module.HOME_LOCK
    done: list[float] = []
    with lock.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)

        def write() -> None:
            engine._hermes("alpha", "config", "set", "k", "v")
            done.append(1.0)

        t = threading.Thread(target=write)
        t.start()
        time.sleep(0.2)
        assert not done  # still waiting for the other holder (e.g. the e2e rig)
        fcntl.flock(held, fcntl.LOCK_UN)
    t.join(5)
    assert done


def test_a_nested_write_on_the_same_home_does_not_deadlock(tmp_path: Path) -> None:
    runner = _SlowRunner()
    engine = _engine(tmp_path, runner)
    home = engine.profile_home("alpha")
    home.mkdir(parents=True)
    with engine_module.home_write_lock(home):
        engine._hermes("alpha", "config", "set", "inner", "1")
    assert "inner: 1" in (home / "config.yaml").read_text()
